/**
 * API Gateway
 * -----------
 * - Receives REST requests from the frontend
 * - Validates JWT (issued by Keycloak)
 * - Calls AuthorizationService.CheckAccess to get ALLOW/DENY + access_level
 * - Calls PatientDataService for raw rows
 * - Calls DataTransformService to redact + convert to FHIR
 * - Exposes Prometheus metrics at /metrics
 */
const express = require("express");
const path = require("path");
const grpc = require("@grpc/grpc-js");
const protoLoader = require("@grpc/proto-loader");
const client = require("prom-client");

const { authMiddleware } = require("./auth");

const PROTO_PATH = path.join(__dirname, "hospital.proto");
const packageDef = protoLoader.loadSync(PROTO_PATH, {
  keepCase: false,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true,
});
const hospitalProto = grpc.loadPackageDefinition(packageDef).hospital;

const AUTHZ_ADDR = process.env.AUTHZ_ADDR || "localhost:50051";
const PATIENT_DATA_ADDR = process.env.PATIENT_DATA_ADDR || "localhost:50052";
const TRANSFORM_ADDR = process.env.TRANSFORM_ADDR || "localhost:50053";

const authzClient = new hospitalProto.AuthorizationService(
  AUTHZ_ADDR,
  grpc.credentials.createInsecure()
);
const patientDataClient = new hospitalProto.PatientDataService(
  PATIENT_DATA_ADDR,
  grpc.credentials.createInsecure()
);
const transformClient = new hospitalProto.DataTransformService(
  TRANSFORM_ADDR,
  grpc.credentials.createInsecure()
);

function grpcCall(client, method, request) {
  return new Promise((resolve, reject) => {
    client[method](request, (err, response) => {
      if (err) return reject(err);
      resolve(response);
    });
  });
}

function parseFHIRBundle(bundle) {
  return (bundle.entries || []).map((entry) => JSON.parse(entry.jsonPayload));
}

// ---------------- Prometheus metrics ----------------
const register = new client.Registry();
client.collectDefaultMetrics({ register });

const httpRequestDuration = new client.Histogram({
  name: "gateway_http_request_duration_seconds",
  help: "Duration of HTTP requests in seconds",
  labelNames: ["method", "route", "status"],
  buckets: [0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5],
});
register.registerMetric(httpRequestDuration);

const httpRequestsTotal = new client.Counter({
  name: "gateway_http_requests_total",
  help: "Total HTTP requests",
  labelNames: ["method", "route", "status"],
});
register.registerMetric(httpRequestsTotal);

const authzDenials = new client.Counter({
  name: "gateway_authz_denials_total",
  help: "Total requests denied by AuthorizationService",
  labelNames: ["role"],
});
register.registerMetric(authzDenials);

const grpcErrors = new client.Counter({
  name: "gateway_grpc_errors_total",
  help: "Total gRPC errors seen by the gateway",
  labelNames: ["service"],
});
register.registerMetric(grpcErrors);

