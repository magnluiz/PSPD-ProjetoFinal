# Hospital Microservices — Monitoramento/Observabilidade em K8S

Projeto PSPD 2026/1 — aplicação de microsserviços HL7/FHIR para um Hospital
Universitário, instanciada em cluster Kubernetes com observabilidade via
Prometheus + Grafana.

## Arquitetura

```
Frontend --HTTP/OIDC--> Keycloak
Frontend --HTTP/JWT--> API Gateway --gRPC/HTTP2--> Authorization Service
                                 --gRPC/HTTP2--> Patient Data Service --SQL--> PostgreSQL
                                 --gRPC/HTTP2--> Data Transform Service
```

- **API Gateway** (Node.js/Express): REST endpoints, valida JWT (Keycloak), roteia gRPC, consolida respostas.
- **Authorization Service** (Python/gRPC): decide ALLOW/DENY + nível de acesso (FULL/PARTIAL/ANONYMIZED/AGGREGATED).
- **Patient Data Service** (Python/gRPC): único serviço que acessa as tabelas clínicas no PostgreSQL.
- **Data Transform Service** (Python/gRPC): anonimização, agregação e conversão para HL7/FHIR.

Os 4 tipos de comunicação gRPC estão demonstrados:
- **Unary**: `CheckAccess`, `GetPatientSummary`, `ToFHIRPatient`, etc.
- **Server streaming**: `PatientDataService.StreamCohortData`
- **Client streaming**: `DataTransformService.CollectFHIRBundle`
- **Bidirectional streaming**: `DataTransformService.TransformPipeline`

## Estrutura do repositório

```
proto/                  hospital.proto (contrato gRPC compartilhado)
services/
  authorization-service/  (Python + grpcio)
  patient-data-service/   (Python + grpcio + psycopg2)
  data-transform-service/ (Python + grpcio)
gateway/                 API Gateway (Node.js/Express)
frontend/                Frontend HTML servido por Nginx, login OIDC/PKCE
db/
  schema.sql             DDL das 5 tabelas
  seed.py                gerador de dados sintéticos (Faker, seed fixo)
keycloak/
  hospital-realm.json    realm com roles medico/estagiario/pesquisador + usuários de teste
k8s/
  base/                  Deployments/Services/HPA de todos os componentes
  monitoring/            Prometheus (RBAC + scrape via anotações) + Grafana
load-tests/
  k6/load-test.js        cenário de carga (10/50/100/500/1000 VUs)
  locust/locustfile.py   equivalente em Locust
docker-compose.yaml       validação funcional local (sem K8s)
deploy.sh                 build + deploy completo no minikube
docs/relatorio.md         esqueleto do relatório (Seção 4 da especificação)
```

## 1. Validação funcional local (Docker Compose)

Réplica única de cada serviço + 1 instância do Postgres, conforme item 3.a
da especificação.

```bash
python3 db/seed.py --patients 500 --out db/seed.sql
docker compose up --build
```

Isso sobe: postgres, keycloak (com realm importado), os 3 microsserviços,
o gateway, frontend, prometheus e grafana. Endpoints:
- Gateway: http://localhost:8080
- Frontend: http://localhost:8082
- Keycloak: http://localhost:8081 (admin/admin)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

Obtendo um token JWT real do Keycloak (usuário `med.cardoso`, senha `senha123`):

```bash
curl -X POST http://localhost:8081/realms/hospital/protocol/openid-connect/token \
  -d "client_id=hospital-frontend" -d "grant_type=password" \
  -d "username=med.cardoso" -d "password=senha123" | jq -r .access_token
```

Ou, para testes rápidos sem Keycloak, rode o gateway com
`AUTH_MODE=insecure-dev` e envie os headers `x-username` / `x-role`
diretamente (já usado pelos scripts de carga).

### Testando os 4 níveis de acesso

Pelo frontend, acesse http://localhost:8082, clique em "Login Keycloak" e
use um dos usuários do realm (`med.cardoso`, `est.silva`, `pesq.dias`, todos
com senha `senha123`). O frontend usa Authorization Code + PKCE e envia o JWT
ao gateway como Bearer token.

```bash
# FULL (médico, paciente vinculado)
curl -H "x-username: med.cardoso" -H "x-role: medico" \
  http://localhost:8080/api/patients/P000001/resumo-clinico

# PARTIAL (estagiário)
curl -H "x-username: est.silva" -H "x-role: estagiario" \
  http://localhost:8080/api/patients/P000004/resumo-clinico

# AGGREGATED (pesquisador, projeto aprovado e vigente)
curl -H "x-username: pesq.dias" -H "x-role: pesquisador" \
  http://localhost:8080/api/coorte/1/estatisticas

# ANONYMIZED (pesquisador, coorte via streaming)
curl -H "x-username: pesq.dias" -H "x-role: pesquisador" \
  http://localhost:8080/api/coorte/1/exames
```

