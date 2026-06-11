.PHONY: install-dev run test compile smoke

PYTHON ?= .venv/bin/python

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(PYTHON) -m plextui

test:
	$(PYTHON) -m pytest

compile:
	python3 -m compileall -f src tests

smoke:
	$(PYTHON) -m plextui.smoke
