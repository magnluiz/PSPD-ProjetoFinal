"""
Authorization Service
----------------------
Decides ALLOW/DENY + access level (FULL/PARTIAL/ANONYMIZED/AGGREGATED) for a
given (username, role, query) combination, based on the relationship tables
in Postgres (user_patient_assignments, projects). It never touches clinical
data itself -- only relationship/authorization data.
"""
import logging
import os
from concurrent import futures

import grpc
import psycopg2
from psycopg2.extras import RealDictCursor
from prometheus_client import Counter, Histogram, start_http_server

import hospital_pb2
import hospital_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [authz] %(message)s")
log = logging.getLogger(__name__)

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "host=localhost port=5432 dbname=hospital user=hospital password=hospital",
)

REQUEST_COUNT = Counter(
    "authz_requests_total", "Total CheckAccess requests", ["role", "decision"]
)
REQUEST_LATENCY = Histogram(
    "authz_request_latency_seconds", "CheckAccess latency in seconds"
)


def get_conn():
    return psycopg2.connect(DB_DSN)


class AuthorizationServicer(hospital_pb2_grpc.AuthorizationServiceServicer):
    def CheckAccess(self, request, context):
        with REQUEST_LATENCY.time():
            role = request.role.lower()
            if role == "medico":
                decision = self._check_medico(request)
            elif role == "estagiario":
                decision = self._check_estagiario(request)
            elif role == "pesquisador":
                decision = self._check_pesquisador(request)
            else:
                decision = hospital_pb2.AccessResponse(
                    allow=False, access_level="", reason=f"unknown role '{request.role}'"
                )

            REQUEST_COUNT.labels(
                role=role or "unknown", decision="ALLOW" if decision.allow else "DENY"
            ).inc()
            return decision

    def _check_medico(self, request):
        """Médico só pode acessar pacientes vinculados a ele (assignment_type = ATTENDING)."""
        if not request.patient_id:
            return hospital_pb2.AccessResponse(allow=False, reason="patient_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1 FROM user_patient_assignments
                WHERE username = %s AND patient_id = %s
                  AND assignment_type = 'ATTENDING' AND active = true
                """,
                (request.username, request.patient_id),
            )
            if cur.fetchone():
                return hospital_pb2.AccessResponse(allow=True, access_level="FULL")
        return hospital_pb2.AccessResponse(
            allow=False, reason="paciente não vinculado a este médico"
        )

    def _check_estagiario(self, request):
        """Estagiário só pode acessar pacientes de uma atividade supervisionada ativa
        (assignment_type = TRAINEE, com supervisor_username preenchido)."""
        if not request.patient_id:
            return hospital_pb2.AccessResponse(allow=False, reason="patient_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1 FROM user_patient_assignments
                WHERE username = %s AND patient_id = %s
                  AND assignment_type = 'TRAINEE' AND active = true
                  AND supervisor_username IS NOT NULL
                """,
                (request.username, request.patient_id),
            )
            if cur.fetchone():
                return hospital_pb2.AccessResponse(allow=True, access_level="PARTIAL")
        return hospital_pb2.AccessResponse(
            allow=False, reason="paciente não vinculado a atividade supervisionada"
        )

    def _check_pesquisador(self, request):
        """Pesquisador só pode acessar coortes de projetos aprovados e vigentes
        (status = APPROVED em projects)."""
        if not request.project_id:
            return hospital_pb2.AccessResponse(allow=False, reason="project_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT status, valid_until FROM projects
                WHERE project_id = %s AND researcher_username = %s
                """,
                (request.project_id, request.username),
            )
            row = cur.fetchone()
            if not row:
                return hospital_pb2.AccessResponse(allow=False, reason="projeto não encontrado")
            if row["status"] != "APPROVED":
                return hospital_pb2.AccessResponse(
                    allow=False, reason=f"projeto com status '{row['status']}'"
                )
            import datetime

            if row["valid_until"] and row["valid_until"] < datetime.date.today():
                return hospital_pb2.AccessResponse(allow=False, reason="projeto expirado")

            level = (
                "AGGREGATED"
                if request.query_type in ("Estatisticas", "ResumoCoorte")
                else "ANONYMIZED"
            )
            return hospital_pb2.AccessResponse(allow=True, access_level=level)


def serve():
    port = os.environ.get("GRPC_PORT", "50051")
    metrics_port = int(os.environ.get("METRICS_PORT", "9100"))
    start_http_server(metrics_port)
    log.info(f"Prometheus metrics exposed on :{metrics_port}/metrics")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    hospital_pb2_grpc.add_AuthorizationServiceServicer_to_server(
        AuthorizationServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    log.info(f"AuthorizationService listening on :{port}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
