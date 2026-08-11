#!/usr/bin/env python3
"""
Walk-forward 评估（wf_freeze_soft_v1 简化 smoke）

协议要点：
- 在 min_train 之后逐期：用 t 的市场状态评估 t 期结构/成本信号
- 记录 hit_red top1、p1c_market MAE、crowd 分位
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np


def random_hit_expectation():
    return 6 * 6 / 33.0  # ≈1.0909


def run_walk_forward_smoke(dh, mm, nm, n_test=50, seed=42, min_train=None):
    """
    轻量 smoke：不重训 GMM，使用全量已 fit 的 mm 标签（与生产 soft 近似）。
    返回 KPI dict。
    """
    rng = np.random.default_rng(seed)
    N = dh.N
    if min_train is None:
        min_train = max(200, N - n_test - 1)
    start = max(min_train, N - n_test - 1)
    hits = []
    p1c_err = []
    bet_err = []
    crowd_pct = []

    for t in range(start, N - 1):
        # 市场 p1c 预测误差（用 t 的 bet 预测 t 的 p1c）
        hat = mm.predict_p1c_from_market(dh.bet[t])
        p1c_err.append(abs(hat - dh.p1c[t]))
        # bet 方向：用 pool_{t-1} 预测 bet_t
        if t > 0:
            bet_hat = mm.predict_bet(dh.pool[t - 1])
            bet_err.append(abs(bet_hat - dh.bet[t]) / max(1.0, dh.bet[t]))

        # 随机基线对照：抽一组号码 vs 实际
        pool_state = mm.get_pool_state(t)
        cands = nm.sample_candidates(30, pool_state)
        # 用结构 LL 取 top1（非 consistency 重计算，smoke）
        scored = [(nm.structure_ll_raw(r[0]), r[0]) for r in cands]
        scored.sort(key=lambda x: -x[0])
        top_reds = scored[0][1]
        actual = set(dh.data[t + 1][f"红球{j}"] for j in range(1, 7))
        hits.append(len(set(top_reds) & actual))

        # 实际组合的 crowd 分位（越高越拥挤）
        actual_reds = sorted(actual)
        costs = [nm._raw_cost_score(r[0], t=t) for r in cands]
        ac = nm._raw_cost_score(actual_reds, t=t)
        if costs:
            crowd_pct.append(float(np.mean(np.array(costs) <= ac)))

    hits = np.array(hits, dtype=float)
    kpi = {
        "protocol": "wf_freeze_soft_v1_smoke",
        "seed": seed,
        "n_eval": int(len(hits)),
        "start_t": int(start),
        "avg_hit_red_top1": float(hits.mean()) if len(hits) else 0.0,
        "random_hit_expectation": random_hit_expectation(),
        "hit_vs_random": float(hits.mean() / random_hit_expectation()) if len(hits) else 0.0,
        "p1c_mae": float(np.mean(p1c_err)) if p1c_err else None,
        "bet_mape": float(np.mean(bet_err)) if bet_err else None,
        "actual_crowd_percentile_mean": float(np.mean(crowd_pct)) if crowd_pct else None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return kpi


def save_kpi(kpi: dict, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kpi, f, ensure_ascii=False, indent=2)
    return path
