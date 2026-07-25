#!/usr/bin/env python3
"""
市场模型 —— Regime 分类 + 反馈回路 + 状态转移

来源: ssq_bettor_behavior.py MarketCycleAnalyzer + FeedbackLoopAnalyzer
      ssq_prob_kernel.py ProbabilisticTransitionKernel
"""

import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.linear_model import LinearRegression
from scipy import stats
from config import POOL_LOW, POOL_HIGH


class MarketModel:
    """市场状态分析与预测"""
    
    def __init__(self, dh):
        self.dh = dh
        self.N = dh.N
        self._build_regime_model()
        self._build_feedback()
        self._build_markov()
    
    # ── Regime 分类 ──────────────────────────────────────────
    
    def _build_regime_model(self):
        """GMM 聚类识别 5 种市场状态"""
        X = np.column_stack([
            np.log10(self.dh.pool + 1),
            np.log10(self.dh.bet + 1),
            np.log10(self.dh.p1c + 1),
        ])
        X = (X - X.mean(0)) / (X.std(0) + 1e-10)
        
        gmm = GaussianMixture(n_components=5, random_state=42, n_init=10)
        self._regime_labels = gmm.fit_predict(X)
        self._regime_model = gmm
        
        # 描述每个 Regime
        self.regime_info = []
        for k in range(gmm.n_components):
            mask = self._regime_labels == k
            self.regime_info.append({
                'label': k,
                'pct': mask.sum() / self.N,
                'avg_pool': float(self.dh.pool[mask].mean() / 1e8),
                'avg_bet': float(self.dh.bet[mask].mean() / 1e8),
                'avg_prize1': float(self.dh.p1c[mask].mean()),
            })
    
    def get_regime(self, t=None):
        """返回 t 期的市场 Regime"""
        if t is None:
            t = self.dh.latest_t
        X = np.log10(np.array([[
            self.dh.pool[t] + 1,
            self.dh.bet[t] + 1,
            self.dh.p1c[t] + 1,
        ]]))
        X = (X - X.mean(0)) / (X.std(0) + 1e-10)
        return int(self._regime_model.predict(X)[0])
    
    def get_pool_state(self, t=None):
        """奖池水位: "蓄水"/"平衡"/"放水" """
        if t is None:
            t = self.dh.latest_t
        p = self.dh.pool[t]
        if p < POOL_LOW:
            return "蓄水"
        elif p > POOL_HIGH:
            return "放水"
        return "平衡"
    
    def get_regime_description(self, t=None):
        """完整的Regime中文描述"""
        if t is None:
            t = self.dh.latest_t
        r = self.get_regime(t)
        info = self.regime_info[r]
        return {
            'regime_id': r,
            'pool_state': self.get_pool_state(t),
            'pool': float(self.dh.pool[t]),
            'bet': float(self.dh.bet[t]),
            'avg_pool': info['avg_pool'],
            'avg_bet': info['avg_bet'],
            'avg_prize1': info['avg_prize1'],
            'probability': info['pct'],
        }
    
    # ── 反馈回路 ─────────────────────────────────────────────
    
    def _build_feedback(self):
        """三大反馈回路的回归系数"""
        N = self.N
        x_pool = np.log10(self.dh.pool[:-1] + 1).reshape(-1, 1)
        y_bet = np.log10(self.dh.bet[1:] + 1)
        self._reg_pool_bet = LinearRegression().fit(x_pool, y_bet)
        
        x_bet = np.log10(self.dh.bet + 1).reshape(-1, 1)
        y_p1c = np.log10(self.dh.p1c + 1)
        self._reg_bet_prize = LinearRegression().fit(x_bet, y_p1c)
    
    def impulse_response(self, pool_shock=1e8):
        """奖池冲击→投注响应"""
        shock_log = np.log10(pool_shock + 1)
        response_log = self._reg_pool_bet.predict([[shock_log]])[0]
        response = 10 ** response_log - 1
        return float(response)
    
    def predict_bet(self, pool):
        """给定奖池，预测投注额"""
        log_pool = np.log10(np.array([[pool + 1]]))
        log_bet = self._reg_pool_bet.predict(log_pool)[0]
        return float(10 ** log_bet - 1)
    
    # ── Markov 转移 ──────────────────────────────────────────
    
    def _build_markov(self, n_states=12):
        """基于 KMeans 的离散状态转移矩阵"""
        from sklearn.cluster import KMeans
        
        # 用市场变量做聚类
        X = self.dh.market
        X_n = (X - X.mean(0)) / (X.std(0) + 1e-10)
        
        km = KMeans(n_clusters=n_states, random_state=42, n_init=20)
        labels = km.fit_predict(X_n)
        
        T = np.zeros((n_states, n_states))
        for t in range(self.N - 1):
            T[labels[t], labels[t+1]] += 1
        row_sum = T.sum(axis=1, keepdims=True) + 1e-10
        self.markov_T = T / row_sum
        self.markov_labels = labels
        self.markov_km = km
    
    def get_markov_state(self, t=None):
        if t is None:
            t = self.dh.latest_t
        return self.markov_labels[t]
    
    def forward_markov(self, state_k, steps=1):
        """前向推演 Markov 链"""
        d = np.zeros(self.markov_T.shape[0])
        d[state_k] = 1.0
        for _ in range(steps):
            d = d @ self.markov_T
        return d
    
    def get_transition_prob(self, from_k, to_k):
        return self.markov_T[from_k, to_k]
