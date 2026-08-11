# ssq_predictor — developer commands (run from this directory)
PYTHON ?= python3

.PHONY: help update predict check serve test data-only eval cutover migrate-rank

help:
	@echo "Targets (run inside ssq_predictor/):"
	@echo "  make serve         # 启动 Web → http://localhost:8080"
	@echo "  make check         # 数据校验 + 引擎冒烟"
	@echo "  make update        # 爬取 + full 重建 + 预测"
	@echo "  make data-only     # 仅爬取合并"
	@echo "  make predict       # 仅预测"
	@echo "  make test          # pytest"
	@echo "  make eval          # walk-forward smoke KPI"
	@echo "  make cutover       # G1–G5 门禁 + scoring_defaults"
	@echo "  make migrate-rank  # predictions rank 迁移"

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

cutover:
	$(PYTHON) scripts/cli.py eval --cutover --n-test 40

migrate-rank:
	$(PYTHON) scripts/migrate_predictions_rank_v2.py
