# Relatório — Monitoramento/Observabilidade de Aplicações em Clusters K8S

## Dados do curso

- **Curso:** Engenharia de Software — Faculdade UnB Gama
- **Disciplina/Turma:** PSPD — Programação para Sistemas Paralelos e Distribuídos, 2026/1
- **Professor:** Fernando W. Cruz
- **Data:** _[preencher]_
- **Alunos participantes:** _[nome completo — matrícula, ...]_

---

## 1. Introdução

_[Descrever brevemente o que foi solicitado (monitoramento/observabilidade de
uma aplicação de microsserviços em K8S) e dar uma visão geral do que este
relatório cobre: arquitetura da aplicação, montagem do cluster, e as cinco
fases da metodologia (validação funcional, testes de carga, escalabilidade
horizontal, autoscaling, observabilidade).]_

---

## 2. Metodologia de trabalho do grupo

_[Como o grupo se organizou: divisão de tarefas, ferramentas de comunicação,
roteiro de encontros. Sugestão de tabela:]_

| Encontro | Data | Pauta | Decisões / pendências |
|---|---|---|---|
| 1 | | Definição da arquitetura e divisão de papéis | |
| 2 | | Implementação dos microsserviços | |
| 3 | | Deploy no K8S + Prometheus/Grafana | |
| 4 | | Testes de carga e análise de resultados | |
| 5 | | Consolidação do relatório e vídeo | |

---

## 3. Experiência de montagem do Kubernetes em modo cluster

_[Detalhar: ferramenta usada (minikube --nodes 4), versão do K8S, comandos
executados, dificuldades encontradas (ex.: drivers, recursos de CPU/memória
disponíveis), como foi verificada a distribuição dos nós (`kubectl get
nodes`), e prints/capturas do cluster ativo.]_

```bash
minikube start --nodes 4 --cpus 2 --memory 4096 --driver=docker
minikube addons enable metrics-server
kubectl get nodes -o wide
```

_[Inserir aqui a saída do comando acima e comentar a topologia (1 master +
N workers).]_

---

## 4. Validação funcional

_[Relatar a execução da aplicação com 1 réplica de cada microsserviço e 1
instância do PostgreSQL. Descrever os testes realizados para os 4 níveis
de acesso (FULL/PARTIAL/ANONYMIZED/AGGREGATED) e para os fluxos de
autenticação (Keycloak). Incluir exemplos de requisição/resposta reais.]_

### 4.1 Cenários testados

| Perfil | Query | Resultado esperado | Resultado obtido |
|---|---|---|---|
| Médico, paciente vinculado | ResumoClinico | ALLOW + FULL | |
| Médico, paciente não vinculado | ResumoClinico | DENY | |
| Estagiário, paciente supervisionado | ResumoClinico | ALLOW + PARTIAL | |
| Pesquisador, projeto aprovado e vigente | Estatisticas | ALLOW + AGGREGATED | |
| Pesquisador, projeto expirado | Estatisticas | DENY | |

### 4.2 Síntese/conclusão da fase

_[Resumo: a aplicação funcionou conforme especificado? Que ajustes foram
necessários?]_

---

## 5. Testes de carga

_[Ferramenta usada: k6 e/ou Locust. Cenários: 10, 50, 100, 500 e 1000
usuários simultâneos. Para cada cenário, reportar pelo menos 4 métricas:
throughput, latência média, utilização de CPU, utilização de memória e
taxa de erro (5 aqui, conforme sugerido na especificação).]_

### 5.1 Resultados por cenário

| Usuários | Throughput (req/s) | Latência média (ms) | p95 (ms) | CPU (%) | Memória (MB) | Taxa de erro (%) |
|---|---|---|---|---|---|---|
| 10 | | | | | | |
| 50 | | | | | | |
| 100 | | | | | | |
| 500 | | | | | | |
| 1000 | | | | | | |

_[Inserir gráficos (Grafana ou k6/Locust) mostrando a evolução dessas
métricas por cenário.]_

### 5.2 Síntese/conclusão da fase

_[Onde ficou o gargalo? Qual serviço saturou primeiro? Isso já é sinal de
que a fase seguinte (escalabilidade horizontal) precisa atacar esse ponto.]_

