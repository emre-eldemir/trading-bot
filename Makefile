# =============================================================================
# Makefile — Trading Bot
# Common commands for development, testing, and deployment
# =============================================================================

.PHONY: help install test lint build run paper-trade backtest api clean

# Default target
help:
	@echo "Trading Bot — Available Commands"
	@echo "================================="
	@echo "  make install      Install Python dependencies"
	@echo "  make test         Run unit tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make build        Build Docker image"
	@echo "  make run          Run paper trading (Docker)"
	@echo "  make paper-trade  Run paper trading (local)"
	@echo "  make backtest     Run historical backtest"
	@echo "  make api          Start API dashboard server"
	@echo "  make clean        Remove build artifacts"

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v --tb=short

lint:
	ruff check app/ tests/

build:
	docker build -t trading-bot .

run:
	docker-compose up trading-bot

paper-trade:
	python -m app.main --paper

backtest:
	python -m app.main --backtest

api:
	python -m app.main --api

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf data/reports/*.json data/reports/*.csv data/reports/*.png 2>/dev/null || true
