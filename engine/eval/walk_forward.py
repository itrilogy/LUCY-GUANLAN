#!/usr/bin/env python3
"""
Walk-forward 评估

- run_walk_forward_smoke: 轻量市场 + structure top1
- run_walk_forward_compare: legacy consistency vs multi final 对比（cutover 用）
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np


def random_hit_expectation():
    return 6 * 6 / 33.0  # ≈1.0909


def run_walk_forward_smoke(dh, mm, nm, n_test=50, seed=42, min_train=None):
    """轻量 smoke：结构 top1 + 市场误差。"""
    N = dh.N
    if min_train is None:
        min_train = max(200, N - n_test - 1)
    start = max(min_train, N - n_test - 1)
    hits, p1c_err, bet_err, crowd_pct = [], [], [], []

    for t in range(start, N - 1):
        hat = mm.predict_p1c_from_market(dh.bet[t])
        p1c_err.append(abs(hat - dh.p1c[t]))
        if t > 0:
            bet_hat = mm.predict_bet(dh.pool[t - 1])
            bet_err.append(abs(bet_hat - dh.bet[t]) / max(1.0, float(dh.bet[t])))

        pool_state = mm.get_pool_state(t)
        cands = nm.sample_candidates(30, pool_state)
        if not cands:
            continue
        scored = [(nm.structure_ll_raw(r[0]), r[0]) for r in cands]
        scored.sort(key=lambda x: -x[0])
        top_reds = scored[0][1]
        actual = set(dh.data[t + 1][f"红球{j}"] for j in range(1, 7))
        hits.append(len(set(top_reds) & actual))

        actual_reds = sorted(actual)
        costs = [nm._raw_cost_score(r[0], t=t) for r in cands]
        ac = nm._raw_cost_score(actual_reds, t=t)
        if costs:
            crowd_pct.append(float(np.mean(np.array(costs) <= ac)))

    hits = np.array(hits, dtype=float) if hits else np.array([0.0])
    return {
        "protocol": "wf_freeze_soft_v1_smoke",
        "seed": seed,
        "n_eval": int(len(hits)),
        "start_t": int(start),
        "avg_hit_red_top1": float(hits.mean()),
        "random_hit_expectation": random_hit_expectation(),
        "hit_vs_random": float(hits.mean() / random_hit_expectation()),
        "p1c_mae": float(np.mean(p1c_err)) if p1c_err else None,
        "bet_mape": float(np.mean(bet_err)) if bet_err else None,
        "actual_crowd_percentile_mean": float(np.mean(crowd_pct)) if crowd_pct else None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _eval_mode_window(dh, mm, nm, validator, behavior, mode, start, seed, n_cands=40):
    """mode: 'legacy' | 'multi'"""
    from engine.ranker import MultiRanker

    rng = np.random.default_rng(seed)
    hits, p1c_err, bet_err, crowd_pct = [], [], [], []
    errors = 0
    ranker = MultiRanker(dh, mm, nm, behavior, validator)

    for t in range(start, dh.N - 1):
        try:
            if t > 0:
                bet_hat = mm.predict_bet(dh.pool[t - 1])
                bet_err.append(abs(bet_hat - dh.bet[t]) / max(1.0, float(dh.bet[t])))
            p1c_m = mm.predict_p1c_from_market(dh.bet[t])
            p1c_err.append(abs(p1c_m - dh.p1c[t]))

            pool_state = mm.get_pool_state(t)
            # 固定种子采样：临时设 random seed
            import random
            random.seed(int(seed + t))
            cands = nm.sample_candidates(n_cands, pool_state)
            if not cands:
                continue

            # 简易 validate：用 t 期 bet/regime
            regime_t = int(mm._regime_labels[t])
            bet_t = float(dh.bet[t])
            validated = []
            for reds, blue, cost in cands:
                est = nm.estimate_prize1(reds, bet_t, t=t)
                score = validator.consistency_score(reds, regime_t, bet_t)
                validated.append({
                    "reds": reds, "blue": blue, "cost": cost,
                    "consistency": score, "est_prize1": est,
                })

            if mode == "multi":
                ranked = ranker.rank(validated, bet_amount=bet_t)
                # ranker 使用 latest_t 特征；评估窗口用 structure+anti_crowd 本地近似
                # 若 rank 空则回退
                if not ranked:
                    ranked = sorted(validated, key=lambda x: -x["consistency"])
                top = ranked[0]
                # multi p1c_hat error vs actual prize count at t+1? use market p1c at t
                fwd = ranker.forward_p1c(top["reds"], bet_amount=bet_t, t=t)
                # already have p1c_m error; also track hat residual
                _ = fwd
            else:
                ranked = sorted(validated, key=lambda x: -x["consistency"])
                top = ranked[0]

            actual = set(dh.data[t + 1][f"红球{j}"] for j in range(1, 7))
            hits.append(len(set(top["reds"]) & actual))

            actual_reds = sorted(actual)
            costs = [c[2] for c in cands]
            ac = nm._raw_cost_score(actual_reds, t=t)
            if costs:
                crowd_pct.append(float(np.mean(np.array(costs) <= ac)))
        except Exception:
            errors += 1
            continue

    hits_a = np.array(hits, dtype=float) if hits else np.array([0.0])
    return {
        "mode": mode,
        "n_eval": int(len(hits)),
        "avg_hit_red_top1": float(hits_a.mean()),
        "hit_vs_random": float(hits_a.mean() / random_hit_expectation()),
        "p1c_mae": float(np.mean(p1c_err)) if p1c_err else None,
        "bet_mape": float(np.mean(bet_err)) if bet_err else None,
        "actual_crowd_percentile_mean": float(np.mean(crowd_pct)) if crowd_pct else None,
        "errors": errors,
    }


def run_walk_forward_compare(dh, mm, nm, validator, behavior, n_test=40, seed=42):
    """legacy vs multi 同窗对比。"""
    N = dh.N
    start = max(200, N - n_test - 1)
    legacy = _eval_mode_window(dh, mm, nm, validator, behavior, "legacy", start, seed)
    multi = _eval_mode_window(dh, mm, nm, validator, behavior, "multi", start, seed + 1)
    return {
        "protocol": "wf_freeze_soft_v1_compare",
        "seed": seed,
        "start_t": int(start),
        "n_test": n_test,
        "legacy": legacy,
        "multi": multi,
        "errors": legacy.get("errors", 0) + multi.get("errors", 0),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_kpi(kpi: dict, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)
    return path