---

## 6. Escalabilidade horizontal

_[Repetir (parte d) o teste de maior carga (ex.: 500 e 1000 usuários) após
escalar os módulos de 1 para 3 réplicas cada. Analisar:]_
- Ganho de desempenho (comparar throughput/latência antes e depois)
- Utilização dos nós do cluster (`kubectl top nodes`)
- Distribuição dos pods (`kubectl get pods -o wide`)
- Impacto no banco de dados (o Postgres continua sendo um único ponto —
  discutir se ele virou o novo gargalo)

| Réplicas | Usuários | Throughput (req/s) | Latência média (ms) | Observações |
|---|---|---|---|---|
| 1x | 500 | | | (baseline, copiado da Seção 5) |
| 3x | 500 | | | |
| 1x | 1000 | | | (baseline, copiado da Seção 5) |
| 3x | 1000 | | | |

### 6.1 Síntese/conclusão da fase

_[...]_

---

## 7. Autoscaling (HPA)

_[Configuração usada: min=1, max=10 réplicas, CPU alvo=60% (ajustar
conforme o que foi realmente testado). Demonstrar:]_
- (i) Criação automática de pods sob carga (`kubectl get hpa -w` +
  `kubectl get pods -w` durante o teste)
- (ii) Redistribuição da carga entre as novas réplicas
- (iii) Redução de latência após o scale-up
- (iv) Limites de escalabilidade observados (o que acontece ao atingir
  maxReplicas=10, ou quando o gargalo passa a ser o Postgres/nó do cluster)

```bash
kubectl -n hospital get hpa -w
kubectl -n hospital get pods -o wide -w
```

_[Inserir gráfico/tabela do número de réplicas ao longo do tempo durante
um teste de carga crescente.]_

### 7.1 Síntese/conclusão da fase

_[...]_

---

## 8. Observabilidade

_[Descrever a instalação do Prometheus (RBAC, service discovery via
anotações `prometheus.io/scrape`) e do Grafana. Listar as métricas
coletadas (mínimo 5, ver README para a lista completa) e anexar prints dos
dashboards construídos.]_

### 8.1 Métricas monitoradas

| Métrica | Fonte | O que mede |
|---|---|---|
| `gateway_http_requests_total` | API Gateway | Requisições por rota/status |
| `gateway_http_request_duration_seconds` | API Gateway | Latência HTTP |
| `authz_requests_total{role,decision}` | Authorization Service | Decisões ALLOW/DENY por papel |
| `patientdata_db_queries_total` | Patient Data Service | Volume de consultas SQL |
| `transform_requests_total{method,access_level}` | Data Transform Service | Uso por tipo de transformação |
| _(pods ativos, CPU/memória por pod)_ | metrics-server / HPA | Efeito do autoscaling |

### 8.2 Dashboards

_[Inserir prints dos painéis Grafana criados, com breve explicação do que
cada um mostra.]_

### 8.3 Síntese/conclusão da fase

_[...]_

---

## 9. Conclusão

_[Texto conclusivo sobre a experiência: principais dificuldades técnicas
(ex.: streaming gRPC, HPA não escalando como esperado, limites de recursos
do cluster local), soluções encontradas, e aprendizados gerais sobre
observabilidade em sistemas distribuídos.]_

### Comentários pessoais (um por integrante)

**[Nome do integrante 1]**
_[Partes que mais trabalhou, principais aprendizados, nota de autoavaliação.]_

**[Nome do integrante 2]**
_[...]_

_(repetir para cada integrante do grupo)_

---

## 10. Referências

[1] Arundel, J. and Domingus, J. *Cloud Native DevOps with Kubernetes –
Building, Deploying and Scaling Modern Applications in the Cloud*,
O'Reilly, 2019.

[2] HL7 FHIR. Disponível em: https://www.hl7.org/fhir/

[3] Kubernetes Documentation. Disponível em: https://kubernetes.io

[4] Prometheus Documentation. Disponível em: https://prometheus.io

_[Adicionar demais referências utilizadas.]_

---

## Anexos (opcional)

_[Arquivos de configuração completos, comentários adicionais sobre o
código, instruções de execução detalhadas — ou apenas referenciar o
GitHub/repositório entregue.]_
