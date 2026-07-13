"""
Patient Data Service
---------------------
Only service that touches clinical tables (patients, encounters,
clinical_events). Does not make authorization decisions -- trusts the
Gateway already called AuthorizationService.CheckAccess.
"""
import logging
import os
import re
import time
from threading import Lock
from concurrent import futures
from contextlib import contextmanager

import grpc
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from prometheus_client import Counter, Histogram, start_http_server

import hospital_pb2
import hospital_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [patient-data] %(message)s")
log = logging.getLogger(__name__)

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "host=localhost port=5432 dbname=hospital user=hospital password=hospital",
)
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "30"))
DB_POOL = None
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "60"))
CACHE_LOCK = Lock()
CACHE = {
    "caregiver_patients": {},
    "patient_summary": {},
    "aggregated_stats": {},
}

REQUEST_COUNT = Counter(
    "patientdata_requests_total", "Total requests handled", ["method"]
)
REQUEST_LATENCY = Histogram(
    "patientdata_request_latency_seconds", "Request latency in seconds", ["method"]
)
DB_QUERY_COUNT = Counter("patientdata_db_queries_total", "Total SQL queries executed")


def _get_pool():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = pool.ThreadedConnectionPool(DB_POOL_MIN, DB_POOL_MAX, DB_DSN)
    return DB_POOL


def _cache_get(namespace, key):
    if CACHE_TTL_SECONDS <= 0:
        return None
    now = time.time()
    with CACHE_LOCK:
        item = CACHE[namespace].get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            CACHE[namespace].pop(key, None)
            return None
        return value


def _cache_set(namespace, key, value):
    if CACHE_TTL_SECONDS <= 0:
        return value
    with CACHE_LOCK:
        CACHE[namespace][key] = (time.time() + CACHE_TTL_SECONDS, value)
    return value


@contextmanager
def get_conn():
    conn = _get_pool().getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        _get_pool().putconn(conn)


def _row_to_encounter(r):
    # Proto field names (data_inicio, tipo_atendimento, setor, ...) are kept
    # as-is -- they are the internal gRPC contract, not DB column names.
    return hospital_pb2.Encounter(
        encounter_id=_numeric_id(r["encounter_id"]),
        data_inicio=str(r["start_date"]),
        data_fim=str(r["end_date"]) if r["end_date"] else "",
        tipo_atendimento=r["encounter_type"] or "",
        setor=r["department"] or "",
    )


def _row_to_event(r):
    return hospital_pb2.ClinicalEvent(
        evento_id=_numeric_id(r["event_id"]),
        patient_id=r["patient_id"],
        tipo_evento=r["event_type"],
        codigo_evento=r["code"],
        descricao=r["description"] or "",
        data_evento=str(r["event_date"]),
        valor=float(r["value"]) if r["value"] is not None else 0.0,
        unidade=r["unit"] or "",
    )


def _numeric_id(value):
    """Adapt textual IDs from the shared DB to the legacy int32 gRPC fields."""
    digits = re.sub(r"\D", "", str(value))
    return int(digits[-9:]) if digits else 0


def _build_patient(cur, patient_id) -> hospital_pb2.RawPatientDataResponse:
    DB_QUERY_COUNT.inc()
    cur.execute("SELECT * FROM patients WHERE patient_id = %s", (patient_id,))
    p = cur.fetchone()
    if not p:
        return None

    DB_QUERY_COUNT.inc()
    cur.execute(
        "SELECT * FROM encounters WHERE patient_id = %s ORDER BY start_date DESC",
        (patient_id,),
    )
    encounters = [_row_to_encounter(r) for r in cur.fetchall()]

    DB_QUERY_COUNT.inc()
    cur.execute(
        "SELECT * FROM clinical_events WHERE patient_id = %s ORDER BY event_date DESC",
        (patient_id,),
    )
    events = cur.fetchall()
    conditions = [_row_to_event(r) for r in events if r["event_type"] == "CONDITION"]
    observations = [_row_to_event(r) for r in events if r["event_type"] == "OBSERVATION"]
    medications = [_row_to_event(r) for r in events if r["event_type"] == "MEDICATION"]

    return hospital_pb2.RawPatientDataResponse(
        patient_id=p["patient_id"],
        full_name=p["full_name"],
        birth_date=str(p["birth_date"]),
        gender=p["gender"],
        city=p["city"] or "",
        state=p["state"] or "",
        cpf=p["cpf"] or "",
        cns=p["cns"] or "",
        encounters=encounters,
        conditions=conditions,
        observations=observations,
        medications=medications,
    )


