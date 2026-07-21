.PHONY: sync lint typecheck test eval quality

sync:
	uv sync --all-extras --locked

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src scripts

test:
	uv run pytest tests/unit --cov=money_movement.domain --cov=money_movement.application --cov=money_movement.risk_review --cov-report=term-missing --cov-fail-under=90

eval:
	uv run python scripts/run_risk_review_evals.py

quality: lint typecheck test eval