// ---------------- App setup ----------------
const app = express();
app.use(express.json());
app.use((req, res, next) => {
  res.set("Access-Control-Allow-Origin", req.header("origin") || "*");
  res.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.set("Access-Control-Allow-Headers", "Authorization,Content-Type");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

app.use((req, res, next) => {
  const end = httpRequestDuration.startTimer();
  res.on("finish", () => {
    const labels = { method: req.method, route: req.route ? req.route.path : req.path, status: res.statusCode };
    end(labels);
    httpRequestsTotal.inc(labels);
  });
  next();
});

app.get("/metrics", async (req, res) => {
  res.set("Content-Type", register.contentType);
  res.end(await register.metrics());
});

app.get("/healthz", (req, res) => res.json({ status: "ok" }));

// ---------------- Routes ----------------

// GET /api/patients/:id/resumo-clinico  (médico/estagiário)
app.get("/api/patients/:id/resumo-clinico", authMiddleware, async (req, res) => {
  await handlePatientQuery(req, res, "ResumoClinico");
});

// GET /api/patients/:id/historico-clinico (médico/estagiário)
app.get("/api/patients/:id/historico-clinico", authMiddleware, async (req, res) => {
  await handlePatientQuery(req, res, "HistoricoClinico");
});

async function handlePatientQuery(req, res, queryType) {
  const { username, role } = req.user;
  const patientId = req.params.id;
  try {
    const access = await grpcCall(authzClient, "CheckAccess", {
      username,
      role,
      queryType,
      patientId,
      projectId: "",
    });
    if (!access.allow) {
      authzDenials.inc({ role });
      return res.status(403).json({ error: "access denied", reason: access.reason });
    }

    const method = queryType === "HistoricoClinico" ? "GetPatientHistory" : "GetPatientSummary";
    const raw = await grpcCall(patientDataClient, method, { patientId });

    const bundle = await grpcCall(transformClient, "ToFHIRBundle", {
      patients: [raw],
      accessLevel: access.accessLevel,
    });
    const resources = parseFHIRBundle(bundle);
    const patientResource = resources.find((resource) => resource.resourceType === "Patient") || null;

    res.json({
      accessLevel: access.accessLevel,
      resource: patientResource,
      bundle: {
        resourceType: "Bundle",
        type: queryType === "HistoricoClinico" ? "history" : "collection",
        total: resources.length,
        entry: resources.map((resource) => ({ resource })),
      },
      resources,
    });
  } catch (err) {
    grpcErrors.inc({ service: err.service || "unknown" });
    res.status(502).json({ error: "upstream service error", detail: err.message });
  }
}

// GET /api/patients (list of patients the caregiver can see)
app.get("/api/patients", authMiddleware, async (req, res) => {
  const { username, role } = req.user;
  try {
    const list = await grpcCall(patientDataClient, "GetPatientsByCaregiver", { username, role });
    res.json({ patientIds: list.patientIds });
  } catch (err) {
    res.status(502).json({ error: "upstream service error", detail: err.message });
  }
});

// GET /api/coorte/:projectId/estatisticas (pesquisador, AGGREGATED)
app.get("/api/coorte/:projectId/estatisticas", authMiddleware, async (req, res) => {
  const { username, role } = req.user;
  const projectId = req.params.projectId;
  try {
    const access = await grpcCall(authzClient, "CheckAccess", {
      username,
      role,
      queryType: "Estatisticas",
      patientId: "",
      projectId,
    });
    if (!access.allow) {
      authzDenials.inc({ role });
      return res.status(403).json({ error: "access denied", reason: access.reason });
    }

    const stats = await grpcCall(patientDataClient, "GetAggregatedStats", { projectId });
    res.json({ accessLevel: access.accessLevel, stats });
  } catch (err) {
    grpcErrors.inc({ service: err.service || "unknown" });
    res.status(502).json({ error: "upstream service error", detail: err.message });
  }
});

// GET /api/coorte/:projectId/exames (pesquisador, ANONYMIZED, streamed cohort)
app.get("/api/coorte/:projectId/exames", authMiddleware, async (req, res) => {
  const { username, role } = req.user;
  const projectId = req.params.projectId;
  try {
    const access = await grpcCall(authzClient, "CheckAccess", {
      username,
      role,
      queryType: "ExamesCoorte",
      patientId: "",
      projectId,
    });
    if (!access.allow) {
      authzDenials.inc({ role });
      return res.status(403).json({ error: "access denied", reason: access.reason });
    }

    // Server-streaming call: consume patients as they arrive and pipe them
    // into the transform service. The endpoint returns only Observation
    // resources, with Patient references already pseudonymized by ANONYMIZED.
    const call = patientDataClient.StreamCohortData({ projectId });
    const observations = [];
    const errPromise = new Promise((_, reject) => call.on("error", reject));

    const collectPromise = new Promise((resolve, reject) => {
      const pipeline = transformClient.TransformPipeline();
      pipeline.on("data", (fhirResource) => {
        if (fhirResource.resourceType === "Observation") {
          observations.push(JSON.parse(fhirResource.jsonPayload));
        }
      });
      pipeline.on("end", () => resolve());
      pipeline.on("error", reject);

      call.on("data", (patient) => {
        pipeline.write({ patient, accessLevel: access.accessLevel });
      });
      call.on("end", () => pipeline.end());
    });

    await Promise.race([collectPromise, errPromise]);
    res.json({
      accessLevel: access.accessLevel,
      count: observations.length,
      bundle: {
        resourceType: "Bundle",
        type: "collection",
        total: observations.length,
        entry: observations.map((resource) => ({ resource })),
      },
      resources: observations,
    });
  } catch (err) {
    grpcErrors.inc({ service: err.service || "unknown" });
    res.status(502).json({ error: "upstream service error", detail: err.message });
  }
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`[gateway] listening on :${PORT}`);
  console.log(`[gateway] authz=${AUTHZ_ADDR} patientData=${PATIENT_DATA_ADDR} transform=${TRANSFORM_ADDR}`);
});
