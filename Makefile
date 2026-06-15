.PHONY: install-dev run test compile smoke build check-package check-release stage-release check clean

PYTHON ?= .venv/bin/python
BUMP ?= patch

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

build:
	$(PYTHON) -m build --no-isolation

check-package: build
	$(PYTHON) -m twine check dist/*

check-release:
	$(PYTHON) scripts/check_release.py

stage-release:
	$(PYTHON) scripts/stage_release.py --bump $(BUMP)

check: smoke test compile check-release check-package

clean:
	rm -rf build dist *.egg-info src/*.egg-info
