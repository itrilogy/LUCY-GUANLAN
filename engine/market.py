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
        X_raw = np.column_stack([
            np.log10(self.dh.pool + 1),
            np.log10(self.dh.bet + 1),
            np.log10(self.dh.p1c + 1),
        ])
        # 保存训练集标准化参数，供单期推断复用（勿对单样本再求 mean/std）
        self._regime_mean = X_raw.mean(0)
        self._regime_std = X_raw.std(0) + 1e-10
        X = (X_raw - self._regime_mean) / self._regime_std

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
        """返回 t 期的市场 Regime（优先用训练期标签，避免单样本标准化偏差）"""
        if t is None:
            t = self.dh.latest_t
        if 0 <= t < len(self._regime_labels):
            return int(self._regime_labels[t])
        X = np.log10(np.array([[
            self.dh.pool[t] + 1,
            self.dh.bet[t] + 1,
            self.dh.p1c[t] + 1,
        ]]))
        X = (X - self._regime_mean) / self._regime_std
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

    def predict_p1c_from_market(self, bet: float) -> float:
        """市场主通道：投注额 → 期望头奖注数（f_M）"""
        log_p = self._reg_bet_prize.predict([[np.log10(float(bet) + 1)]])[0]
        return float(10 ** log_p - 1)

    # ── Markov 转移 ──────────────────────────────────────────
    
    def _build_markov(self, n_states=12):
        """基于 KMeans 的离散状态转移矩阵（保存标准化参数供 soft 扩展）"""
        from sklearn.cluster import KMeans

        X = self.dh.market
        self._markov_mean = X.mean(0)
        self._markov_std = X.std(0) + 1e-10
        X_n = (X - self._markov_mean) / self._markov_std

        km = KMeans(n_clusters=n_states, random_state=42, n_init=20)
        labels = km.fit_predict(X_n)
        self.markov_labels = labels
        self.markov_km = km
        self._n_markov_states = n_states
        self._rebuild_transition_matrices()

    def _rebuild_transition_matrices(self):
        """从当前 labels 重算 Markov / Regime 转移（O(N)，soft 可用）"""
        n_states = int(getattr(self, "_n_markov_states", 12))
        labels = self.markov_labels
        N = self.N

        T = np.zeros((n_states, n_states))
        for t in range(N - 1):
            T[labels[t], labels[t + 1]] += 1
        row_sum = T.sum(axis=1, keepdims=True) + 1e-10
        self.markov_T = T / row_sum

        pi_matrix = np.ones(n_states) / n_states
        for k in range(n_states):
            pi_matrix[k] = np.sum(labels == k) / max(1, N)
        pi_mat = pi_matrix.reshape(1, -1)
        pi_j_mat = pi_matrix.reshape(-1, 1)
        T_bwd = self.markov_T.T * pi_mat / (pi_j_mat + 1e-10)
        col_sum = T_bwd.sum(axis=0, keepdims=True) + 1e-10
        self.markov_T_bwd = T_bwd / col_sum

        labels_5 = self._regime_labels
        T5 = np.zeros((5, 5))
        for t in range(N - 1):
            T5[labels_5[t], labels_5[t + 1]] += 1
        row_sum5 = T5.sum(axis=1, keepdims=True) + 1e-10
        self.regime_T = T5 / row_sum5

        pi5 = np.array([np.sum(labels_5 == k) for k in range(5)], dtype=float) / max(1, N)
        T5_bwd = self.regime_T.T * pi5.reshape(1, -1) / (pi5.reshape(-1, 1) + 1e-10)
        col5 = T5_bwd.sum(axis=0, keepdims=True) + 1e-10
        self.regime_T_bwd = T5_bwd / col5

    def soft_extend(self, dh):
        """
        进程内 soft：冻结 GMM/KMeans，仅为新增期预测标签并重算转移。
        若期数减少或模型未 fit → 返回 False（调用方应 full 重建）。
        """
        n_old = len(self._regime_labels)
        n_new = dh.N
        if n_new < n_old or self._regime_model is None or self.markov_km is None:
            return False
        self.dh = dh
        self.N = n_new
        if n_new == n_old:
            self._rebuild_transition_matrices()
            return True

        # 新增期：用冻结标准化 + 模型 predict
        new_regimes = []
        new_markov = []
        for t in range(n_old, n_new):
            Xr = np.log10(np.array([[
                dh.pool[t] + 1, dh.bet[t] + 1, dh.p1c[t] + 1,
            ]]))
            Xr = (Xr - self._regime_mean) / self._regime_std
            new_regimes.append(int(self._regime_model.predict(Xr)[0]))

            Xm = dh.market[t:t + 1]
            Xm_n = (Xm - self._markov_mean) / self._markov_std
            new_markov.append(int(self.markov_km.predict(Xm_n)[0]))

        self._regime_labels = np.concatenate([
            self._regime_labels, np.array(new_regimes, dtype=self._regime_labels.dtype)
        ])
        self.markov_labels = np.concatenate([
            self.markov_labels, np.array(new_markov, dtype=self.markov_labels.dtype)
        ])
        # soft 不重拟合反馈回归
        self._rebuild_transition_matrices()
        # 轻量刷新 regime_info 统计
        self.regime_info = []
        for k in range(5):
            mask = self._regime_labels == k
            if mask.sum() == 0:
                self.regime_info.append({
                    "label": k, "pct": 0.0, "avg_pool": 0.0, "avg_bet": 0.0, "avg_prize1": 0.0,
                })
            else:
                self.regime_info.append({
                    "label": k,
                    "pct": float(mask.sum() / self.N),
                    "avg_pool": float(self.dh.pool[mask].mean() / 1e8),
                    "avg_bet": float(self.dh.bet[mask].mean() / 1e8),
                    "avg_prize1": float(self.dh.p1c[mask].mean()),
                })
        return True
    
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
    
    def backward_markov(self, state_k, steps=1):
        """反向回溯 Markov 链 (T_bwd)"""
        d = np.zeros(self.markov_T_bwd.shape[0])
        d[state_k] = 1.0
        for _ in range(steps):
            d = d @ self.markov_T_bwd
        return d
    
    def get_transition_prob(self, from_k, to_k):
        return self.markov_T[from_k, to_k]
