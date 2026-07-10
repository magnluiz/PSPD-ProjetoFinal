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
import threading
import time
from concurrent import futures
from contextlib import contextmanager

import grpc
from psycopg2 import pool
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
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "20"))
AUTHZ_CACHE_TTL_SECONDS = float(os.environ.get("AUTHZ_CACHE_TTL_SECONDS", "30"))
DB_POOL = None
AUTHZ_CACHE = {}
AUTHZ_CACHE_LOCK = threading.Lock()

REQUEST_COUNT = Counter(
    "authz_requests_total", "Total CheckAccess requests", ["role", "decision"]
)
REQUEST_LATENCY = Histogram(
    "authz_request_latency_seconds", "CheckAccess latency in seconds"
)


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


class AuthorizationServicer(hospital_pb2_grpc.AuthorizationServiceServicer):
    def CheckAccess(self, request, context):
        with REQUEST_LATENCY.time():
            role = request.role.lower()
            cache_key = (
                request.username,
                role,
                request.patient_id,
                request.project_id,
                request.query_type,
            )
            decision = self._get_cached_decision(cache_key)
            if decision is None:
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
                self._cache_decision(cache_key, decision)

            REQUEST_COUNT.labels(
                role=role or "unknown", decision="ALLOW" if decision.allow else "DENY"
            ).inc()
            return decision

    def _get_cached_decision(self, cache_key):
        if AUTHZ_CACHE_TTL_SECONDS <= 0:
            return None
        now = time.monotonic()
        with AUTHZ_CACHE_LOCK:
            cached = AUTHZ_CACHE.get(cache_key)
            if not cached:
                return None
            expires_at, allow, access_level, reason = cached
            if expires_at <= now:
                AUTHZ_CACHE.pop(cache_key, None)
                return None
        return hospital_pb2.AccessResponse(
            allow=allow, access_level=access_level, reason=reason
        )

    def _cache_decision(self, cache_key, decision):
        if AUTHZ_CACHE_TTL_SECONDS <= 0:
            return
        value = (
            time.monotonic() + AUTHZ_CACHE_TTL_SECONDS,
            decision.allow,
            decision.access_level,
            decision.reason,
        )
        with AUTHZ_CACHE_LOCK:
            AUTHZ_CACHE[cache_key] = value

    def _check_medico(self, request):
        """Médico só pode acessar pacientes vinculados a ele."""
        if not request.patient_id:
            return hospital_pb2.AccessResponse(allow=False, reason="patient_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1 FROM user_patient_assignments
                WHERE username_cuidador = %s AND patient_id = %s
                  AND tipo_vinculo = 'medico' AND status = 'ativo'
                """,
                (request.username, request.patient_id),
            )
            if cur.fetchone():
                return hospital_pb2.AccessResponse(allow=True, access_level="FULL")
        return hospital_pb2.AccessResponse(
            allow=False, reason="paciente não vinculado a este médico"
        )

    def _check_estagiario(self, request):
        """Estagiário só pode acessar pacientes de uma atividade supervisionada ativa."""
        if not request.patient_id:
            return hospital_pb2.AccessResponse(allow=False, reason="patient_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1 FROM user_patient_assignments
                WHERE username_cuidador = %s AND patient_id = %s
                  AND tipo_vinculo = 'estagiario' AND status = 'ativo'
                  AND username_supervisor IS NOT NULL
                """,
                (request.username, request.patient_id),
            )
            if cur.fetchone():
                return hospital_pb2.AccessResponse(allow=True, access_level="PARTIAL")
        return hospital_pb2.AccessResponse(
            allow=False, reason="paciente não vinculado a atividade supervisionada"
        )

    def _check_pesquisador(self, request):
        """Pesquisador só pode acessar coortes de projetos aprovados e vigentes."""
        if not request.project_id:
            return hospital_pb2.AccessResponse(allow=False, reason="project_id required")
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT status, data_validade FROM projects
                WHERE projeto_id = %s AND username_pesquisador = %s
                """,
                (request.project_id, request.username),
            )
            row = cur.fetchone()
            if not row:
                return hospital_pb2.AccessResponse(allow=False, reason="projeto não encontrado")
            if row["status"] != "Aprovado":
                return hospital_pb2.AccessResponse(
                    allow=False, reason=f"projeto com status '{row['status']}'"
                )
            import datetime

            if row["data_validade"] and row["data_validade"] < datetime.date.today():
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
