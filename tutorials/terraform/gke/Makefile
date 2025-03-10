RED = $(shell tput -Txterm setab 1 && tput -Txterm setaf 0)
GREEN = $(shell tput -Txterm setab 2 && tput -Txterm setaf 0)
PURPLE = $(shell tput -Txterm setab 5 && tput -Txterm setaf 7)
RESET = $(shell tput -Txterm sgr0)
CLUSTER_NAME = production-stack
REGION = us-central1-a


all: create

create: create-gke-infra create-helm-chart

create-gke-infra:
	@echo ""
	@echo "$(GREEN) create gke infra $(RESET)"
	@cd gke-infrastructure && terraform init
	@cd gke-infrastructure && terraform apply -auto-approve

create-helm-chart:
	@echo ""
	@echo "$(GREEN) create helm chart $(RESET)"
	gcloud container clusters get-credentials $(CLUSTER_NAME) --region=$(REGION)
	@cd production-stack && terraform init
	@cd production-stack && terraform apply -auto-approve


destroy-gke-infra:
	@echo ""
	@echo "$(PURPLE) destroy gke infra $(RESET)"
	@cd gke-infrastructure && terraform init
	@cd gke-infrastructure && terraform destroy -auto-approve

destroy-helm-chart:
	@echo ""
	@echo "$(PURPLE) destroy helm chart $(RESET)"
	@cd production-stack && terraform init
	@cd production-stack && terraform destroy -auto-approve

clean: destroy-helm-chart

fclean: destroy-helm-chart destroy-gke-infra

.PHONY: all create init clean fclean
