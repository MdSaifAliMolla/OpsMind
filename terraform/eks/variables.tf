variable "region" {
  description = "AWS region for EKS"
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "opsmind"
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "ecr_url" {
  value = aws_ecr_repository.opsmind.repository_url
}

output "kubeconfig_cmd" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${var.cluster_name}"
}
