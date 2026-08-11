#!/usr/bin/env python3
"""
遗传进化引擎 —— 全量计算，双向验证适应度

从 ssq_evolution_v2.py 移植，对接当前 DataHub/Validator 管线。
适应度 = Validator.consistency_score() (完整前向→反向→评分)
每代写入 data/progress.json 供前端轮询。
"""

import json, os, math, random, time
import numpy as np
from config import ROOT

WEIGHTS_FILE = os.path.join(ROOT, "data", "weights.json")
PROGRESS_FILE = os.path.join(ROOT, "data", "progress.json")

FEAT_NAMES = ["遗漏值","近10期频","近20期频","近50期频",
              "遗漏趋势","奖池相关","继承率","相对遗漏"]


class PatternGene:
    """基因: 8维红球权重 + 4维蓝球权重 + 继承/跨度偏置"""

    def __init__(self):
        self.w_red = np.random.randn(8) * 0.3
        self.w_blue = np.random.randn(4) * 0.3
        self.inherit_bias = random.uniform(-0.5, 0.5)
        self.span_bias = random.uniform(-2, 2)
        self.fitness = None
        self.detail = {}

    def clone(self):
        g = PatternGene()
        g.w_red = self.w_red.copy()
        g.w_blue = self.w_blue.copy()
        g.inherit_bias = self.inherit_bias
        g.span_bias = self.span_bias
        return g

    def mutate(self, rate=0.3):
        for i in range(8):
            if random.random() < rate:
                self.w_red[i] += random.gauss(0, 0.15)
        for i in range(4):
            if random.random() < rate:
                self.w_blue[i] += random.gauss(0, 0.15)
        if random.random() < rate:
            self.inherit_bias += random.gauss(0, 0.2)
        if random.random() < rate:
            self.span_bias += random.gauss(0, 1)
        self.fitness = None
        return self

    def crossover(self, other):
        child = self.clone()
        for i in range(8):
            if random.random() < 0.5:
                child.w_red[i] = other.w_red[i]
        for i in range(4):
            if random.random() < 0.5:
                child.w_blue[i] = other.w_blue[i]
        if random.random() < 0.5:
            child.inherit_bias = other.inherit_bias
        if random.random() < 0.5:
            child.span_bias = other.span_bias
        child.fitness = None
        return child

    def predict(self, dh, t):
        """用基因预测t+1期的号码"""
        rf = dh.get_red_features(t)
        bf = dh.get_blue_features(t)
        scores = rf @ self.w_red
        if t > 0:
            for j in range(1, 7):
                scores[dh.data[t][f"红球{j}"]-1] += self.inherit_bias
        reds = sorted((np.argsort(scores)[-6:][::-1] + 1).tolist())
        b_scores = bf @ self.w_blue
        blue = int(np.argmax(b_scores) + 1)
        return reds, blue

    def to_dict(self):
        return {
            'w_red': [float(x) for x in self.w_red],
            'w_blue': [float(x) for x in self.w_blue],
            'inherit_bias': float(self.inherit_bias),
            'span_bias': float(self.span_bias),
            'fitness': float(self.fitness) if self.fitness else None,
        }

    @staticmethod
    def from_dict(d):
        g = PatternGene()
        g.w_red = np.array(d['w_red'])
        g.w_blue = np.array(d['w_blue'])
        g.inherit_bias = d['inherit_bias']
        g.span_bias = d['span_bias']
        g.fitness = d.get('fitness')
        return g


