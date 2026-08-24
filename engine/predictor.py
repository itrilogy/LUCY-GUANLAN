#!/usr/bin/env python3
"""
预测引擎 —— 整合所有模块的编排层

流程:
  市场状态 → 候选采样 → 双向验证 → [可选 multi 排序] → 复式 → 报告
"""

import json
import os
import time

import numpy as np

import config as cfg
from config import PREDICT_FILE, TOP_N
from engine.numbers import CompoundBetPlanner
from engine.behavior import BehaviorModel
from engine.ranker import MultiRanker
from engine.evolution import Evolution, save_weights, load_weights, WEIGHTS_FILE


def write_progress(stage, pct, msg):
    try:
        with open(WEIGHTS_FILE.replace("weights.json", "progress.json"), "w") as f:
            json.dump(
                {"running": True, "stage": stage, "progress": pct, "message": msg}, f
            )
    except Exception:
        pass


def clear_progress():
    try:
        with open(WEIGHTS_FILE.replace("weights.json", "progress.json"), "w") as f:
            json.dump(
                {"running": False, "stage": "idle", "progress": 0, "message": "就绪"}, f
            )
    except Exception:
        pass


def _experimental_allowed():
    if not cfg.SCORING_EXPERIMENTAL_GATE:
        return True
    return os.environ.get("SSQ_ALLOW_EXPERIMENTAL_SCORING", "0") in ("1", "true", "yes")


def resolve_scoring_mode(requested=None):
    mode = (requested or cfg.SCORING_MODE or "legacy").lower()
    if mode not in ("legacy", "multi", "dual"):
        mode = "legacy"
    if mode in ("multi", "dual") and not _experimental_allowed():
        return "legacy", "experimental_gate_blocked"
    return mode, None


