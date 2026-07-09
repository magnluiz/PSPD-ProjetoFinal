/**
 * k6 load test for the hospital microservices API.
 *
 * Runs a mix of realistic requests (médico summary, estagiário summary,
 * pesquisador stats + streamed cohort) through the API Gateway.
 *
 * Usage:
 *   BASE_URL=http://<gateway-host>:30080 k6 run -e STAGE=10 load-test.js
 *   (repeat with STAGE=50,100,500,1000 -- see run-all.sh)
 *
 * By default, obtains real Keycloak JWTs during setup and sends Bearer tokens
 * to the gateway. Set AUTH_MODE=insecure-dev to use x-username/x-role headers
 * when you explicitly want to isolate backend performance from JWT validation.
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";

http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 403));

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const KEYCLOAK_URL = __ENV.KEYCLOAK_URL || "http://localhost:8081";
const AUTH_MODE = __ENV.AUTH_MODE || "keycloak";
const PASSWORD = __ENV.TEST_PASSWORD || "senha123";
const VUS = parseInt(__ENV.STAGE || "10", 10);
const DURATION = __ENV.DURATION || "60s";

const errorCount = new Counter("app_errors");
const denyCount = new Counter("app_denies");
const summaryTrend = new Trend("resumo_clinico_duration");
const statsTrend = new Trend("estatisticas_duration");

export const options = {
  scenarios: {
    ramping_load: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "15s", target: VUS },
        { duration: DURATION, target: VUS },
        { duration: "10s", target: 0 },
      ],
      gracefulRampDown: "5s",
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<3000"],
    http_req_failed: ["rate<0.05"],
  },
};

// Test identities matching db/seed.py -- adjust patient IDs to ones that
// actually exist in your seeded DB (P000001..P0000NN).
const MEDICOS = ["med.cardoso", "med.souza", "med.lima", "med.alves", "med.rocha"];
const ESTAGIARIOS = ["est.silva", "est.pereira", "est.costa", "est.santos", "est.oliveira"];
const PESQUISADORES = ["pesq.franca", "pesq.dias", "pesq.moura"];
const PATIENT_IDS = Array.from({ length: 300 }, (_, i) => `P${String(i + 1).padStart(6, "0")}`);
const PROJECT_IDS = ["1", "2", "3", "4", "5", "6"];
const USERS = [...MEDICOS, ...ESTAGIARIOS, ...PESQUISADORES];

function randomOf(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function tokenFor(username) {
  const res = http.post(
    `${KEYCLOAK_URL}/realms/hospital/protocol/openid-connect/token`,
    {
      client_id: "hospital-frontend",
      grant_type: "password",
      username,
      password: PASSWORD,
    }
  );
  check(res, { "keycloak token ok": (r) => r.status === 200 && r.json("access_token") });
  return res.json("access_token");
}

export function setup() {
  if (AUTH_MODE === "insecure-dev") return { tokens: {} };
  const tokens = {};
  for (const username of USERS) {
    tokens[username] = tokenFor(username);
  }
  return { tokens };
}

function authHeaders(username, role, data) {
  if (AUTH_MODE === "insecure-dev") {
    return { "x-username": username, "x-role": role };
  }
  return { "Authorization": `Bearer ${data.tokens[username]}` };
}

export default function (data) {
  const scenario = Math.random();

  if (scenario < 0.5) {
    // médico querying resumo clínico
    const username = randomOf(MEDICOS);
    const patientId = randomOf(PATIENT_IDS);
    const res = http.get(`${BASE_URL}/api/patients/${patientId}/resumo-clinico`, {
      headers: authHeaders(username, "medico", data),
    });
    summaryTrend.add(res.timings.duration);
    if (res.status === 403) denyCount.add(1);
    else if (res.status !== 200) errorCount.add(1);
    check(res, { "status is 200 or 403": (r) => r.status === 200 || r.status === 403 });
  } else if (scenario < 0.8) {
    // estagiário querying resumo clínico
    const username = randomOf(ESTAGIARIOS);
    const patientId = randomOf(PATIENT_IDS);
    const res = http.get(`${BASE_URL}/api/patients/${patientId}/resumo-clinico`, {
      headers: authHeaders(username, "estagiario", data),
    });
    summaryTrend.add(res.timings.duration);
    if (res.status === 403) denyCount.add(1);
    else if (res.status !== 200) errorCount.add(1);
    check(res, { "status is 200 or 403": (r) => r.status === 200 || r.status === 403 });
  } else {
    // pesquisador querying aggregated stats
    const username = randomOf(PESQUISADORES);
    const projectId = randomOf(PROJECT_IDS);
    const res = http.get(`${BASE_URL}/api/coorte/${projectId}/estatisticas`, {
      headers: authHeaders(username, "pesquisador", data),
    });
    statsTrend.add(res.timings.duration);
    if (res.status === 403) denyCount.add(1);
    else if (res.status !== 200) errorCount.add(1);
    check(res, { "status is 200 or 403": (r) => r.status === 200 || r.status === 403 });
  }

  sleep(Math.random() * 1.5 + 0.5);
}
