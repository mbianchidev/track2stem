.PHONY: help build up down logs clean test

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build all Docker images
	docker compose build

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Show logs from all services
	docker compose logs -f

clean: ## Remove all containers, volumes, and images
	docker compose down -v
	docker compose rm -f

restart: down up ## Restart all services

status: ## Show status of all services
	docker compose ps

backend-logs: ## Show backend logs
	docker compose logs -f backend

frontend-logs: ## Show frontend logs
	docker compose logs -f frontend

processor-logs: ## Show processor logs
	docker compose logs -f processor

shell-backend: ## Open shell in backend container
	docker compose exec backend sh

shell-processor: ## Open shell in processor container
	docker compose exec processor bash

dev: ## Start services in development mode (with logs)
	docker compose up --build
