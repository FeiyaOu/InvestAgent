# 项目自带虚拟环境（.venv 在本项目根目录下，不是上级目录）
# 需要用其他解释器时可覆盖：make test PYTHON=python3
PYTHON ?= .venv/bin/python
STREAMLIT ?= $(PYTHON) -m streamlit

.PHONY: install install-dev test test-reporter test-agent test-integration lint run

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest

test-reporter:
	$(PYTHON) -m pytest tests/test_reporter.py -v

test-agent:
	$(PYTHON) -m pytest tests/test_agent.py -v

test-integration:
	$(PYTHON) -m pytest tests/ -m integration -v

lint:
	$(PYTHON) -m ruff check src/ tests/
	$(PYTHON) linters/check_agent_structure.py

run:
	$(STREAMLIT) run app/streamlit_app.py
