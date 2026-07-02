.PHONY: test lint fmt integration

test:
	python -m pytest tests/unit -q

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check --fix .
	ruff format .

integration:
	tests/integration/run.sh
