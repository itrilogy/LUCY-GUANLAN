#!/usr/bin/env python3
"""
Cutover 门禁 G1–G5 + baseline_market + cutover_decision

G1: multi 的 p1c_hat MAE ≤ legacy 的 est 路径误差 × 1.05（或 ≤ baseline）
G2: multi hit_vs_random 不低于 legacy - 0.05
G3: bet MAE ≤ baseline_market × 1.05（市场健康，非 multi-vs-legacy）
G4: multi actual_crowd_percentile ≤ legacy + 0.05（更不拥挤更好，不显著变差）
G5: 无运行时异常 + 报告可序列化
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np

from config import DATA_DIR, ENGINE_STATE_FILE
from engine.eval.walk_forward import (
    random_hit_expectation,
    run_walk_forward_compare,
    save_kpi,
)


EVAL_DIR = os.path.join(DATA_DIR, "eval")
BASELINE_MARKET = os.path.join(EVAL_DIR, "baseline_market.json")
CUTOVER_DECISION = os.path.join(EVAL_DIR, "cutover_decision.md")
WF_COMPARE = os.path.join(EVAL_DIR, "wf_compare_latest.json")


def ensure_baseline_market(dh, mm, force=False, n_test=80):
    """写入/更新市场健康基线（bet MAPE、p1c MAE）；窗口与 cutover 对齐"""
    os.makedirs(EVAL_DIR, exist_ok=True)
    if os.path.exists(BASELINE_MARKET) and not force:
        with open(BASELINE_MARKET, encoding="utf-8") as f:
            bl = json.load(f)
            # 窗口不一致时强制刷新
            if bl.get("n_test") == n_test:
                return bl

    start = max(1, dh.N - n_test - 1)
    bet_err, p1c_err = [], []
    for t in range(start, dh.N):
        if t < 1:
            continue
        bet_hat = mm.predict_bet(dh.pool[t - 1])
        bet_err.append(abs(bet_hat - dh.bet[t]) / max(1.0, float(dh.bet[t])))
        p1c_hat = mm.predict_p1c_from_market(dh.bet[t])
        p1c_err.append(abs(p1c_hat - dh.p1c[t]))

    baseline = {
        "protocol": "baseline_market_v1",
        "n_test": n_test,
        "n_eval": len(bet_err),
        "start_t": start,
        "bet_mape": float(np.mean(bet_err)) if bet_err else None,
        "p1c_mae": float(np.mean(p1c_err)) if p1c_err else None,
        "latest_issue": dh.latest_issue,
        "N": dh.N,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(BASELINE_MARKET, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)
    return baseline


def evaluate_gates(dh, mm, nm, validator, behavior, n_test=40, seed=42):
    """运行对比评估并判定 G1–G5"""
    # 基线与评估同窗；首次或 n_test 变化时刷新
    baseline = ensure_baseline_market(dh, mm, force=False, n_test=n_test)
    compare = run_walk_forward_compare(
        dh, mm, nm, validator, behavior, n_test=n_test, seed=seed
    )
    save_kpi(compare, WF_COMPARE)

    legacy = compare["legacy"]
    multi = compare["multi"]
    gates = {}

    # G1: multi market-side p1c MAE not worse than legacy*1.05
    g1_ok = (
        multi["p1c_mae"] is not None
        and legacy["p1c_mae"] is not None
        and multi["p1c_mae"] <= legacy["p1c_mae"] * 1.05 + 1e-9
    )
    gates["G1_p1c_mae"] = {
        "pass": bool(g1_ok),
        "legacy": legacy["p1c_mae"],
        "multi": multi["p1c_mae"],
        "rule": "multi <= legacy * 1.05",
    }

    # G2: hit_vs_random
    g2_ok = multi["hit_vs_random"] >= legacy["hit_vs_random"] - 0.05
    gates["G2_hit_vs_random"] = {
        "pass": bool(g2_ok),
        "legacy": legacy["hit_vs_random"],
        "multi": multi["hit_vs_random"],
        "rule": "multi >= legacy - 0.05",
    }

    # G3: market health — same-window bet_mape vs frozen baseline
    # 同窗刷新基线后应近似相等；允许 5% 漂移
    g3_ok = (
        baseline.get("bet_mape") is not None
        and legacy.get("bet_mape") is not None
        and legacy["bet_mape"] <= baseline["bet_mape"] * 1.05 + 1e-9
    )
    gates["G3_bet_mape_vs_baseline"] = {
        "pass": bool(g3_ok),
        "baseline": baseline.get("bet_mape"),
        "current": legacy.get("bet_mape"),
        "rule": "current bet_mape <= baseline * 1.05 (same n_test window)",
    }

    # G4: crowd percentile (lower = actual less crowded than candidates — softer gate)
    g4_ok = (
        multi.get("actual_crowd_percentile_mean") is not None
        and legacy.get("actual_crowd_percentile_mean") is not None
        and multi["actual_crowd_percentile_mean"]
        <= legacy["actual_crowd_percentile_mean"] + 0.05 + 1e-9
    )
    gates["G4_crowd_percentile"] = {
        "pass": bool(g4_ok),
        "legacy": legacy.get("actual_crowd_percentile_mean"),
        "multi": multi.get("actual_crowd_percentile_mean"),
        "rule": "multi crowd_pct <= legacy + 0.05",
    }

    # G5: runtime health
    g5_ok = compare.get("errors", 0) == 0 and multi.get("n_eval", 0) > 0
    gates["G5_runtime"] = {
        "pass": bool(g5_ok),
        "errors": compare.get("errors", 0),
        "n_eval": multi.get("n_eval"),
        "rule": "errors==0 and n_eval>0",
    }

    all_pass = all(g["pass"] for g in gates.values())
    decision = "go" if all_pass else "no-go"

    report = {
        "decision": decision,
        "gates": gates,
        "baseline_market": baseline,
        "compare_path": WF_COMPARE,
        "protocol": "cutover_g1_g5_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "random_hit_expectation": random_hit_expectation(),
    }
    return report


def write_cutover_decision(report: dict, reviewer="automated"):
    os.makedirs(EVAL_DIR, exist_ok=True)
    lines = [
        "# Cutover Decision",
        "",
        f"- **Decision**: `{report['decision']}`",
        f"- **Reviewer**: {reviewer}",
        f"- **Created**: {report['created_at']}",
        f"- **Protocol**: {report.get('protocol')}",
        "",
        "## Gates",
        "",
        "| Gate | Pass | Detail |",
        "|------|------|--------|",
    ]
    for name, g in report["gates"].items():
        detail = {k: v for k, v in g.items() if k != "pass"}
        lines.append(f"| {name} | {'✅' if g['pass'] else '❌'} | `{detail}` |")
    lines.extend([
        "",
        "## Notes",
        "",
        "- G3 is market health vs baseline, not multi-vs-legacy.",
        "- Hit≈random is expected; G2 only checks multi does not regress vs legacy.",
        "- `go` enables default SCORING_MODE=multi and SCORING_EXPERIMENTAL_GATE=false.",
        "",
        f"Compare artifact: `{report.get('compare_path')}`",
        "",
    ])
    text = "\n".join(lines)
    with open(CUTOVER_DECISION, "w", encoding="utf-8") as f:
        f.write(text)
    # machine readable
    with open(os.path.join(EVAL_DIR, "cutover_decision.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return CUTOVER_DECISION


def apply_cutover_config(decision: str):
    """
    根据 decision 写 config 覆盖文件 data/eval/scoring_defaults.json
    （config.py 启动时读取，避免直接改源码产生噪声 diff 时也可强制）。
    """
    path = os.path.join(EVAL_DIR, "scoring_defaults.json")
    if decision == "go":
        payload = {
            "SCORING_MODE": "multi",
            "SCORING_EXPERIMENTAL_GATE": False,
            "EVOLUTION_MODE": "off",
            "BACKWARD_MODE": "conditional",
            "applied_from": "cutover_go",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        payload = {
            "SCORING_MODE": "legacy",
            "SCORING_EXPERIMENTAL_GATE": True,
            "EVOLUTION_MODE": "off",
            "BACKWARD_MODE": "prize",
            "applied_from": "cutover_no_go",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # also patch engine_state
    st = {}
    if os.path.exists(ENGINE_STATE_FILE):
        try:
            with open(ENGINE_STATE_FILE, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
    st["cutover_decision"] = decision
    st["scoring_defaults"] = payload
    with open(ENGINE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    return path