## 2. Cluster Kubernetes (minikube, 1 master + 3+ workers)

```bash
minikube start --nodes 4 --cpus 2 --memory 4096 --driver=docker
minikube addons enable metrics-server   # necessário para o HPA
./deploy.sh
```

O script `deploy.sh` builda as imagens dentro do Docker do minikube, cria
os ConfigMaps de init do banco/Keycloak, e aplica `k8s/base/` + `k8s/monitoring/`.

Acessando os serviços:
```bash
minikube service api-gateway -n hospital --url
minikube service prometheus -n hospital --url
minikube service grafana -n hospital --url
kubectl -n hospital port-forward svc/keycloak 8081:8080
```

Verificando distribuição dos pods entre os workers:
```bash
kubectl -n hospital get pods -o wide
```

## 3. Escalabilidade horizontal (item 3.c)

```bash
kubectl -n hospital scale deployment api-gateway --replicas=3
kubectl -n hospital scale deployment authorization-service --replicas=3
kubectl -n hospital scale deployment patient-data-service --replicas=3
kubectl -n hospital scale deployment data-transform-service --replicas=3
kubectl -n hospital get pods -o wide -w
```

## 4. Autoscaling / HPA (item 3.d)

Os manifests em `k8s/base/08-hpa.yaml` já configuram HPA (min=1, max=10,
CPU alvo 60%) para os 4 serviços de aplicação. Para observar o autoscaling
em ação, gere carga (Seção 5) e acompanhe:

```bash
kubectl -n hospital get hpa -w
```

## 5. Testes de carga (item 3.b)

Cenários obrigatórios: 10, 50, 100, 500, 1000 usuários simultâneos.

**k6:**
```bash
cd load-tests/k6
BASE_URL=$(minikube service api-gateway -n hospital --url) \
KEYCLOAK_URL=http://localhost:8081 \
./run-all.sh
```

Em outro terminal, deixe o Keycloak acessível para o k6:
```bash
kubectl -n hospital port-forward svc/keycloak 8081:8080
```

**Locust (alternativa/complementar):**
```bash
cd load-tests/locust
locust -f locustfile.py --host $(minikube service api-gateway -n hospital --url) \
  --users 100 --spawn-rate 20 --run-time 60s --headless --csv results/locust-100users
```

> Nota de auth para testes de carga: o k6 usa tokens reais do Keycloak por
> padrão. Para isolar a medição de desempenho dos microsserviços do custo de
> validação JWT, rode o gateway com `AUTH_MODE=insecure-dev` e execute o k6
> com `AUTH_MODE=insecure-dev`.

## 6. Observabilidade (item 3.e)

Todos os 4 serviços expõem métricas Prometheus (`/metrics` no gateway,
`:910x/metrics` nos microsserviços gRPC), descobertas automaticamente
pelas anotações `prometheus.io/scrape` nos Deployments.

Métricas expostas (mínimo de 5 exigido pela especificação):
1. `gateway_http_requests_total` — requisições por rota/status
2. `gateway_http_request_duration_seconds` — latência HTTP no gateway
3. `authz_requests_total{role,decision}` — decisões ALLOW/DENY por papel
4. `patientdata_db_queries_total` — número de consultas SQL executadas
5. `transform_requests_total{method,access_level}` — uso por tipo de transformação
6. `gateway_authz_denials_total` / `gateway_grpc_errors_total` — erros
7. Métricas padrão de processo (CPU, memória) via `prom-client`/`prometheus_client`
8. `kube_pod_*` (via metrics-server/HPA) — quantidade de pods, uso de CPU/memória por pod

Dashboards Grafana: crie painéis apontando para o datasource "Prometheus"
(já provisionado). Sugestão de painéis: requests/s por rota, p95 de
latência, taxa de erro, decisões de autorização por papel, réplicas ativas
por Deployment (via `kube_deployment_status_replicas`, se o
kube-state-metrics for adicionado).

## Requisitos e testes já validados neste projeto

Durante o desenvolvimento, todo o pipeline foi validado localmente com
PostgreSQL real:
- Schema + 300 pacientes sintéticos carregados sem erros
- Os 3 gRPC services rodando e conectados ao banco
- Gateway roteando corretamente FULL / PARTIAL / ANONYMIZED / AGGREGATED
- Fluxo de streaming (server-streaming → bidi-streaming) testado com uma
  coorte real de 108 pacientes
- Teste de carga real (Locust, 15 usuários) rodou 127 requisições com 0% de falhas

Falta rodar em cluster K8s real (minikube) e coletar as métricas de
desempenho para os 5 cenários de carga exigidos — isso depende de acesso a
Docker/minikube, que não está disponível no ambiente de desenvolvimento
usado para construir este projeto.
