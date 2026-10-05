# OpsMind — one-command environments (kind-local free, EKS for resume wow).
kind-up:
	kind create cluster --config kind/cluster.yaml
	kubectl create ns opsmind || true

helm-local:
	helm upgrade --install opsmind helm/opsmind -n opsmind \
	  --set image.repository=opsmind-api --set image.tag=local \
	  --set ingress.enabled=false --set postgresql.enabled=true --set qdrant.enabled=true
	kubectl -n opsmind get pods

docker-local:
	docker build -t opsmind-api:local .
	kind load docker-image opsmind-api:local --name opsmind

eval-gated:
	python -m app.evaluation.run

port-api:
	kubectl -n opsmind port-forward svc/opsmind-api 4000:4000

# EKS (costs ~$70-90/mo — destroy after demo):
#   cd terraform/eks && terraform init && terraform apply
#   aws eks update-kubeconfig --region us-east-1 --name opsmind
#   helm upgrade --install opsmind helm/opsmind -n opsmind --set image.repository=<ECR_URL> --set ingress.enabled=true --set ingress.host=opsmind.YOU.com
eks-destroy:
	cd terraform/eks && terraform destroy
