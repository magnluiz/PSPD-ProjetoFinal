# Hospital Microservices - PSPD 2026/1

Aplicação hospitalar em microsserviços para o trabalho final de PSPD, implantada no cluster Kubernetes compartilhado do professor no namespace `grupo-6`.

O sistema expõe um pseudo-prontuário com autenticação via Keycloak, autorização por perfil, acesso a dados clínicos no PostgreSQL do grupo, transformação para HL7/FHIR, testes de carga com k6/Locust e observabilidade via Prometheus/Grafana/Rancher Monitoring.

## Arquitetura

```text
Frontend
  -> API Gateway (REST/JWT)
      -> Authorization Service (gRPC)
      -> Patient Data Service (gRPC -> PostgreSQL)
      -> Data Transform Service (gRPC -> FHIR)

Keycloak -> tokens OIDC
Prometheus/Grafana -> métricas e dashboards
```

Componentes:

- `frontend`: interface HTML servida por Nginx.
- `gateway`: API Gateway em Node.js/Express. Valida autenticação, chama os serviços gRPC e expõe `/metrics`.
- `services/authorization-service`: decide `ALLOW`/`DENY` e nível de acesso (`FULL`, `PARTIAL`, `ANONYMIZED`, `AGGREGATED`).
- `services/patient-data-service`: único serviço que acessa o PostgreSQL real do grupo.
- `services/data-transform-service`: anonimização, agregação e conversão para recursos FHIR.
- `db/schema.sql` e `db/seed.py`: schema e carga sintética alinhados ao schema real do banco do professor.
- `load-tests/k6` e `load-tests/locust`: testes de carga.
- `docs/relatorio.md`: relatório final com resultados e prints do Grafana.

## Estado atual do deploy

Ambiente final:

```text
Namespace: grupo-6
Frontend/API: https://kiriland.unb.br/grupo6
Keycloak: https://kiriland.unb.br/keycloak
Realm: grupo06
Client ID usado nos testes: admin-cli
```

Os manifests principais estão em `k8s/base/`.

Importante:

- Não aplique `k8s/monitoring/` no cluster compartilhado. O Prometheus/Grafana já existem via Rancher Monitoring.
- Não aplique manifests locais de PostgreSQL/Keycloak no cluster do professor. O projeto usa o banco e o Keycloak compartilhados.
- O arquivo `k8s/base/kubeconfig-grupo-6.yaml` é credencial local e está ignorado pelo Git.
- Os resultados brutos de k6 ficam em `load-tests/k6/results/` e também são ignorados pelo Git.

## Estrutura do repositório

```text
db/
  schema.sql
  seed.py
docs/
  relatorio.md
  images/
frontend/
gateway/
k8s/
  base/
  monitoring/        # apenas referência local; não aplicar no cluster compartilhado
load-tests/
  k6/
  locust/
services/
  authorization-service/
  patient-data-service/
  data-transform-service/
```

## Deploy no cluster do professor

Antes de aplicar, confirme as permissões:

```bash
kubectl auth can-i create deployments -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl auth can-i create ingresses -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
```

Aplicação recomendada dos manifests:

```bash
kubectl apply -f k8s/base/01-secrets.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/03-authorization-service.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/04-patient-data-service.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/05-data-transform-service.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/07-api-gateway.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/09-frontend.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/10-ingress.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl apply -f k8s/base/08-hpa.yaml --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
```

Verificação:

```bash
kubectl get pods -n grupo-6 -o wide --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl get ingress -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl get hpa -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
```

## Autenticação e usuários de teste

Nos testes de carga, o token é obtido pelo Keycloak:

```text
KEYCLOAK_URL=https://kiriland.unb.br/keycloak
KEYCLOAK_REALM=grupo06
CLIENT_ID=admin-cli
TEST_PASSWORD=PseudoPEP2026!
```

Usuários usados pelos scripts:

```text
Médicos:        med.cardoso, med.lima, med.almeida, med.rocha, med.monteiro
Estagiários:   est.ferreira, est.gomes, est.costa, est.melo, est.dias
Pesquisadores: pes.mendes, pes.araujo, pes.silveira
```

Observação: o cliente `admin-cli` gera tokens válidos, mas sem todos os claims da aplicação. Para os testes, o gateway aceita tokens válidos desse cliente e usa `X-Username` para identificar o usuário. Em produção, o correto é usar um client próprio da aplicação com claims completos.

## Validação funcional

Teste rápido da aplicação pública:

```bash
BASE_URL=https://kiriland.unb.br/grupo6 \
KEYCLOAK_URL=https://kiriland.unb.br/keycloak \
KEYCLOAK_REALM=grupo06 \
CLIENT_ID=admin-cli \
TEST_PASSWORD='PseudoPEP2026!' \
STAGE=10 \
DURATION=15s \
RAMP_UP=5s \
RAMP_DOWN=5s \
k6 run load-tests/k6/load-test.js
```

Fluxos validados:

