# Baseline freeze

| Field | Value |
|-------|--------|
| Date | 2026-08-08 |
| Product path | `ssq_predictor/` |
| Plan | `docs/ENGINEERING_RENOVATION_PLAN.md` rev 3 |

## Data (post-crawl)

- Source: `data/ssq_all.json` + `data/ssq.db`
- Expected range after crawl: 03001 → 26090+ (N≈3487+)
- Schedule: Tue/Thu/Sun 22:00; `STARTUP_FETCH=auto`

## Engineering baseline (already landed before Phase 1 PRs)

- Crawler + merge + hit backfill
- `issue_to_t` backward
- Vectorized red features + cost frequency prefix sums
- Draw-day scheduler

## Phase 1 freeze (this delivery)

- Prize LUT + single-pass `batch_validate`
- Soft reinit (in-process) / CLI full
- Makefile + `scripts/cli.py`
- Research archive under `../research/archive/`
- SQLite RLock
- `predictions.rank` TEXT + `rank_order`
- Brand: `web/static/brand/*` + 鹿溪 lockup

## Golden seed note

- Tests use `tests/fixtures/mini_draws.json` (last 80 draws snapshot at freeze time).
- For ranking parity regressions, fix `random.seed` when comparing sample-dependent paths.