class Predictor:

    def __init__(self, dh, mm, nm, validator, behavior=None):
        self.dh = dh
        self.mm = mm
        self.nm = nm
        self.validator = validator
        self.behavior = behavior or BehaviorModel(dh, nm)
        self.bp = CompoundBetPlanner(validator, nm)
        self.ranker = MultiRanker(dh, mm, nm, self.behavior, validator)

    def run(self, n_candidates=2000, evolve=False, scoring_mode=None):
        """运行完整预测流程"""
        t0 = time.time()
        mode, gate_note = resolve_scoring_mode(scoring_mode)

        # 0. 进化（可关闭）
        evo_mode = cfg.EVOLUTION_MODE
        if evolve and evo_mode == "off":
            write_progress("sampling", 2, "进化已关闭 (EVOLUTION_MODE=off)...")
            evolve = False
        if evolve:
            write_progress(
                "evolution",
                2,
                "研究用自洽进化（非命中优化）初始化...",
            )
            evo = Evolution(self.dh, self.validator, self.nm)
            best_gene, _ = evo.run()
            save_weights(best_gene)
            write_progress("sampling", 88, "进化完成，进入采样验证...")
        else:
            write_progress("sampling", 2, "使用缓存权重预测...")

        regime_desc = self.mm.get_regime_description()
        pool_state = regime_desc["pool_state"]

        write_progress("sampling", 3, "采样候选号码...")
        candidates = self.nm.sample_candidates(n_candidates, pool_state)

        write_progress("validating", 5, f"双向验证 {n_candidates} 候选...")
        validated = self.validator.batch_validate(candidates)

        # multi / dual 排序
        predictions_legacy = None
        if mode in ("multi", "dual"):
            write_progress("ranking", 85, "多目标排序 (anti_crowd/structure/market_fit)...")
            ranked = self.ranker.rank(validated)
            if mode == "dual":
                predictions_legacy = validated[:TOP_N]
            active = ranked
            sort_key = "final"
        else:
            active = validated
            sort_key = "consistency"

        write_progress("compound", 92, "规划复式方案...")
        # 复式覆盖权重：multi 用 final 填入 consistency 字段供 planner
        plan_src = active
        if mode in ("multi", "dual"):
            plan_src = []
            for r in active:
                rr = dict(r)
                rr["consistency"] = float(r.get("final", r.get("consistency", 0)))
                plan_src.append(rr)
        compound_plans = self.bp.build_tiers(plan_src)

        top = active[:TOP_N]

        from collections import Counter

        freq_reds = Counter()
        freq_blues = Counter()
        for r in top:
            for n in r["reds"]:
                freq_reds[n] += 1
            freq_blues[r["blue"]] += 1
        top10_reds = sorted([n for n, _ in freq_reds.most_common(10)])
        top2_blues = sorted([n for n, _ in freq_blues.most_common(2)])
        combo_cnt2 = __import__("math").comb(len(top10_reds), 6) * len(top2_blues)
        cost_yuan2 = combo_cnt2 * 2
        freq_compound = {
            "tier_name": "高频聚合",
            "tier_desc": f"{combo_cnt2}注={cost_yuan2}元 · 频次参考",
            "reds": top10_reds,
            "blues": top2_blues,
            "total_combos": combo_cnt2,
            "total_cost": cost_yuan2,
            "avg_match_rate": round(
                len(set(top10_reds) & set(n for r in top for n in r["reds"])) / 60, 4
            ),
            "consistency": round(
                sum(r.get("consistency", 0) for r in top) / max(1, len(top)), 4
            ),
            "note": "非评分排序，仅频次参考",
        }
        compound_plans.append(freq_compound)

        write_progress("report", 97, "生成报告...")
        report = self._build_report(
            regime_desc,
            top,
            candidates,
            t0,
            compound_plans,
            scoring_mode=mode,
            sort_key=sort_key,
            predictions_legacy=predictions_legacy,
            gate_note=gate_note,
            evolve=evolve,
        )
        clear_progress()
        return report

    def _build_report(
        self,
        regime_desc,
        top,
        all_candidates,
        t0,
        compound_plans=None,
        scoring_mode="legacy",
        sort_key="consistency",
        predictions_legacy=None,
        gate_note=None,
        evolve=False,
    ):
        elapsed = time.time() - t0
        last_review = self._last_review()
        popularity = self.behavior.popularity()
        current_pool = regime_desc["pool"]
        predicted_bet = self.mm.predict_bet(current_pool)
        p1c_m = self.mm.predict_p1c_from_market(
            regime_desc["bet"] if regime_desc.get("bet") else self.dh.bet[self.dh.latest_t]
        )

        predictions = []
        for i, r in enumerate(top):
            entry = {
                "rank": i + 1,
                "reds": [int(x) for x in r["reds"]],
                "blue": int(r["blue"]),
                "consistency": round(float(r.get("consistency", 0)), 4),
                "cost": round(float(r.get("cost", 0)), 2),
                "est_prize1": int(r.get("est_prize1", 0)),
                "passed": bool(float(r.get("consistency", 0)) > 0.2),
            }
            if "scores" in r:
                entry["scores"] = r["scores"]
                entry["final"] = round(float(r.get("final", 0)), 4)
            predictions.append(entry)

        legacy_list = None
        if predictions_legacy is not None:
            legacy_list = []
            for i, r in enumerate(predictions_legacy[:TOP_N]):
                legacy_list.append({
                    "rank": i + 1,
                    "reds": [int(x) for x in r["reds"]],
                    "blue": int(r["blue"]),
                    "consistency": round(float(r["consistency"]), 4),
                    "cost": round(float(r["cost"]), 2),
                    "est_prize1": int(r.get("est_prize1", 0)),
                })

        score_field = "final" if scoring_mode in ("multi", "dual") else "consistency"
        top_score = predictions[0].get(score_field, predictions[0]["consistency"]) if predictions else 0
        avg_score = (
            float(np.mean([p.get(score_field, p["consistency"]) for p in predictions]))
            if predictions
            else 0
        )

        return {
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "current_issue": self.dh.next_issue,
            "elapsed": round(elapsed, 1),
            "scoring_mode": scoring_mode,
            "sort_key": sort_key,
            "gate_note": gate_note,
            "evolution_used": bool(evolve),
            "evolution_note": (
                "研究用自洽进化（非命中优化）" if evolve else None
            ),
            "disclaimer": (
                "本工具客观刻画奖池状态与组合拥挤度，"
                "红蓝球开奖接近真随机，一致性评分非中奖预言。"
            ),
            "market": {
                "regime": regime_desc["pool_state"],
                "regime_id": regime_desc["regime_id"],
                "pool": int(current_pool),
                "bet": int(regime_desc["bet"]),
                "p1c_market_hat": round(float(p1c_m), 2),
                "predicted_pool_range": [
                    int(current_pool * 0.9),
                    int(current_pool * 1.1),
                ],
                "predicted_bet_range": [
                    int(predicted_bet * 0.9),
                    int(predicted_bet * 1.1),
                ],
            },
            "predictions": predictions,
            "predictions_legacy": legacy_list,
            "popularity": {
                "hot": popularity["hot"],
                "cold": popularity["cold"],
                "birthday_effect": popularity["birthday_effect"],
            },
            "last_review": last_review,
            "compound_plans": compound_plans or [],
            "stats": {
                "total_candidates": len(all_candidates),
                "top_score": top_score,
                "avg_score": avg_score,
            },
        }

    def _last_review(self):
        t = self.dh.latest_t
        if t < 1:
            return None
        actual_reds = sorted([self.dh.data[t][f"红球{j}"] for j in range(1, 7)])
        actual_blue = self.dh.data[t]["蓝球"]
        return {
            "issue": self.dh.issues[t],
            "actual_reds": actual_reds,
            "actual_blue": actual_blue,
        }

    def save(self, report, path=None):
        path = path or PREDICT_FILE
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def load_saved(self, path=None):
        path = path or PREDICT_FILE
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
