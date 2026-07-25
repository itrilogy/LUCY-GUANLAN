#!/usr/bin/env python3
"""
号码分析 —— 条件分布 + 成本模型 + 候选采样

来源: ssq_zone_predictor.py MarketConditionalModel
      ssq_house_model.py HouseCostModel
      ssq_bettor_behavior.py BehaviorInference
"""

import math, random
import numpy as np
from collections import Counter
from scipy import stats
from sklearn.linear_model import LinearRegression
from config import N_RED, BIRTHDAY_EFFECT, N_CANDIDATES


class NumberModel:
    """号码特征分析 + 成本评分 + 候选生成"""
    
    def __init__(self, dh):
        self.dh = dh
        self.N = dh.N
        self._build_unconditional()
        self._build_cost_model()
    
    # ── 无条件分布 ──────────────────────────────────────────
    
    def _build_unconditional(self):
        """号码特征的长期均值与标准差"""
        self.feat_names = ['span','sum','odd','z1','z2','z3',
                           'bday','cons','prime','same_tail']
        arr = np.array([[p[f] for f in self.feat_names] 
                         for p in self.dh.profiles])
        self.feat_mean = arr.mean(axis=0)
        self.feat_std = arr.std(axis=0)
    
    def get_unconditional_dist(self):
        """返回无条件分布"""
        return {
            name: {
                'mean': self.feat_mean[i],
                'std': self.feat_std[i],
                'ci68': (self.feat_mean[i] - self.feat_std[i],
                         self.feat_mean[i] + self.feat_std[i]),
                'ci95': (self.feat_mean[i] - 2*self.feat_std[i],
                         self.feat_mean[i] + 2*self.feat_std[i]),
            }
            for i, name in enumerate(self.feat_names)
        }
    
    # ── 市场条件微调 ────────────────────────────────────────
    
    def get_conditional_dist(self, pool_state):
        """
        基于奖池状态调整条件分布。
        效应量来自历史分析 (生日号效应 1.16x, 一区偏移等)
        """
        dist = self.get_unconditional_dist()
        
        # 放水期: 提高生日号/小号权重
        if pool_state == "放水":
            dist['bday']['mean'] = min(6, dist['bday']['mean'] + 0.08)
            dist['z1']['mean'] = min(5, dist['z1']['mean'] + 0.05)
        # 蓄水期: 降低生日号权重  
        elif pool_state == "蓄水":
            dist['bday']['mean'] = max(0, dist['bday']['mean'] - 0.08)
            dist['z1']['mean'] = max(0, dist['z1']['mean'] - 0.05)
        
        return dist
    
    # ── 成本评分模型 ────────────────────────────────────────
    
    def _build_cost_model(self):
        """从历史数据拟合成本评分系数"""
        all_costs = []
        all_p1c = []
        
        for t in range(self.N):
            reds = sorted([self.dh.data[t][f"红球{j}"] for j in range(1,7)])
            cost = self._raw_cost_score(reds)
            all_costs.append(cost)
            all_p1c.append(self.dh.p1c[t])
        
        self._all_costs = np.array(all_costs)
        self._all_p1c = np.array(all_p1c)
        
        # 成本→头奖注数的回归
        reg = LinearRegression()
        reg.fit(self._all_costs.reshape(-1, 1), np.log10(self._all_p1c + 1))
        self._cost_to_prize = reg
    
    def _raw_cost_score(self, reds):
        """
        原始成本分: 正=热门(多人买), 负=冷门(少人买)
        """
        span = max(reds) - min(reds)
        bday_cnt = sum(1 for x in reds if 1 <= x <= 31)
        cons = sum(1 for j in range(5) if reds[j+1] - reds[j] == 1)
        big = sum(1 for x in reds if x >= 32)
        
        # 近20期频率
        t = self.dh.latest_t
        recent = 0
        for num in reds:
            freq = sum(1 for s in range(max(0,t-20), t+1) 
                      if any(self.dh.data[s][f"红球{k}"]==num for k in range(1,7)))
            recent += freq / 20
        
        cost = (bday_cnt * 0.3 + (7 - span/5) * 0.15 + 
                cons * 0.2 + recent * 0.2 - big * 0.3)
        return cost
    
    def cost_score(self, reds):
        """公开接口: 返回归一化的成本分"""
        return float(self._raw_cost_score(reds))
    
    def estimate_prize1(self, reds, bet_amount):
        """估算如果开出这组号码的头奖注数"""
        cost = self._raw_cost_score(reds)
        log_p1c = self._cost_to_prize.predict([[cost]])[0]
        p1c = 10 ** log_p1c - 1
        
        # 投注量修正: 投注越多, 头奖越多
        avg_bet = self.dh.bet.mean()
        p1c *= max(0.5, bet_amount / avg_bet)
        
        return max(0, int(p1c))
    
    # ── 候选采样 ────────────────────────────────────────────
    
    def sample_candidates(self, n=N_CANDIDATES, pool_state="平衡"):
        """根据条件分布采样候选号码"""
        dist = self.get_conditional_dist(pool_state)
        candidates = []
        seen = set()
        
        attempts = 0
        while len(candidates) < n and attempts < n * 20:
            attempts += 1
            
            # 从分布采样红球
            reds = self._sample_from_dist(dist)
            if reds is None:
                continue
            
            key = tuple(reds)
            if key in seen:
                continue
            seen.add(key)
            
            blue = random.randint(1, 16)
            cost = self._raw_cost_score(reds)
            candidates.append((reds, blue, cost))
        
        return candidates
    
    def _sample_from_dist(self, dist):
        """从特征分布采样一组红球"""
        target_span = random.gauss(dist['span']['mean'], dist['span']['std'])
        target_sum = random.gauss(dist['sum']['mean'], dist['sum']['std'])
        target_z1 = round(random.gauss(dist['z1']['mean'], dist['z1']['std']))
        target_bday = round(random.gauss(dist['bday']['mean'], dist['bday']['std']))
        
        target_span = max(1, min(32, int(target_span)))
        target_sum = max(21, min(183, int(target_sum)))
        target_z1 = max(0, min(6, target_z1))
        target_bday = max(0, min(6, target_bday))
        
        # 拒绝采样
        for _ in range(500):
            reds = sorted(random.sample(range(1, 34), 6))
            span = reds[-1] - reds[0]
            s = sum(reds)
            z1 = sum(1 for x in reds if 1 <= x <= 11)
            bday = sum(1 for x in reds if 1 <= x <= 31)
            
            if (abs(span - target_span) <= 3 and
                abs(s - target_sum) <= 10 and
                abs(z1 - target_z1) <= 2 and
                bday >= target_bday - 1):
                return reds
        return None
    
    # ── 号码热度分析 ────────────────────────────────────────
    
    def get_popularity_analysis(self, top_n=10):
        """热门号和冷门号分析"""
        t = self.dh.latest_t
        
        hot_scores = []
        for num in range(1, 34):
            feat = self.dh.get_red_features(t)[num-1]
            # 综合热度分
            score = (feat[0] * -0.1 +   # 遗漏少→热
                     feat[1] * 0.5 +    # 近10期频高→热
                     feat[4] * -0.3 +   # 趋势负(变热)→热
                     (0.3 if 1 <= num <= 31 else -0.3))  # 生日号→热
            hot_scores.append((num, score))
        
        hot_scores.sort(key=lambda x: x[1], reverse=True)
        
        return {
            'hot': [num for num, s in hot_scores[:top_n]],
            'cold': [num for num, s in hot_scores[-top_n:]],
            'birthday_effect': BIRTHDAY_EFFECT,
        }


