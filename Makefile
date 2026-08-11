# ssq_predictor — developer commands (run from this directory)
PYTHON ?= python3

.PHONY: help update predict check serve test data-only eval

help:
	@echo "Targets:"
	@echo "  make update      # crawl + full reinit + predict"
	@echo "  make data-only   # crawl/merge only"
	@echo "  make predict     # predict only"
	@echo "  make check       # validate data + smoke"
	@echo "  make serve       # Flask app"
	@echo "  make test        # pytest"
	@echo "  make eval        # walk-forward smoke KPI"

update:
	$(PYTHON) scripts/cli.py update

data-only:
	$(PYTHON) scripts/cli.py update --data-only

predict:
	$(PYTHON) scripts/cli.py predict

check:
	$(PYTHON) scripts/cli.py check

serve:
	$(PYTHON) scripts/cli.py serve

test:
	$(PYTHON) -m pytest -q

eval:
	$(PYTHON) scripts/cli.py eval --n-test 40
