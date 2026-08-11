#!/usr/bin/env python3
"""
BehaviorModel —— 人群拥挤 / 成本代理（B）

crowd_raw 复用 NumberModel 庄家成本分，不另起一套公式。
"""

from __future__ import annotations


class BehaviorModel:
    """行为/拥挤估计"""

    def __init__(self, dh, nm):
        self.dh = dh
        self.nm = nm

    def crowd_raw(self, reds, t=None) -> float:
        """正 = 更热门/更拥挤（与 _raw_cost_score 一致）"""
        return float(self.nm._raw_cost_score(reds, t=t))

    def anti_crowd_raw(self, reds, t=None) -> float:
        return -self.crowd_raw(reds, t=t)

    def popularity(self, top_n=10) -> dict:
        return self.nm.get_popularity_analysis(top_n=top_n)