class CompoundBetPlanner:
    """
    合并复式投注规划器 —— 基于全验证池的加权贪心算法。

    核心: 从 Validator 输出的完整候选池 (2000个带一致性评分的组合) 中,
    选择使"加权覆盖率"最大化的红球集合R和蓝球集合B。

    加权覆盖率 = Σ consistency(c) for c where c.reds ⊆ R AND c.blue ∈ B

    算法: 贪心边际增益 (每次选 gain/cost 比率最高的球)

    复式自身也过双向验证:
      复式整体头奖 ≈ mean(forward(c)) for c ⊆ R×B
      复式一致性 = backward(整体头奖) 与当前Regime的匹配度
    """

    # 三档预设: (红球数, 蓝球数, 名称, 描述)
    TIERS = [
        (8, 1, "经济型", "56元 (28注)"),
        (9, 1, "标准型", "168元 (84注)"),
        (10, 2, "豪华型", "840元 (420注)"),
    ]

    def __init__(self, validator, number_model):
        self.validator = validator
        self.nm = number_model
        self.dh = validator.dh
        self.mm = validator.mm

    def build_from_candidates(self, candidates, max_red=10, max_blue=2):
        """
        从候选池构建最优复式。返回结果包含构建轨迹。
        """
        # ... same coverage_score logic ...
        def coverage_score(c_idx, R, B):
            c = candidates[c_idx]
            match = sum(1 for r in c['reds'] if r in R)
            ratio = match / 6.0
            blue_ok = (not B) or (c['blue'] in B)
            return c['consistency'] * ratio if blue_ok else 0.0

        red_to_cands = {num: [] for num in range(1, 34)}
        for idx, c in enumerate(candidates):
            for r in c['reds']:
                red_to_cands[r].append(idx)

        red_weight = {num: sum(candidates[i]['consistency'] for i in lst)
                      for num, lst in red_to_cands.items()}
        sorted_reds = sorted(red_weight.keys(), key=lambda n: -red_weight[n])

        blue_weight = {b: sum(c['consistency'] for c in candidates if c['blue'] == b)
                       for b in range(1, 17)}
        selected_blues = {max(blue_weight, key=blue_weight.get)}
        selected_reds = set(sorted_reds[:6])

        # 构建轨迹
        steps = []
        all_score = sum(c['consistency'] for c in candidates)

        def current_cov(R, B):
            return sum(coverage_score(i, R, B) for i in range(len(candidates)))

        init_cov = current_cov(selected_reds, selected_blues)
        steps.append({
            'step': len(steps),
            'action': '基底',
            'ball': None,
            'reds_count': len(selected_reds),
            'coverage': round(init_cov / all_score, 4) if all_score > 0 else 0,
            'cumulative_gain': 0,
        })

        # 贪心扩展红球
        for _ in range(len(selected_reds), max_red):
            best_gain, best_r = 0, None
            current = current_cov(selected_reds, selected_blues)
            for r in sorted_reds:
                if r in selected_reds: continue
                R_new = selected_reds | {r}
                new_cov = current_cov(R_new, selected_blues)
                gain = new_cov - current
                if gain > best_gain:
                    best_gain, best_r = gain, r
            if best_r is None or best_gain <= 0: break
            selected_reds.add(best_r)
            new_cov = current_cov(selected_reds, selected_blues)
            steps.append({
                'step': len(steps),
                'action': '加红球',
                'ball': best_r,
                'reds_count': len(selected_reds),
                'coverage': round(new_cov / all_score, 4) if all_score > 0 else 0,
                'gain': round(best_gain, 4),
                'cumulative_gain': round(new_cov - init_cov, 4) if all_score > 0 else 0,
            })

        # 蓝球扩展
        for step in range(1, max_blue):
            best_gain, best_b = 0, None
            current = current_cov(selected_reds, selected_blues)
            for b in range(1, 17):
                if b in selected_blues: continue
                B_new = selected_blues | {b}
                new_cov = current_cov(selected_reds, B_new)
                gain = new_cov - current
                if gain > best_gain:
                    best_gain, best_b = gain, b
            if best_b is None or best_gain <= 0: break
            selected_blues.add(best_b)
            new_cov = current_cov(selected_reds, selected_blues)
            steps.append({
                'step': len(steps),
                'action': '加蓝球',
                'ball': best_b,
                'reds_count': len(selected_reds),
                'blues_count': len(selected_blues),
                'coverage': round(new_cov / all_score, 4) if all_score > 0 else 0,
                'gain': round(best_gain, 4),
            })

        total_combos = math.comb(len(selected_reds), 6) * len(selected_blues)
        total_cost = total_combos * 2
        final_cov = current_cov(selected_reds, selected_blues)
        compound_consistency = self._compound_validation(
            list(selected_reds), list(selected_blues), candidates)

        return {
            'reds': sorted(selected_reds),
            'blues': sorted(selected_blues),
            'total_combos': total_combos,
            'total_cost': total_cost,
            'weighted_score': round(final_cov, 2),
            'coverage_rate': round(final_cov / all_score, 4) if all_score > 0 else 0,
            'consistency': round(compound_consistency, 4),
            'avg_match_rate': round(final_cov / all_score, 4) if all_score > 0 else 0,
            'build_steps': steps,
        }

    def _compound_validation(self, reds, blues, candidates):
        """
        复式级双向验证。

        前向: 复式整体预期头奖 = mean(forward(c)) for c ⊆ R×B
        反向: 从预期头奖反推Regime
        一致性: 当前Regime在反向分布中的概率
        """
        current_regime = self.mm.get_regime()

        # 找出被复式覆盖的候选
        red_set, blue_set = set(reds), set(blues)
        covered = [c for c in candidates
                   if set(c['reds']).issubset(red_set) and c['blue'] in blue_set]

        if not covered:
            return 0.3  # 默认中等评分

        # 前向: 平均预期头奖
        avg_est_prize = int(np.mean([c.get('est_prize1', 5) for c in covered]))

        # 反向: 从预期头奖推Regime
        back_result = self.validator.backward(avg_est_prize, top_k=30)
        if back_result is None:
            return 0.3

        regime_prob = back_result['regime_dist'].get(current_regime, 0)

        # 浓度: 反向Regime分布的集中程度
        regime_entropy = -sum(p * math.log(p + 1e-10) for p in back_result['regime_dist'].values())
        max_entropy = math.log(max(1, len(back_result['regime_dist'])))
        concentration = 1 - regime_entropy / max_entropy if max_entropy > 0 else 1

        score = regime_prob * 0.7 + concentration * 0.3
        return min(1.0, max(0.0, score))

    def build_tiers(self, candidates):
        """返回三档预设方案"""
        results = []
        for n_red, n_blue, name, desc in self.TIERS:
            plan = self.build_from_candidates(candidates, max_red=n_red, max_blue=n_blue)
            plan['tier_name'] = name
            plan['tier_desc'] = desc
            results.append(plan)
        return results
