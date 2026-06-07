PHONY := help install run start test lint

.PHONY: $(PHONY)

help:
	@echo "Usage: make install | make run | make start | make test | make lint"

# Install the package + dev extras into the local .venv
install:
	@bash -lc '.venv/bin/python -m pip install -e ".[dev]"'

# Run the LiveKit worker in dev mode (auto-reload + verbose logs)
run:
	@bash -lc '.venv/bin/python -m wispoke_voice.worker dev'

# Run the worker in production mode
start:
	@bash -lc '.venv/bin/python -m wispoke_voice.worker start'

# Run test suite
test:
	@bash -lc '.venv/bin/python -m pytest tests/ -v'

# Lint with ruff
lint:
	@bash -lc '.venv/bin/ruff check src tests'
