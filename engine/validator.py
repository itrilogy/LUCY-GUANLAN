#!/usr/bin/env python3
"""
双向验证器 —— 前向推演 + 反向校验 + 一致性评分

核心循环:
  前向: 当前市场状态 + 候选号码 → 预期头奖注数
  反向: 预期头奖注数 → 反推最可能的市场状态
  评分: 前向假设 vs 反向推得 → 一致性分数

Phase 1: prize LUT + batch_validate 单次 forward/backward
"""

import numpy as np
from collections import Counter

from config import (
    BACKWARD_LUT_MAX_PRIZE,
    BACKWARD_TOP_K,
    BACKWARD_DIST_WEIGHTS,
    CONSISTENCY_CURRENT_WEIGHT,
    CONSISTENCY_ENTROPY_WEIGHT,
    prize_clamp,
)


class Validator:
    """双向验证器"""

    def __init__(self, dh, mm, nm):
        self.dh = dh
        self.mm = mm
        self.nm = nm
        self.N = dh.N
        self._backward_lut = None
        self._backward_lut_meta = None

    # ── 前向通道 ───────────────────────────────────────────

    def forward(self, reds, bet_amount=None):
        """给定号码组合 → 估算头奖注数"""
        if bet_amount is None:
            bet_amount = self.dh.bet[self.dh.latest_t]
        return self.nm.estimate_prize1(reds, bet_amount)

    # ── 反向通道 ───────────────────────────────────────────

    def backward(self, prize1_count, top_k=None):
        """
        反向: 给定头奖注数 → 反推"开奖前的市场状态"
        用 issue → t 映射定位前一期（不依赖 draws.id）。
        """
        if top_k is None:
            top_k = BACKWARD_TOP_K
        rows = self.dh.db_query(
            "SELECT issue, prize1_cnt FROM draws "
            "ORDER BY ABS(prize1_cnt - ?) LIMIT ?",
            (int(prize1_count), top_k),
        )
        if not rows:
            return None

        issue_to_t = getattr(self.dh, "issue_to_t", None) or {
            issue: t for t, issue in enumerate(self.dh.issues)
        }

        states = []
        for row in rows:
            issue = row[0]
            t = issue_to_t.get(str(issue))
            if t is None:
                t = issue_to_t.get(issue)
            if t is None or t < 1:
                continue
            prev_t = t - 1
            if prev_t >= self.dh.N:
                continue
            states.append({
                "pool_before": float(self.dh.pool[prev_t]),
                "bet_before": float(self.dh.bet[prev_t]),
                "regime": int(self.mm._regime_labels[prev_t]),
                "pool_state": self.mm.get_pool_state(prev_t),
                "issue": str(issue),
                "t": t,
            })

        if not states:
            return None

        regime_counts = Counter(s["regime"] for s in states)
        total = len(states)

        return {
            "regime_dist": {k: v / total for k, v in regime_counts.items()},
            "most_likely_regime": max(regime_counts, key=regime_counts.get),
            "avg_pool_before": float(np.mean([s["pool_before"] for s in states])),
            "avg_bet_before": float(np.mean([s["bet_before"] for s in states])),
            "pool_state_dist": Counter(s["pool_state"] for s in states),
            "n_samples": total,
        }

    def backward_conditional(
        self, p1c_hat, pool=None, bet=None, regime=None, top_k=None, weights=None
    ):
        """
        条件近邻反向：在 (p1c, pool_prev, bet_prev, regime_prev) 空间找邻居。
        当 weights 仅 w_p=1 时近似 prize-only。
        """
        top_k = BACKWARD_TOP_K if top_k is None else top_k
        w = dict(BACKWARD_DIST_WEIGHTS)
        if weights:
            w.update(weights)

        t_now = self.dh.latest_t
        pool = float(self.dh.pool[t_now] if pool is None else pool)
        bet = float(self.dh.bet[t_now] if bet is None else bet)
        if regime is None:
            regime = int(self.mm.get_regime(t_now))

        # 历史 t>=1：用 t 的 p1c 与 t-1 的市场状态
        p1c_hist = self.dh.p1c[1:]
        pool_prev = self.dh.pool[:-1]
        bet_prev = self.dh.bet[:-1]
        regime_prev = self.mm._regime_labels[:-1]
        n = len(p1c_hist)
        if n == 0:
            return self.backward(prize_clamp(p1c_hat), top_k=top_k)

        def _z(x, arr):
            mu, sd = float(np.mean(arr)), float(np.std(arr)) + 1e-10
            return (float(x) - mu) / sd

        z_p = _z(p1c_hat, p1c_hist)
        z_pool = _z(pool, pool_prev)
        z_bet = _z(bet, bet_prev)
        zp = (p1c_hist - p1c_hist.mean()) / (p1c_hist.std() + 1e-10)
        zpo = (pool_prev - pool_prev.mean()) / (pool_prev.std() + 1e-10)
        zb = (bet_prev - bet_prev.mean()) / (bet_prev.std() + 1e-10)
        d = (
            w["w_p"] * np.abs(zp - z_p)
            + w["w_pool"] * np.abs(zpo - z_pool)
            + w["w_bet"] * np.abs(zb - z_bet)
            + w["w_r"] * (regime_prev != regime).astype(float)
        )
        k = min(top_k, n)
        idx = np.argpartition(d, k - 1)[:k]
        # idx 是相对 p1c_hist 的，对应真实期号 t = idx+1，前一期 prev = idx
        states = []
        for i in idx:
            prev_t = int(i)
            states.append({
                "pool_before": float(self.dh.pool[prev_t]),
                "bet_before": float(self.dh.bet[prev_t]),
                "regime": int(self.mm._regime_labels[prev_t]),
                "pool_state": self.mm.get_pool_state(prev_t),
                "t": prev_t + 1,
            })
        if not states:
            return None
        regime_counts = Counter(s["regime"] for s in states)
        total = len(states)
        return {
            "regime_dist": {k: v / total for k, v in regime_counts.items()},
            "most_likely_regime": max(regime_counts, key=regime_counts.get),
            "avg_pool_before": float(np.mean([s["pool_before"] for s in states])),
            "avg_bet_before": float(np.mean([s["bet_before"] for s in states])),
            "pool_state_dist": Counter(s["pool_state"] for s in states),
            "n_samples": total,
            "mode": "conditional",
        }

    # ── Prize LUT ──────────────────────────────────────────

    def ensure_backward_lut(self, max_prize=None, top_k=None):
        """预计算 prize∈[0,max] 的 backward 结果。"""
        max_prize = BACKWARD_LUT_MAX_PRIZE if max_prize is None else max_prize
        top_k = BACKWARD_TOP_K if top_k is None else top_k
        meta = (max_prize, top_k)
        if self._backward_lut is not None and self._backward_lut_meta == meta:
            return
        self._backward_lut = {
            p: self.backward(p, top_k=top_k) for p in range(max_prize + 1)
        }
        self._backward_lut_meta = meta

    def invalidate_backward_lut(self):
        """数据变更后必须调用。"""
        self._backward_lut = None
        self._backward_lut_meta = None

    def _score_from_backward(self, back_result, current_regime) -> float:
        """
        regime_prob * w + concentration * (1-w)
        不含 tbd_bonus（仅 batch_validate 使用）。
        """
        if back_result is None:
            return 0.0
        regime_prob = back_result["regime_dist"].get(current_regime, 0)
        probs = list(back_result["regime_dist"].values())
        regime_entropy = -sum(p * np.log(p + 1e-10) for p in probs)
        max_entropy = np.log(max(1, len(probs)))
        concentration = 1 - regime_entropy / max_entropy if max_entropy > 0 else 1.0
        w = CONSISTENCY_CURRENT_WEIGHT
        score = regime_prob * w + concentration * (1.0 - w)
        return float(min(1.0, max(0.0, score)))

    def _tbd_bonus(self, back_result, tbd_prior) -> float:
        """batch_validate 专用：与 regime T_bwd 重叠，最高 +0.2。"""
        if not back_result:
            return 0.0
        bwd_total = sum(back_result["regime_dist"].values()) or 1.0
        overlap = 0.0
        for r_k, r_p in back_result["regime_dist"].items():
            overlap += min(r_p / bwd_total, float(tbd_prior[int(r_k)]))
        return round(overlap * 0.2, 3)

    # ── 一致性评分 ─────────────────────────────────────────

    def consistency_score(self, reds, current_regime=None, bet_amount=None):
        """
        完整前向→反向→评分。公开 API 不含 tbd_bonus。
        """
        if current_regime is None:
            current_regime = self.mm.get_regime()
        if bet_amount is None:
            bet_amount = self.dh.bet[self.dh.latest_t]

        est_prize = self.forward(reds, bet_amount)
        back_result = self.backward(est_prize, top_k=BACKWARD_TOP_K)
        return self._score_from_backward(back_result, current_regime)

    # ── 批量验证 ───────────────────────────────────────────

    def batch_validate(self, candidates):
        """
        对批量候选运行验证并按 consistency 降序。
        单次 forward + LUT backward（含 tbd_bonus）。
        """
        current_regime = self.mm.get_regime()
        bet_amount = self.dh.bet[self.dh.latest_t]
        tbd_prior = self.mm.regime_T_bwd[current_regime]

        self.ensure_backward_lut(top_k=BACKWARD_TOP_K)

        results = []
        for reds, blue, cost in candidates:
            est_prize = self.forward(reds, bet_amount)
            key = prize_clamp(est_prize)
            back_result = self._backward_lut.get(key)
            raw = self._score_from_backward(back_result, current_regime)
            tbd_bonus = self._tbd_bonus(back_result, tbd_prior)
            adjusted = min(1.0, raw * (1.0 + tbd_bonus))
            results.append({
                "reds": reds,
                "blue": blue,
                "cost": cost,
                "consistency": round(adjusted, 4),
                "raw_consistency": round(raw, 4),
                "est_prize1": est_prize,
                "tbd_bonus": round(tbd_bonus, 3),
            })

        results.sort(key=lambda x: x["consistency"], reverse=True)
        return results

    # ── 历史回测 ───────────────────────────────────────────

    def backtest(self, n_test=200):
        """留一法：高评分 top-1 红球命中 vs 随机基线。"""
        results = []
        for t in range(self.N - n_test, self.N - 1):
            regime_t = self.mm._regime_labels[t]
            pool_state = self.mm.get_pool_state(t)
            candidates = self.nm.sample_candidates(200, pool_state)

            validated = []
            for reds, blue, cost in candidates:
                score = self.consistency_score(reds, regime_t, self.dh.bet[t])
                validated.append((score, reds, blue))

            validated.sort(key=lambda x: x[0], reverse=True)
            actual_reds = sorted([self.dh.data[t + 1][f"红球{j}"] for j in range(1, 7)])
            if validated:
                top_reds = validated[0][1]
                hits = len(set(top_reds) & set(actual_reds))
                results.append(hits)

        if not results:
            return {"avg_hits": 0, "hits_list": []}

        return {
            "avg_hits": float(np.mean(results)),
            "hits_list": results,
            "vs_random": float(np.mean(results)) / (6 * 6 / 33),
        }
