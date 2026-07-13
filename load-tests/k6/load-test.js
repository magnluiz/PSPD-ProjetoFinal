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
import { check, fail, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";

http.setResponseCallback(http.expectedStatuses({ min: 200, max: 399 }, 403));

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const KEYCLOAK_URL = __ENV.KEYCLOAK_URL || "http://localhost:8081";
const KEYCLOAK_REALM = __ENV.KEYCLOAK_REALM || "hospital";
const CLIENT_ID = __ENV.CLIENT_ID || "hospital-frontend";
const AUTH_MODE = __ENV.AUTH_MODE || "keycloak";
const PASSWORD = __ENV.TEST_PASSWORD || "senha123";
const VUS = parseInt(__ENV.STAGE || "10", 10);
const DURATION = __ENV.DURATION || "60s";
const RAMP_UP = __ENV.RAMP_UP || "15s";
const RAMP_DOWN = __ENV.RAMP_DOWN || "10s";
const P95_THRESHOLD_MS = parseInt(__ENV.P95_THRESHOLD_MS || "7000", 10);
const FAIL_RATE_THRESHOLD = __ENV.FAIL_RATE_THRESHOLD || "0.05";

const errorCount = new Counter("app_errors");
const denyCount = new Counter("app_denies");
const unexpectedStatusCount = new Counter("unexpected_statuses");
const summaryTrend = new Trend("resumo_clinico_duration");
const statsTrend = new Trend("estatisticas_duration");

export const options = {
  scenarios: {
    ramping_load: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: RAMP_UP, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: RAMP_DOWN, target: 0 },
      ],
      gracefulRampDown: "5s",
    },
  },
  thresholds: {
    http_req_duration: [`p(95)<${P95_THRESHOLD_MS}`],
    http_req_failed: [`rate<${FAIL_RATE_THRESHOLD}`],
  },
};

// Test identities matching db/seed.py -- adjust patient IDs to ones that
// actually exist in your seeded DB (P000001..P0000NN).
const MEDICOS = ["med.cardoso", "med.lima", "med.almeida", "med.rocha", "med.monteiro"];
const ESTAGIARIOS = ["est.ferreira", "est.gomes", "est.costa", "est.melo", "est.dias"];
const PESQUISADORES = ["pes.mendes", "pes.araujo", "pes.silveira"];
const PATIENT_IDS = Array.from({ length: 300 }, (_, i) => `P${String(i + 1).padStart(6, "0")}`);
const PROJECT_IDS = ["PRJ01", "PRJ02", "PRJ03", "PRJ04", "PRJ05", "PRJ06"];
const USERS = [...MEDICOS, ...ESTAGIARIOS, ...PESQUISADORES];

function randomOf(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function tokenFor(username) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const res = http.post(
      `${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token`,
      {
        client_id: CLIENT_ID,
        grant_type: "password",
        username,
        password: PASSWORD,
      }
    );
    if (res.status === 200 && res.json("access_token")) {
      check(res, { "keycloak token ok": () => true });
      return res.json("access_token");
    }
    if (attempt < 3) sleep(attempt);
  }
  fail(`Keycloak token failed after 3 attempts for ${username}`);
}

export function setup() {
  if (AUTH_MODE === "insecure-dev") return { tokens: {}, patientIds: {} };
  const tokens = {};
  for (const username of USERS) {
    tokens[username] = tokenFor(username);
  }

  const patientIds = {};
  for (const username of [...MEDICOS, ...ESTAGIARIOS]) {
    const res = http.get(`${BASE_URL}/api/patients`, {
      headers: {
        "Authorization": `Bearer ${tokens[username]}`,
        "x-username": username,
      },
    });
    const ok = check(res, {
      "caregiver patients loaded": (r) => r.status === 200 && Array.isArray(r.json("patientIds")),
    });
    patientIds[username] = ok ? res.json("patientIds") : [];
  }
  return { tokens, patientIds };
}

function patientFor(username, data) {
  const accessible = data.patientIds[username] || [];
  return accessible.length > 0 ? randomOf(accessible) : randomOf(PATIENT_IDS);
}

function authHeaders(username, role, data) {
  if (AUTH_MODE === "insecure-dev") {
    return { "x-username": username, "x-role": role };
  }
  return {
    "Authorization": `Bearer ${data.tokens[username]}`,
    "x-username": username,
  };
}

export default function (data) {
  const scenario = Math.random();

  if (scenario < 0.5) {
    // médico querying resumo clínico
    const username = randomOf(MEDICOS);
    const patientId = patientFor(username, data);
    const res = http.get(`${BASE_URL}/api/patients/${patientId}/resumo-clinico`, {
      headers: authHeaders(username, "medico", data),
    });
    summaryTrend.add(res.timings.duration);
    if (res.status === 403) denyCount.add(1);
    else if (res.status !== 200) {
      errorCount.add(1);
      unexpectedStatusCount.add(1, { endpoint: "resumo-medico", status: String(res.status) });
    }
    check(res, { "status is 200 or 403": (r) => r.status === 200 || r.status === 403 });
  } else if (scenario < 0.8) {
    // estagiário querying resumo clínico
    const username = randomOf(ESTAGIARIOS);
    const patientId = patientFor(username, data);
    const res = http.get(`${BASE_URL}/api/patients/${patientId}/resumo-clinico`, {
      headers: authHeaders(username, "estagiario", data),
    });
    summaryTrend.add(res.timings.duration);
    if (res.status === 403) denyCount.add(1);
    else if (res.status !== 200) {
      errorCount.add(1);
      unexpectedStatusCount.add(1, { endpoint: "resumo-estagiario", status: String(res.status) });
    }
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
    else if (res.status !== 200) {
      errorCount.add(1);
      unexpectedStatusCount.add(1, { endpoint: "estatisticas", status: String(res.status) });
    }
    check(res, { "status is 200 or 403": (r) => r.status === 200 || r.status === 403 });
  }

  sleep(Math.random() * 1.5 + 0.5);
}
