# Cutover Decision

- **Decision**: `go`
- **Reviewer**: automated
- **Created**: 2026-08-11T17:01:05
- **Protocol**: cutover_g1_g5_v1

## Gates

| Gate | Pass | Detail |
|------|------|--------|
| G1_p1c_mae | ✅ | `{'legacy': 5.390650226817442, 'multi': 5.390650226817442, 'rule': 'multi <= legacy * 1.05'}` |
| G2_hit_vs_random | ✅ | `{'legacy': 0.7944444444444445, 'multi': 0.8555555555555556, 'rule': 'multi >= legacy - 0.05'}` |
| G3_bet_mape_vs_baseline | ✅ | `{'baseline': 0.2726115771985358, 'current': 0.27386709319954355, 'rule': 'current bet_mape <= baseline * 1.05 (same n_test window)'}` |
| G4_crowd_percentile | ✅ | `{'legacy': 0.3716666666666667, 'multi': 0.39249999999999996, 'rule': 'multi crowd_pct <= legacy + 0.05'}` |
| G5_runtime | ✅ | `{'errors': 0, 'n_eval': 30, 'rule': 'errors==0 and n_eval>0'}` |

## Notes

- G3 is market health vs baseline, not multi-vs-legacy.
- Hit≈random is expected; G2 only checks multi does not regress vs legacy.
- `go` enables default SCORING_MODE=multi and SCORING_EXPERIMENTAL_GATE=false.

Compare artifact: `/Users/kwangwah/Project/Lottery/ssq_predictor/data/eval/wf_compare_latest.json`
