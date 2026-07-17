#!/bin/sh

# Get the latest ArgoCD Helm chart version
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1
helm repo update argo >/dev/null 2>&1
helm search repo argo/argo-cd --versions | head -n 2 | tail -n 1 | awk '{print $2}'