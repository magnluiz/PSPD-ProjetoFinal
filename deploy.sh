#!/bin/bash
# Builds all Docker images inside minikube's Docker daemon and applies the
# K8s manifests. Run this after `minikube start --nodes 4 ...` (1 master +
# 3 workers, per the assignment).
#
# Usage: ./deploy.sh

set -e

echo "=== Pointing Docker CLI at minikube's daemon ==="
eval $(minikube docker-env)

echo "=== Building images ==="
docker build -t hospital/authorization-service:latest ./services/authorization-service
docker build -t hospital/patient-data-service:latest ./services/patient-data-service
docker build -t hospital/data-transform-service:latest ./services/data-transform-service
docker build -t hospital/api-gateway:latest ./gateway
docker build -t hospital/frontend:latest ./frontend

echo "=== Generating seed data ==="
python3 db/seed.py --patients 500 --out db/seed.sql

echo "=== Applying namespace, secrets, and Keycloak realm/DB init ConfigMaps ==="
kubectl apply -f k8s/base/00-namespace.yaml
kubectl apply -f k8s/base/01-secrets.yaml
kubectl create configmap postgres-init-scripts \
  --from-file=db/schema.sql --from-file=db/seed.sql \
  -n hospital --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap keycloak-realm \
  --from-file=keycloak/hospital-realm.json \
  -n hospital --dry-run=client -o yaml | kubectl apply -f -

echo "=== Applying core services ==="
kubectl apply -f k8s/base/

echo "=== Applying monitoring stack ==="
kubectl apply -f k8s/monitoring/

echo "=== Waiting for rollout ==="
kubectl -n hospital rollout status deployment/postgres --timeout=120s
kubectl -n hospital rollout status deployment/keycloak --timeout=180s
kubectl -n hospital rollout status deployment/authorization-service --timeout=120s
kubectl -n hospital rollout status deployment/patient-data-service --timeout=120s
kubectl -n hospital rollout status deployment/data-transform-service --timeout=120s
kubectl -n hospital rollout status deployment/api-gateway --timeout=120s
kubectl -n hospital rollout status deployment/frontend --timeout=120s
kubectl -n hospital rollout status deployment/prometheus --timeout=120s
kubectl -n hospital rollout status deployment/grafana --timeout=120s

echo
echo "=== Done. Useful URLs (via minikube service): ==="
echo "  API Gateway: minikube service api-gateway -n hospital --url"
echo "  Frontend:    minikube service frontend -n hospital --url"
echo "  Prometheus:  minikube service prometheus -n hospital --url"
echo "  Grafana:     minikube service grafana -n hospital --url  (admin/admin)"
echo "  Keycloak:    kubectl -n hospital port-forward svc/keycloak 8081:8080"
