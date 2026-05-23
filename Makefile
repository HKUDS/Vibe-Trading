.PHONY: help install dev dev-backend dev-frontend test test-backend test-frontend lint lint-backend lint-frontend format format-backend format-frontend fix fix-backend fix-frontend typecheck typecheck-backend clean docker-up docker-down

# ─── Help ───────────────────────────────────────────────────────────
help: ## Show this help
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Install ────────────────────────────────────────────────────────
install: ## Install all dependencies
	@echo "==> Installing backend dependencies..."
	cd backend && pip install -e ".[dev]"
	@echo "==> Installing frontend dependencies..."
	cd frontend && pnpm install

install-frontend: ## Install frontend dependencies only
	cd frontend && pnpm install

install-backend: ## Install backend dependencies only
	cd backend && pip install -e ".[dev]"

# ─── Development ────────────────────────────────────────────────────
dev: ## Start both frontend and backend (run in separate terminals)
	@echo "Run 'make dev-backend' and 'make dev-frontend' in separate terminals"

dev-backend: ## Start backend development server
	cd backend && uvicorn src.main:app --reload --port 8001 --host 0.0.0.0

dev-frontend: ## Start frontend development server
	cd frontend && pnpm dev

# ─── Testing ────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests
	cd backend && pytest -xvs

test-frontend: ## Run frontend tests
	cd frontend && pnpm test

test-coverage: ## Run all tests with coverage
	cd backend && pytest --cov=src --cov-report=html --cov-report=term
	cd frontend && pnpm test:coverage

# ─── Linting ────────────────────────────────────────────────────────
lint: lint-backend lint-frontend ## Lint all code

lint-backend: ## Lint Python code
	cd backend && ruff check src tests
	cd backend && mypy src

lint-frontend: ## Lint TypeScript code
	cd frontend && pnpm lint

# ─── Formatting ─────────────────────────────────────────────────────
format: format-backend format-frontend ## Format all code

format-backend: ## Format Python code
	cd backend && ruff format src tests

format-frontend: ## Format TypeScript code
	cd frontend && pnpm format

# ─── Auto-fix ───────────────────────────────────────────────────────
fix: fix-backend fix-frontend ## Auto-fix all code issues

fix-backend: ## Auto-fix Python code
	cd backend && ruff check --fix src tests

fix-frontend: ## Auto-fix TypeScript code
	cd frontend && pnpm lint:fix

# ─── Type Checking ──────────────────────────────────────────────────
typecheck: typecheck-backend typecheck-frontend ## Type-check all code

typecheck-backend: ## Type-check Python code
	cd backend && mypy src

typecheck-frontend: ## Type-check TypeScript code
	cd frontend && pnpm typecheck

# ─── Pre-commit ─────────────────────────────────────────────────────
pre-commit: ## Run all pre-commit hooks
	pre-commit run --all-files

# ─── Docker ─────────────────────────────────────────────────────────
docker-up: ## Start full stack with Docker Compose
	docker-compose up --build -d

docker-down: ## Stop Docker Compose stack
	docker-compose down

docker-logs: ## Show Docker Compose logs
	docker-compose logs -f

# ─── Cleaning ───────────────────────────────────────────────────────
clean: ## Clean build artifacts
	cd frontend && rm -rf dist node_modules coverage .vite
	cd backend && rm -rf __pycache__ .pytest_cache .mypy_cache htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
