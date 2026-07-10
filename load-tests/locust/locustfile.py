"""
Locust load test for the hospital microservices API.

Usage:
    locust -f locustfile.py --host http://<gateway-host>:30080

Then open http://localhost:8089 and set the user count to 10/50/100/500/1000
per the assignment's required scenarios, or run headless:

    locust -f locustfile.py --host http://<gateway-host>:30080 \
        --users 100 --spawn-rate 20 --run-time 60s --headless \
        --csv results/locust-100users

By default this obtains real Keycloak tokens. Set KEYCLOAK_URL when Keycloak
is not at http://localhost:8081, or AUTH_MODE=insecure-dev when the gateway
is explicitly running in header-auth development mode.
"""
import json
import os
import random
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from locust import HttpUser, between, task

MEDICOS = ["med.cardoso", "med.souza", "med.lima", "med.alves", "med.rocha"]
ESTAGIARIOS = ["est.silva", "est.pereira",
               "est.costa", "est.santos", "est.oliveira"]
PESQUISADORES = ["pesq.franca", "pesq.dias", "pesq.moura"]
PATIENT_IDS = [f"P{i:06d}" for i in range(1, 301)]
PROJECT_IDS = ["1", "2", "3", "4", "5", "6"]
AUTH_MODE = os.environ.get("AUTH_MODE", "keycloak")
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
PASSWORD = os.environ.get("TEST_PASSWORD", "senha123")


def role_for(username):
    if username.startswith("med."):
        return "medico"
    if username.startswith("est."):
        return "estagiario"
    return "pesquisador"


def token_for(username):
    data = urlencode(
        {
            "client_id": "hospital-frontend",
            "grant_type": "password",
            "username": username,
            "password": PASSWORD,
        }
    ).encode()
    request = Request(
        f"{KEYCLOAK_URL}/realms/hospital/protocol/openid-connect/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())["access_token"]


class AuthenticatedUser(HttpUser):
    abstract = True
    tokens: dict[str, str]

    def on_start(self):
        self.tokens = {}

    def auth_headers(self, username):
        if AUTH_MODE == "insecure-dev":
            return {"x-username": username, "x-role": role_for(username)}
        if username not in self.tokens:
            self.tokens[username] = token_for(username)
        return {"Authorization": f"Bearer {self.tokens[username]}"}


class MedicoUser(AuthenticatedUser):
    weight = 5
    wait_time = between(0.5, 2)

    @task
    def resumo_clinico(self):
        username = random.choice(MEDICOS)
        patient_id = random.choice(PATIENT_IDS)
        with self.client.get(
            f"/api/patients/{patient_id}/resumo-clinico",
            headers=self.auth_headers(username),
            name="/api/patients/[id]/resumo-clinico (medico)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


class EstagiarioUser(AuthenticatedUser):
    weight = 3
    wait_time = between(0.5, 2)

    @task
    def resumo_clinico(self):
        username = random.choice(ESTAGIARIOS)
        patient_id = random.choice(PATIENT_IDS)
        with self.client.get(
            f"/api/patients/{patient_id}/resumo-clinico",
            headers=self.auth_headers(username),
            name="/api/patients/[id]/resumo-clinico (estagiario)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


class PesquisadorUser(AuthenticatedUser):
    weight = 2
    wait_time = between(1, 3)

    @task(2)
    def estatisticas(self):
        username = random.choice(PESQUISADORES)
        project_id = random.choice(PROJECT_IDS)
        with self.client.get(
            f"/api/coorte/{project_id}/estatisticas",
            headers=self.auth_headers(username),
            name="/api/coorte/[id]/estatisticas",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(1)
    def exames_coorte(self):
        """Exercises the server-streaming + bidi-streaming transform
        pipeline -- typically the heaviest endpoint, worth watching under
        load separately from the others."""
        username = random.choice(PESQUISADORES)
        project_id = random.choice(PROJECT_IDS)
        with self.client.get(
            f"/api/coorte/{project_id}/exames",
            headers=self.auth_headers(username),
            name="/api/coorte/[id]/exames (streamed)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")
