#!/usr/bin/env python3
"""
双向验证器 —— 前向推演 + 反向校验 + 一致性评分

核心循环:
  前向: 当前市场状态 + 候选号码 → 预期头奖注数
  反向: 预期头奖注数 → 反推最可能的市场状态
  评分: 前向假设 vs 反向推得 → 一致性分数

来源: ssq_bidirectional.py BackwardValidator
      ssq_zone_predictor.py 互逆逻辑
"""

import numpy as np
from collections import Counter


class Validator:
    """双向验证器"""
    
    def __init__(self, dh, mm, nm):
        self.dh = dh
        self.mm = mm
        self.nm = nm
        self.N = dh.N
    
    # ── 前向通道 ───────────────────────────────────────────
    
    def forward(self, reds, bet_amount=None):
        """
        前向: 给定号码组合 → 估算头奖注数
        
        方法: 用成本模型估算
        """
        if bet_amount is None:
            bet_amount = self.dh.bet[self.dh.latest_t]
        return self.nm.estimate_prize1(reds, bet_amount)
    
    # ── 反向通道 ───────────────────────────────────────────
    
    def backward(self, prize1_count, top_k=20):
        """
        反向: 给定头奖注数 → 反推"开奖前的市场状态"
        
        使用 SQLite 索引加速 (O(log N))，与原始逻辑完全等价。
        """
        # 用 SQLite 索引查询最近的头奖注数
        rows = self.dh.db_query(
            "SELECT id, prize1_cnt FROM draws ORDER BY ABS(prize1_cnt - ?) LIMIT ?",
            (int(prize1_count), top_k)
        )
        ids = [r[0] for r in rows]
        if not ids:
            return None
        
        # 这些期的开奖前市场状态
        states = []
        for id_val in ids:
            if id_val > 1:  # 有前一期
                prev = self.dh.db_query_one("SELECT pool, bet FROM draws WHERE id=?", (id_val - 1,))
                if prev:
                    t = id_val - 1  # 0-indexed for numpy arrays
                    if t < self.dh.N and t >= 0:
                        states.append({
                            'pool_before': float(prev[0]),
                            'bet_before': float(prev[1]),
                            'regime': int(self.mm._regime_labels[t]),
                            'pool_state': self.mm.get_pool_state(t),
                        })
        
        if not states:
            return None
        
        # 统计Regime分布
        regime_counts = Counter(s['regime'] for s in states)
        total = len(states)
        
        return {
            'regime_dist': {k: v/total for k, v in regime_counts.items()},
            'most_likely_regime': max(regime_counts, key=regime_counts.get),
            'avg_pool_before': float(np.mean([s['pool_before'] for s in states])),
            'avg_bet_before': float(np.mean([s['bet_before'] for s in states])),
            'pool_state_dist': Counter(s['pool_state'] for s in states),
            'n_samples': total,
        }
    
    # ── 一致性评分 ─────────────────────────────────────────
    
    def consistency_score(self, reds, current_regime=None, bet_amount=None):
        """
        对一个号码组合运行完整的前向→反向→评分循环。
        
        返回 0~1 的分数, 越高越自洽。
        """
        if current_regime is None:
            current_regime = self.mm.get_regime()
        if bet_amount is None:
            bet_amount = self.dh.bet[self.dh.latest_t]
        
        # 前向: 号码 → 头奖注数
        est_prize = self.forward(reds, bet_amount)
        
        # 反向: 头奖注数 → 市场Regime
        back_result = self.backward(est_prize)
        
        if back_result is None:
            return 0.0
        
        # 反向结果中, 当前Regime的概率有多高?
        regime_prob = back_result['regime_dist'].get(current_regime, 0)
        
        # 如果反向推得的Regime与当前一致 → 高评分
        # 也奖励反向结果中Regime分布集中的情况
        regime_entropy = -sum(p * np.log(p + 1e-10) 
                              for p in back_result['regime_dist'].values())
        max_entropy = np.log(len(back_result['regime_dist']))
        concentration = 1 - regime_entropy / max_entropy if max_entropy > 0 else 1
        
        score = regime_prob * 0.7 + concentration * 0.3
        return min(1.0, max(0.0, score))
    
    # ── 批量验证 ───────────────────────────────────────────
    
    def batch_validate(self, candidates):
        """对批量候选号码运行验证, 返回排序后的结果"""
        current_regime = self.mm.get_regime()
        bet_amount = self.dh.bet[self.dh.latest_t]
        
        # T_bwd: 从当前Regime反推"前一期"应处的Regime (5-class)
        tbd_prior = self.mm.regime_T_bwd[current_regime]
        tbd_top_regime = int(np.argmax(tbd_prior))
        
        results = []
        for reds, blue, cost in candidates:
            score = self.consistency_score(reds, current_regime, bet_amount)
            est_prize = self.forward(reds, bet_amount)
            
            # T_bwd 一致性: 软匹配 (用重叠概率)
            back_result = self.backward(est_prize)
            tbd_bonus = 0.0
            if back_result:
                # 计算 backward 推得的 Regime 分布与 T_bwd 预期分布的相似度
                bwd_total = sum(back_result['regime_dist'].values())
                overlap = 0.0
                for r_k, r_p in back_result['regime_dist'].items():
                    overlap += min(r_p / bwd_total, tbd_prior[int(r_k)])
                tbd_bonus = round(overlap * 0.2, 3)  # 最高+20%
            
            adjusted = min(1.0, score * (1.0 + tbd_bonus))
            results.append({
                'reds': reds,
                'blue': blue,
                'cost': cost,
                'consistency': round(adjusted, 4),
                'raw_consistency': round(score, 4),
                'est_prize1': est_prize,
                'tbd_bonus': round(tbd_bonus, 3),
            })
        
        results.sort(key=lambda x: x['consistency'], reverse=True)
        return results
    
    # ── 历史回测 ───────────────────────────────────────────
    
    def backtest(self, n_test=200):
        """
        历史回测: 用过去 n_test 期做留一法验证。
        检查高评分号码是否更接近实际开奖号码。
        """
        results = []
        for t in range(self.N - n_test, self.N - 1):
            # 模拟在t期时, 预测t+1期
            regime_t = self.mm._regime_labels[t]
            
            # 生成候选
            pool_state = self.mm.get_pool_state(t)
            candidates = self.nm.sample_candidates(200, pool_state)
            
            # 验证
            validated = []
            for reds, blue, cost in candidates:
                score = self.consistency_score(reds, regime_t, self.dh.bet[t])
                validated.append((score, reds, blue))
            
            validated.sort(key=lambda x: x[0], reverse=True)
            
            # 实际号码
            actual_reds = sorted([self.dh.data[t+1][f"红球{j}"] for j in range(1,7)])
            
            # 检查top候选的命中率
            if validated:
                top_reds = validated[0][1]
                hits = len(set(top_reds) & set(actual_reds))
                results.append(hits)
        
        if not results:
            return {'avg_hits': 0, 'hits_list': []}
        
        return {
            'avg_hits': float(np.mean(results)),
            'hits_list': results,
            'vs_random': float(np.mean(results)) / (6 * 6/33),
        }
