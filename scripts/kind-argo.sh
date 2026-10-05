#!/usr/bin/env bash
# kind + ArgoCD end-to-end (Phase 8 proof #1). Run from repo root.
# Needs: kind, kubectl, helm. ~10 min first run (image build + model bake).
set -euo pipefail

kind create cluster --config kind/cluster.yaml
kubectl create namespace opsmind --dry-run=client -o yaml | kubectl apply -f -

docker build -t opsmind-api:local .
kind load docker-image opsmind-api:local --name opsmind

helm upgrade --install opsmind helm/opsmind -n opsmind \
  --set image.repository=opsmind-api --set image.tag=local \
  --set ingress.enabled=false

# ArgoCD (GitOps proof): installs controller, points at this repo's chart.
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=available deploy/argocd-server -n argocd --timeout=300s
# Edit argocd/app.yaml repoURL to your fork first:
kubectl apply -f argocd/app.yaml
kubectl -n opsmind get pods
echo "port-forward: kubectl -n opsmind port-forward svc/opsmind-api 4000:4000"

# Helpers (were Makefile targets):
#   eval:        python -m app.evaluation.run
#   port-api:    kubectl -n opsmind port-forward svc/opsmind-api 4000:4000
#   eks-destroy: cd terraform/eks && terraform destroy   (EKS bills while the cluster exists)