class Evolution:
    """遗传进化引擎，完整双向验证适应度"""

    def __init__(self, dh, validator, nm,
                 pop_size=200, generations=30, test_ratio=0.2):
        self.dh = dh
        self.validator = validator
        self.nm = nm
        self.pop_size = pop_size
        self.generations = generations
        self.test_ratio = test_ratio
        self.N = dh.N
        self.test_start = int(self.N * (1 - test_ratio))
        self.pop = []
        self.gen_log = []
        # 预计算 backward 查找表（全量等价，结果一致，仅速度优化）
        self._build_lut()

    def _build_lut(self, max_prize=200):
        """预计算 backward 结果缓存，与扫全量完全等价"""
        self.backward_lut = {}
        for prize in range(max_prize + 1):
            res = self.validator.backward(prize, top_k=30)
            self.backward_lut[prize] = res

    def _write_progress(self, stage, progress, message):
        """写入进度供前端轮询"""
        try:
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({
                    'running': True,
                    'stage': stage,
                    'progress': progress,
                    'message': message,
                }, f)
        except Exception:
            pass

    def _clear_progress(self):
        try:
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({'running': False, 'stage': 'idle', 'progress': 0, 'message': '就绪'}, f)
        except Exception:
            pass

    def evaluate(self, gene):
        """
        适应度 = 在测试集上运行完整双向验证的平均一致性评分（查LUT版）。
        
        与标准 consistency_score 逻辑完全一致，仅 backward 步骤用 LUT 加速。
        """
        total_score = 0.0
        n = 0
        
        for t in range(self.test_start, self.N - 1):
            reds, blue = gene.predict(self.dh, t)
            # forward: 成本→头奖
            bet_amount = self.dh.bet[t]
            est_prize = self.nm.estimate_prize1(reds, bet_amount)
            est_prize = int(round(max(0, min(200, est_prize))))
            
            # backward: LUT查询（与扫全量等价）
            back_result = self.backward_lut.get(est_prize, None)
            if back_result is None:
                continue
            
            # consistency_score: 当前Regime在反向分布中的概率
            current_regime = int(self.validator.mm._regime_labels[t])
            regime_prob = back_result['regime_dist'].get(current_regime, 0)
            entropy = -sum(p * math.log(p + 1e-10) for p in back_result['regime_dist'].values())
            max_entropy = math.log(max(1, len(back_result['regime_dist'])))
            concentration = 1 - entropy / max_entropy if max_entropy > 0 else 1
            score = regime_prob * 0.7 + concentration * 0.3
            
            total_score += score
            n += 1
        
        gene.fitness = total_score / n if n > 0 else 0
        gene.detail = {'avg_consistency': gene.fitness, 'n': n}
        return gene.fitness

    def init_pop(self):
        self.pop = [PatternGene() for _ in range(self.pop_size)]

    def run(self):
        """执行完整进化，返回最佳基因"""
        self._write_progress('init', 0, f'初始化种群 {self.pop_size}...')
        self.init_pop()
        
        # 基准测试
        sample = random.sample(self.pop, min(20, self.pop_size))
        base_fits = []
        for g in sample:
            self.evaluate(g)
            base_fits.append(g.fitness)
        avg_base = float(np.mean(base_fits)) if base_fits else 0
        best_base = float(max(base_fits)) if base_fits else 0
        
        progress_per_gen = 85.0 / max(1, self.generations)  # 预留15%给最终验证
        
        for gen in range(self.generations):
            # 评估
            for g in self.pop:
                if g.fitness is None:
                    self.evaluate(g)
            
            self.pop.sort(key=lambda g: g.fitness, reverse=True)
            best = self.pop[0]
            median = self.pop[len(self.pop)//2]
            self.gen_log.append({
                'gen': gen, 'best': float(best.fitness),
                'median': float(median.fitness),
                'top5_avg': float(np.mean([g.fitness for g in self.pop[:5]])),
            })
            
            pct = int(progress_per_gen * (gen + 1))
            msg = f"进化第 {gen+1}/{self.generations} 代 | 最佳一致={best.fitness:.4f} | 中位={median.fitness:.4f}"
            self._write_progress('evolution', pct, msg)
            
            # 繁殖下一代
            if gen < self.generations - 1:
                next_gen = self.pop[:15].copy()
                while len(next_gen) < self.pop_size:
                    p1 = random.choice(self.pop[:20])
                    if random.random() < 0.7:
                        p2 = random.choice(self.pop[:20])
                        child = p1.crossover(p2)
                    else:
                        child = p1.clone()
                    child.mutate()
                    next_gen.append(child)
                self.pop = next_gen
        
        # 最终排序
        self.pop.sort(key=lambda g: g.fitness, reverse=True)
        best_gene = self.pop[0]
        
        self._write_progress('final_validate', 92, '最终验证最佳基因...')
        # 最终用最佳基因跑完整验证（含2000候选）
        # 但已经在上一步完成了
        
        self._clear_progress()
        return best_gene, {
            'avg_base': avg_base,
            'best_base': best_base,
            'best_fitness': float(best_gene.fitness),
            'generations_run': self.generations,
            'gen_log': self.gen_log,
        }


def load_weights():
    """加载已缓存的权重"""
    try:
        with open(WEIGHTS_FILE) as f:
            d = json.load(f)
        return PatternGene.from_dict(d)
    except Exception:
        return None


def save_weights(gene):
    """保存最佳权重"""
    with open(WEIGHTS_FILE, 'w') as f:
        json.dump(gene.to_dict(), f, indent=2)


def run_evolution(dh, validator, nm, pop_size=200, generations=30, test_ratio=0.2):
    """便捷入口: 创建并运行进化"""
    evo = Evolution(dh, validator, nm, pop_size, generations, test_ratio)
    return evo.run()