- Médico vinculado: `ALLOW + FULL`
- Médico não vinculado: `DENY`
- Estagiário supervisionado: `ALLOW + PARTIAL`
- Pesquisador com projeto vigente: `ALLOW + AGGREGATED`
- Pesquisador sem acesso ao projeto: `DENY`

## Testes de carga

Script principal:

```bash
cd load-tests/k6
BASE_URL=https://kiriland.unb.br/grupo6 \
KEYCLOAK_URL=https://kiriland.unb.br/keycloak \
KEYCLOAK_REALM=grupo06 \
CLIENT_ID=admin-cli \
TEST_PASSWORD='PseudoPEP2026!' \
P95_THRESHOLD_MS=7000 \
./run-all.sh
```

Também é possível rodar um estágio isolado:

```bash
BASE_URL=https://kiriland.unb.br/grupo6 \
KEYCLOAK_URL=https://kiriland.unb.br/keycloak \
KEYCLOAK_REALM=grupo06 \
CLIENT_ID=admin-cli \
TEST_PASSWORD='PseudoPEP2026!' \
STAGE=1000 \
DURATION=60s \
RAMP_UP=15s \
RAMP_DOWN=10s \
P95_THRESHOLD_MS=10000 \
k6 run --summary-export load-tests/k6/results/final-1000vus.json load-tests/k6/load-test.js
```

Resultados finais medidos no cluster:

| Cenário | Throughput | Latência média | p95 | Erro |
|---|---:|---:|---:|---:|
| Baseline 1 réplica, 500 VUs | 20.39 req/s | 6431.33 ms | 9054.80 ms | 0.00% |
| Baseline 1 réplica, 1000 VUs | 22.68 req/s | 6058.99 ms | 12738.39 ms | 11.88% |
| HPA/cache, 500 VUs | 66.32 req/s | 1781.54 ms | 5786.48 ms | 0.00% |
| HPA/cache, 1000 VUs | 67.94 req/s | 1751.26 ms | 6135.46 ms | 1.05% |

## HPA

Configuração final em `k8s/base/08-hpa.yaml`:

| Serviço | Min réplicas | Max réplicas | CPU alvo |
|---|---:|---:|---:|
| API Gateway | 6 | 10 | 40% |
| Authorization Service | 6 | 10 | 40% |
| Patient Data Service | 6 | 10 | 40% |
| Data Transform Service | 3 | 10 | 40% |

Durante o teste de 1000 VUs, gateway, authorization e patient-data chegaram a 10 réplicas.

Comandos úteis:

```bash
kubectl get hpa -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl top pods -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl get pods -n grupo-6 -o wide --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
```

## Observabilidade

As métricas são expostas por:

- API Gateway: `/metrics` na porta 8080.
- Authorization Service: porta 9100.
- Patient Data Service: porta 9101.
- Data Transform Service: porta 9102.

No Grafana/Rancher Monitoring, filtre os dashboards pelo namespace:

```text
grupo-6
```

Dashboards usados no relatório:

- `Kubernetes / Compute Resources / Pod`
- `Kubernetes / Compute Resources / Workload`
- `Rancher / Workload`
- `Kubernetes / Networking / Namespace (Pods)`

Métricas relevantes:

- `gateway_http_requests_total`
- `gateway_http_request_duration_seconds`
- `gateway_authz_denials_total`
- `patientdata_requests_total`
- `patientdata_db_queries_total`
- `patientdata_request_latency_seconds`
- `transform_requests_total`
- métricas Kubernetes de CPU, memória, rede, HPA e réplicas

Para acessar métricas brutas por port-forward:

```bash
kubectl port-forward svc/api-gateway 8080:8080 -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl port-forward svc/authorization-service 9100:9100 -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl port-forward svc/patient-data-service 9101:9101 -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
kubectl port-forward svc/data-transform-service 9102:9102 -n grupo-6 --kubeconfig=k8s/base/kubeconfig-grupo-6.yaml
```

URLs locais:

```text
http://localhost:8080/metrics
http://localhost:9100/metrics
http://localhost:9101/metrics
http://localhost:9102/metrics
```

## Relatório

O relatório final está em:

```text
docs/relatorio.md
```

As imagens usadas no relatório estão em:

```text
docs/images/
```

## Desenvolvimento local

O projeto ainda mantém `docker-compose.yaml`, `deploy.sh` e `k8s/monitoring/` como apoio para execução local/minikube. Esse fluxo não foi o ambiente final de avaliação. Para o cluster do professor, use os manifests de `k8s/base/` conforme descrito acima e não suba uma stack própria de Prometheus/Grafana.

## Observações importantes

- O banco real do professor usa IDs textuais e enums em caixa alta; `db/schema.sql` e `db/seed.py` já refletem isso.
- As imagens configuradas nos manifests usam o padrão `coimbrasdan/hospital-*:g6`.
- Algumas correções foram aplicadas no cluster via ConfigMap override durante os testes, porque o push de imagem Docker pode depender da autenticação do mantenedor da conta Docker Hub.
- Antes de uma entrega definitiva operacional, publique novas imagens Docker com o código atual e reaplique os manifests.