class PatientDataServicer(hospital_pb2_grpc.PatientDataServiceServicer):
    def GetPatientsByCaregiver(self, request, context):
        with REQUEST_LATENCY.labels("GetPatientsByCaregiver").time():
            REQUEST_COUNT.labels("GetPatientsByCaregiver").inc()
            tipo = "ATTENDING" if request.role.lower() == "medico" else "TRAINEE"
            cache_key = (request.username, tipo)
            cached = _cache_get("caregiver_patients", cache_key)
            if cached is not None:
                return hospital_pb2.PatientListResponse(patient_ids=cached)

            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT patient_id FROM user_patient_assignments
                    WHERE username = %s AND assignment_type = %s AND active = true
                    """,
                    (request.username, tipo),
                )
                ids = [r["patient_id"] for r in cur.fetchall()]
            _cache_set("caregiver_patients", cache_key, ids)
            return hospital_pb2.PatientListResponse(patient_ids=ids)

    def GetPatientSummary(self, request, context):
        with REQUEST_LATENCY.labels("GetPatientSummary").time():
            REQUEST_COUNT.labels("GetPatientSummary").inc()
            cached = _cache_get("patient_summary", request.patient_id)
            if cached is not None:
                return cached

            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                patient = _build_patient(cur, request.patient_id)
            if patient is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "patient not found")
            return _cache_set("patient_summary", request.patient_id, patient)

    def GetPatientHistory(self, request, context):
        # Same underlying data as summary; frontend/gateway decides how to
        # render it (summary = latest snapshot, history = full timeline).
        with REQUEST_LATENCY.labels("GetPatientHistory").time():
            REQUEST_COUNT.labels("GetPatientHistory").inc()
            cached = _cache_get("patient_summary", request.patient_id)
            if cached is not None:
                return cached

            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                patient = _build_patient(cur, request.patient_id)
            if patient is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "patient not found")
            return _cache_set("patient_summary", request.patient_id, patient)

    def GetAggregatedStats(self, request, context):
        with REQUEST_LATENCY.labels("GetAggregatedStats").time():
            REQUEST_COUNT.labels("GetAggregatedStats").inc()
            cached = _cache_get("aggregated_stats", request.project_id)
            if cached is not None:
                return cached

            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                patient_ids = self._cohort_patient_ids(cur, request)

                if not patient_ids:
                    return hospital_pb2.AggregatedStatsResponse(total_patients=0)

                DB_QUERY_COUNT.inc()
                cur.execute(
                    "SELECT gender FROM patients WHERE patient_id = ANY(%s)", (patient_ids,)
                )
                genders = [r["gender"] for r in cur.fetchall()]
                gender_dist = _distribution(genders)

                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT date_part('year', age(birth_date)) AS age FROM patients
                    WHERE patient_id = ANY(%s)
                    """,
                    (patient_ids,),
                )
                ages = [_age_bracket(int(r["age"])) for r in cur.fetchall()]
                age_dist = _distribution(ages)

                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT department FROM encounters WHERE patient_id = ANY(%s)
                    """,
                    (patient_ids,),
                )
                depts = [r["department"] for r in cur.fetchall() if r["department"]]
                dept_dist = _distribution(depts)

                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT code, AVG(value::numeric) AS media FROM clinical_events
                    WHERE patient_id = ANY(%s) AND event_type = 'OBSERVATION'
                      AND value ~ '^[+-]?[0-9]+([.][0-9]+)?$'
                    GROUP BY code
                    """,
                    (patient_ids,),
                )
                avg_values = {r["code"]: float(r["media"]) for r in cur.fetchall()}

            response = hospital_pb2.AggregatedStatsResponse(
                total_patients=len(patient_ids),
                gender_distribution=gender_dist,
                age_distribution=age_dist,
                department_distribution=dept_dist,
                avg_values=avg_values,
            )
            return _cache_set("aggregated_stats", request.project_id, response)

    def StreamCohortData(self, request, context):
        """Server-streaming RPC: yields one patient at a time instead of
        building the whole cohort list in memory first."""
        REQUEST_COUNT.labels("StreamCohortData").inc()
        start = time.time()
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            patient_ids = self._cohort_patient_ids(cur, request)
            for pid in patient_ids:
                with get_conn() as conn2, conn2.cursor(cursor_factory=RealDictCursor) as cur2:
                    patient = _build_patient(cur2, pid)
                if patient is not None:
                    yield patient
        REQUEST_LATENCY.labels("StreamCohortData").observe(time.time() - start)

    def _cohort_patient_ids(self, cur, request):
        DB_QUERY_COUNT.inc()
        cur.execute(
            """
            SELECT DISTINCT ce.patient_id
            FROM clinical_events ce
            JOIN projects p ON p.target_condition_code = ce.code
            WHERE p.project_id = %s AND ce.event_type = 'CONDITION'
            """,
            (request.project_id,),
        )
        return [r["patient_id"] for r in cur.fetchall()]


def _distribution(values):
    if not values:
        return {}
    total = len(values)
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return {k: round(v / total, 4) for k, v in counts.items()}


def _age_bracket(age):
    if age < 18:
        return "0-17"
    if age < 40:
        return "18-39"
    if age < 60:
        return "40-59"
    return "60+"


def serve():
    port = os.environ.get("GRPC_PORT", "50052")
    metrics_port = int(os.environ.get("METRICS_PORT", "9101"))
    start_http_server(metrics_port)
    log.info(f"Prometheus metrics exposed on :{metrics_port}/metrics")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    hospital_pb2_grpc.add_PatientDataServiceServicer_to_server(
        PatientDataServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    log.info(f"PatientDataService listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
