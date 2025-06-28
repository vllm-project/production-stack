RED = $(shell tput -Txterm setab 1 && tput -Txterm setaf 0)
GREEN = $(shell tput -Txterm setab 2 && tput -Txterm setaf 0)
PURPLE = $(shell tput -Txterm setab 5 && tput -Txterm setaf 7)
RESET = $(shell tput -Txterm sgr0)


all: create

create: create-azure-infra create-helm-chart

create-azure-infra:
	@echo ""
	@echo "$(GREEN) create azure infra $(RESET)"
	@cd azure-infrastructure && terraform init
	@cd azure-infrastructure && terraform apply -auto-approve

create-helm-chart:
	@echo ""
	@echo "$(GREEN) create helm chart $(RESET)"
	@cd production-stack && terraform init
	@cd production-stack && terraform apply -auto-approve


destroy-azure-infra:
	@echo ""
	@echo "$(PURPLE) destroy azure infra $(RESET)"
	@cd azure-infrastructure && terraform init
	@cd azure-infrastructure && terraform destroy -auto-approve

destroy-helm-chart:
	@echo ""
	@echo "$(PURPLE) destroy helm chart $(RESET)"
	@cd production-stack && terraform init
	@cd production-stack && terraform destroy -auto-approve

clean: destroy-helm-chart

fclean: destroy-helm-chart destroy-azure-infra

.PHONY: all create init clean fclean
