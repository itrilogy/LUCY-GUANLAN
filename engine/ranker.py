#!/usr/bin/env python3
"""
多目标排序 —— anti_crowd / structure / market_fit → final

consistency 仅展示，不进 final。
"""

from __future__ import annotations

from typing import Iterable, List, Dict, Any

import numpy as np

import config as _cfg
from config import RANK_WEIGHTS, prize_clamp


def _minmax(arr: List[float]) -> List[float]:
    if not arr:
        return []
    a = np.asarray(arr, dtype=float)
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-12:
        return [0.5] * len(arr)
    return [float(x) for x in (a - lo) / (hi - lo)]


class MultiRanker:
    """对 batch_validate 结果附加多目标分并排序"""

    def __init__(self, dh, mm, nm, behavior, validator, alpha=None):
        self.dh = dh
        self.mm = mm
        self.nm = nm
        self.behavior = behavior
        self.validator = validator
        self.alpha = float(alpha if alpha is not None else _cfg.FORWARD_COST_ALPHA)
        self.weights = dict(RANK_WEIGHTS)

    def forward_p1c(self, reds, bet_amount=None, t=None) -> dict:
        bet = float(bet_amount if bet_amount is not None else self.dh.bet[self.dh.latest_t])
        p1c_m = self.mm.predict_p1c_from_market(bet)
        g = self.nm.g_cost_p1c(reds, t=t)
        p1c_hat = max(0.0, p1c_m + self.alpha * g)
        return {
            "p1c_hat": p1c_hat,
            "p1c_market": p1c_m,
            "g_p1c": g,
            "alpha": self.alpha,
        }

    def _market_fit_raw(self, p1c_hat, current_regime, pool, bet) -> float:
        if _cfg.BACKWARD_MODE == "conditional":
            back = self.validator.backward_conditional(
                p1c_hat, pool=pool, bet=bet, regime=current_regime
            )
        else:
            back = self.validator.backward(prize_clamp(p1c_hat))
        if not back:
            return 0.0
        return float(back["regime_dist"].get(current_regime, 0.0))

    def rank(self, validated: List[dict], bet_amount=None) -> List[dict]:
        """
        validated: list of {reds, blue, cost, consistency, ...}
        returns new list sorted by final desc.
        """
        if not validated:
            return []

        t = self.dh.latest_t
        regime = self.mm.get_regime(t)
        pool = float(self.dh.pool[t])
        bet = float(bet_amount if bet_amount is not None else self.dh.bet[t])

        anti_raw, struct_raw, mfit_raw = [], [], []
        fwd_list = []
        for r in validated:
            reds = r["reds"]
            anti_raw.append(self.behavior.anti_crowd_raw(reds, t=t))
            struct_raw.append(self.nm.structure_ll_raw(reds))
            fwd = self.forward_p1c(reds, bet_amount=bet, t=t)
            fwd_list.append(fwd)
            mfit_raw.append(self._market_fit_raw(fwd["p1c_hat"], regime, pool, bet))

        anti = _minmax(anti_raw)
        struct = _minmax(struct_raw)
        mfit = _minmax(mfit_raw)
        w = self.weights

        out = []
        for i, r in enumerate(validated):
            final = (
                w["anti_crowd"] * anti[i]
                + w["structure"] * struct[i]
                + w["market_fit"] * mfit[i]
            )
            item = dict(r)
            item["scores"] = {
                "anti_crowd": round(anti[i], 4),
                "structure": round(struct[i], 4),
                "market_fit": round(mfit[i], 4),
                "final": round(float(final), 4),
                "consistency": round(float(r.get("consistency", 0)), 4),
                "crowd_raw": round(-anti_raw[i], 4),
                "p1c_hat": round(fwd_list[i]["p1c_hat"], 3),
                "p1c_market": round(fwd_list[i]["p1c_market"], 3),
            }
            item["final"] = float(final)
            out.append(item)

        out.sort(
            key=lambda x: (
                -x["final"],
                -x["scores"]["structure"],
                x["scores"]["crowd_raw"],
                tuple(x["reds"]),
            )
        )
        return out
