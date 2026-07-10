"""
Patient Data Service
---------------------
Only service that touches clinical tables (patients, encounters,
clinical_events). Does not make authorization decisions -- trusts the
Gateway already called AuthorizationService.CheckAccess.
"""
import logging
import os
import time
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
    return hospital_pb2.Encounter(
        encounter_id=r["encounter_id"],
        data_inicio=str(r["data_inicio"]),
        data_fim=str(r["data_fim"]) if r["data_fim"] else "",
        tipo_atendimento=r["tipo_atendimento"] or "",
        setor=r["setor"] or "",
    )


def _row_to_event(r):
    return hospital_pb2.ClinicalEvent(
        evento_id=r["evento_id"],
        patient_id=r["patient_id"],
        tipo_evento=r["tipo_evento"],
        codigo_evento=r["codigo_evento"],
        descricao=r["descricao"] or "",
        data_evento=str(r["data_evento"]),
        valor=float(r["valor"]) if r["valor"] is not None else 0.0,
        unidade=r["unidade"] or "",
    )


def _build_patient(cur, patient_id) -> hospital_pb2.RawPatientDataResponse:
    DB_QUERY_COUNT.inc()
    cur.execute("SELECT * FROM patients WHERE patient_id = %s", (patient_id,))
    p = cur.fetchone()
    if not p:
        return None

    DB_QUERY_COUNT.inc()
    cur.execute(
        "SELECT * FROM encounters WHERE patient_id = %s ORDER BY data_inicio DESC",
        (patient_id,),
    )
    encounters = [_row_to_encounter(r) for r in cur.fetchall()]

    DB_QUERY_COUNT.inc()
    cur.execute(
        "SELECT * FROM clinical_events WHERE patient_id = %s ORDER BY data_evento DESC",
        (patient_id,),
    )
    events = cur.fetchall()
    conditions = [_row_to_event(r) for r in events if r["tipo_evento"] == "Condicao"]
    observations = [_row_to_event(r) for r in events if r["tipo_evento"] == "Observacao"]
    medications = [_row_to_event(r) for r in events if r["tipo_evento"] == "Medicacao"]

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
            tipo = "medico" if request.role.lower() == "medico" else "estagiario"
            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT patient_id FROM user_patient_assignments
                    WHERE username_cuidador = %s AND tipo_vinculo = %s AND status = 'ativo'
                    """,
                    (request.username, tipo),
                )
                ids = [r["patient_id"] for r in cur.fetchall()]
            return hospital_pb2.PatientListResponse(patient_ids=ids)

    def GetPatientSummary(self, request, context):
        with REQUEST_LATENCY.labels("GetPatientSummary").time():
            REQUEST_COUNT.labels("GetPatientSummary").inc()
            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                patient = _build_patient(cur, request.patient_id)
            if patient is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "patient not found")
            return patient

    def GetPatientHistory(self, request, context):
        # Same underlying data as summary; frontend/gateway decides how to
        # render it (summary = latest snapshot, history = full timeline).
        with REQUEST_LATENCY.labels("GetPatientHistory").time():
            REQUEST_COUNT.labels("GetPatientHistory").inc()
            with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                patient = _build_patient(cur, request.patient_id)
            if patient is None:
                context.abort(grpc.StatusCode.NOT_FOUND, "patient not found")
            return patient

    def GetAggregatedStats(self, request, context):
        with REQUEST_LATENCY.labels("GetAggregatedStats").time():
            REQUEST_COUNT.labels("GetAggregatedStats").inc()
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
                    SELECT setor FROM encounters WHERE patient_id = ANY(%s)
                    """,
                    (patient_ids,),
                )
                depts = [r["setor"] for r in cur.fetchall() if r["setor"]]
                dept_dist = _distribution(depts)

                DB_QUERY_COUNT.inc()
                cur.execute(
                    """
                    SELECT codigo_evento, AVG(valor) AS media FROM clinical_events
                    WHERE patient_id = ANY(%s) AND tipo_evento = 'Observacao' AND valor IS NOT NULL
                    GROUP BY codigo_evento
                    """,
                    (patient_ids,),
                )
                avg_values = {r["codigo_evento"]: float(r["media"]) for r in cur.fetchall()}

            return hospital_pb2.AggregatedStatsResponse(
                total_patients=len(patient_ids),
                gender_distribution=gender_dist,
                age_distribution=age_dist,
                department_distribution=dept_dist,
                avg_values=avg_values,
            )

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
            JOIN projects p ON p.codigo_condicao = ce.codigo_evento
            WHERE p.projeto_id = %s AND ce.tipo_evento = 'Condicao'
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
