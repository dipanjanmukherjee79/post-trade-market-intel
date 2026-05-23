.PHONY: install test lint format run dashboard clean help

help:
	@echo "Targets:"
	@echo "  install     Install dependencies (incl. dev tools)"
	@echo "  test        Run pytest with coverage"
	@echo "  lint        Run ruff lint checks"
	@echo "  format      Auto-format with ruff"
	@echo "  run         Run the end-to-end pipeline"
	@echo "  dashboard   Start the Streamlit dashboard locally"
	@echo "  clean       Remove generated files and caches"

install:
	pip install -e ".[dev]" --break-system-packages

test:
	pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

run:
	python scripts/run_pipeline.py

dashboard:
	streamlit run dashboard/app.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ build/ dist/
