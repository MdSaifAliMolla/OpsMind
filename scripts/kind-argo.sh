#!/usr/bin/env bash
set -euo pipefail

kind create cluster --config kind/cluster.yaml
kubectl create namespace opsmind --dry-run=client -o yaml | kubectl apply -f -

docker build -t opsmind-api:local .
kind load docker-image opsmind-api:local --name opsmind

helm upgrade --install opsmind helm/opsmind -n opsmind \
  --set image.repository=opsmind-api --set image.tag=local \
  --set ingress.enabled=false

kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=available deploy/argocd-server -n argocd --timeout=300s
kubectl apply -f argocd/app.yaml
kubectl -n opsmind get pods
echo "port-forward: kubectl -n opsmind port-forward svc/opsmind-api 4000:4000"
