#!/usr/bin/env python3
"""
预测引擎 —— 整合所有模块的编排层

流程:
  市场状态 → 候选采样 → 双向验证 → 排序 → 报告
"""

import json, time, os
import numpy as np
from config import PREDICT_FILE, TOP_N
from engine.numbers import CompoundBetPlanner
from engine.evolution import Evolution, save_weights, load_weights, WEIGHTS_FILE
import json


def write_progress(stage, pct, msg):
    """写入进度供前端轮询"""
    try:
        with open(WEIGHTS_FILE.replace('weights.json', 'progress.json'), 'w') as f:
            json.dump({'running': True, 'stage': stage, 'progress': pct, 'message': msg}, f)
    except: pass

def clear_progress():
    try:
        with open(WEIGHTS_FILE.replace('weights.json', 'progress.json'), 'w') as f:
            json.dump({'running': False, 'stage': 'idle', 'progress': 0, 'message': '就绪'}, f)
    except: pass


def clear_progress():
    try:
        with open(WEIGHTS_FILE.replace('weights.json', 'progress.json'), 'w') as f:
            json.dump({'running': False, 'stage': 'idle', 'progress': 0, 'message': '就绪'}, f)
    except: pass


class Predictor:
    
    def __init__(self, dh, mm, nm, validator):
        self.dh = dh
        self.mm = mm
        self.nm = nm
        self.validator = validator
        self.bp = CompoundBetPlanner(validator, nm)
    
    def run(self, n_candidates=2000, evolve=False):
        """运行完整预测流程"""
        t0 = time.time()
        
        # 0. 如果启用进化，先跑遗传进化
        if evolve:
            write_progress('evolution', 2, '初始化遗传进化引擎...')
            evo = Evolution(self.dh, self.validator, self.nm)
            best_gene, _ = evo.run()
            save_weights(best_gene)
            write_progress('sampling', 88, '进化完成，进入采样验证...')
        else:
            write_progress('sampling', 2, '使用缓存权重预测...')
        
        # 1. 市场状态
        regime_desc = self.mm.get_regime_description()
        pool_state = regime_desc['pool_state']
        
        # 2. 候选采样
        write_progress('sampling', 3, '采样候选号码...')
        candidates = self.nm.sample_candidates(n_candidates, pool_state)
        
        # 3. 双向验证
        write_progress('validating', 5, f'双向验证 {n_candidates} 候选...')
        validated = self.validator.batch_validate(candidates)
        
        # 4. 复式规划
        write_progress('compound', 92, '规划复式方案...')
        compound_plans = self.bp.build_tiers(validated)
        
        # 5. 排序
        top = validated[:TOP_N]
        
        # 6. 基于top-10推荐的高频复式 (不含11-12注)
        from collections import Counter
        freq_reds = Counter()
        freq_blues = Counter()
        for r in top:
            for n in r['reds']: freq_reds[n] += 1
            freq_blues[r['blue']] += 1
        top10_reds = sorted([n for n, _ in freq_reds.most_common(10)])
        top2_blues = sorted([n for n, _ in freq_blues.most_common(2)])
        combo_cnt2 = __import__('math').comb(len(top10_reds), 6) * len(top2_blues)
        cost_yuan2 = combo_cnt2 * 2
        freq_compound = {
            'tier_name': '高频聚合', 'tier_desc': f'{combo_cnt2}注={cost_yuan2}元',
            'reds': top10_reds, 'blues': top2_blues,
            'total_combos': combo_cnt2, 'total_cost': cost_yuan2,
            'avg_match_rate': round(len(set(top10_reds) & set(n for r in top for n in r['reds'])) / 60, 4),
            'consistency': round(sum(r['consistency'] for r in top) / len(top), 4),
        }
        compound_plans.append(freq_compound)
        
        # 7. 生成报告
        write_progress('report', 97, '生成报告...')
        report = self._build_report(regime_desc, top, candidates, t0, compound_plans)
        clear_progress()
        return report
    
    def _build_report(self, regime_desc, top, all_candidates, t0, compound_plans=None):
        """构建结构化报告"""
        elapsed = time.time() - t0
        
        # 最近一期回顾 (如果有)
        last_review = self._last_review()
        
        # 号码热度
        popularity = self.nm.get_popularity_analysis()
        
        # 奖池预测
        current_pool = regime_desc['pool']
        predicted_bet = self.mm.predict_bet(current_pool)
        
        # 下期奖池估算 (粗略)
        avg_prize_pct = 0.3  # 一二等奖平均占投注的30%
        predicted_pool = current_pool + predicted_bet * 0.49 - predicted_bet * avg_prize_pct
        
        predictions = []
        for i, r in enumerate(top):
            predictions.append({
                'rank': i + 1,
                'reds': [int(x) for x in r['reds']],
                'blue': int(r['blue']),
                'consistency': round(r['consistency'], 4),
                'cost': round(r['cost'], 2),
                'est_prize1': r['est_prize1'],
                'passed': bool(r['consistency'] > 0.2),
            })
        
        return {
            'update_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'current_issue': self.dh.next_issue,
            'elapsed': round(elapsed, 1),
            
            'market': {
                'regime': regime_desc['pool_state'],
                'regime_id': regime_desc['regime_id'],
                'pool': int(current_pool),
                'bet': int(regime_desc['bet']),
                'predicted_pool_range': [
                    int(current_pool * 0.9),
                    int(current_pool * 1.1)
                ],
                'predicted_bet_range': [
                    int(predicted_bet * 0.9),
                    int(predicted_bet * 1.1)
                ],
            },
            
            'predictions': predictions,
            
            'popularity': {
                'hot': popularity['hot'],
                'cold': popularity['cold'],
                'birthday_effect': popularity['birthday_effect'],
            },
            
            'last_review': last_review,
            
            'compound_plans': compound_plans or [],
            
            'stats': {
                'total_candidates': len(all_candidates),
                'top_score': predictions[0]['consistency'] if predictions else 0,
                'avg_score': float(np.mean([p['consistency'] for p in predictions])) if predictions else 0,
            },
        }
    
    def _last_review(self):
        """对比上期预测与实际结果"""
        t = self.dh.latest_t
        if t < 1:
            return None
        
        actual_reds = sorted([self.dh.data[t][f"红球{j}"] for j in range(1,7)])
        actual_blue = self.dh.data[t]["蓝球"]
        
        return {
            'issue': self.dh.issues[t],
            'actual_reds': actual_reds,
            'actual_blue': actual_blue,
        }
    
    def save(self, report):
        """保存预测结果"""
        import numpy as np
        class _Encoder(json.JSONEncoder):
            def default(self, o):
                if isinstance(o, (np.integer,)): return int(o)
                if isinstance(o, (np.floating,)): return float(o)
                if isinstance(o, (np.bool_,)): return bool(o)
                if isinstance(o, np.ndarray): return o.tolist()
                return super().default(o)
        with open(PREDICT_FILE, 'w') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, cls=_Encoder)
    
    def load_saved(self):
        """加载已保存的预测结果"""
        try:
            with open(PREDICT_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
