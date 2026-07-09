"""
Locust load test for the hospital microservices API.

Usage:
    locust -f locustfile.py --host http://<gateway-host>:30080

Then open http://localhost:8089 and set the user count to 10/50/100/500/1000
per the assignment's required scenarios, or run headless:

    locust -f locustfile.py --host http://<gateway-host>:30080 \
        --users 100 --spawn-rate 20 --run-time 60s --headless \
        --csv results/locust-100users
"""
import random

from locust import HttpUser, task, between

MEDICOS = ["med.cardoso", "med.souza", "med.lima", "med.alves", "med.rocha"]
ESTAGIARIOS = ["est.silva", "est.pereira", "est.costa", "est.santos", "est.oliveira"]
PESQUISADORES = ["pesq.franca", "pesq.dias", "pesq.moura"]
PATIENT_IDS = [f"P{i:06d}" for i in range(1, 301)]
PROJECT_IDS = ["1", "2", "3", "4", "5", "6"]


class MedicoUser(HttpUser):
    weight = 5
    wait_time = between(0.5, 2)

    @task
    def resumo_clinico(self):
        username = random.choice(MEDICOS)
        patient_id = random.choice(PATIENT_IDS)
        with self.client.get(
            f"/api/patients/{patient_id}/resumo-clinico",
            headers={"x-username": username, "x-role": "medico"},
            name="/api/patients/[id]/resumo-clinico (medico)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


class EstagiarioUser(HttpUser):
    weight = 3
    wait_time = between(0.5, 2)

    @task
    def resumo_clinico(self):
        username = random.choice(ESTAGIARIOS)
        patient_id = random.choice(PATIENT_IDS)
        with self.client.get(
            f"/api/patients/{patient_id}/resumo-clinico",
            headers={"x-username": username, "x-role": "estagiario"},
            name="/api/patients/[id]/resumo-clinico (estagiario)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


class PesquisadorUser(HttpUser):
    weight = 2
    wait_time = between(1, 3)

    @task(2)
    def estatisticas(self):
        username = random.choice(PESQUISADORES)
        project_id = random.choice(PROJECT_IDS)
        with self.client.get(
            f"/api/coorte/{project_id}/estatisticas",
            headers={"x-username": username, "x-role": "pesquisador"},
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
            headers={"x-username": username, "x-role": "pesquisador"},
            name="/api/coorte/[id]/exames (streamed)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")
