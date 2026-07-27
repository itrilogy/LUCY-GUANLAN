#!/usr/bin/env python3
"""
DataHub —— 统一数据入口

整合: 号码特征预计算 + 市场变量 + 号码画像 + SQLite查询
首次启动自动从 JSON 迁移到 SQLite。
"""

import json, math, os, sqlite3
import numpy as np
from collections import Counter

from config import SSQ_FILE, DATA_DIR

DB_FILE = os.path.join(DATA_DIR, "ssq.db")


def _auto_migrate():
    """自动迁移 JSON → SQLite + 建表（首次运行时）"""
    if not os.path.exists(DB_FILE):
        from scripts.init_db import migrate
        migrate()
    else:
        # 确保预测表存在（增量迁移）
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predict_batch (
                    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    target_issue TEXT NOT NULL,
                    total_entries INT DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INT NOT NULL REFERENCES predict_batch(batch_id),
                    saved_at TEXT NOT NULL DEFAULT (datetime('now')),
                    target_issue TEXT NOT NULL,
                    entry_type TEXT NOT NULL DEFAULT 'single',
                    rank INT NOT NULL,
                    reds TEXT NOT NULL,
                    blue INT,
                    reds_count INT DEFAULT 6,
                    blues_count INT DEFAULT 1,
                    consistency REAL,
                    cost REAL,
                    total_cost INT DEFAULT 0,
                    total_combos INT DEFAULT 0,
                    est_prize1 INT,
                    actual INT DEFAULT NULL,
                    hit_red INT DEFAULT NULL,
                    hit_blue INT DEFAULT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_batch ON predictions(batch_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_target ON predictions(target_issue)")
            conn.commit()
            conn.close()
        except:
            pass


class DataHub:
    """单例数据入口，提供所有预计算特征 + SQLite查询"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance
    
    def load(self, path=None):
        """加载数据并预计算所有特征"""
        if self._loaded:
            return self
        
        path = path or SSQ_FILE
        with open(path) as f:
            data = json.load(f)
        data.sort(key=lambda r: int(r["期号"]))
        self.data = data
        self.N = len(data)
        
        # 自动迁移到 SQLite（首次）
        _auto_migrate()
        self._db = None
        
        self._build_red_features()
        self._build_market_vars()
        self._build_profiles()
        
        self._loaded = True
        # 预计算蓝球遗漏
        self._blue_miss = np.zeros((16, self.N), dtype=int)
        last_blue = np.zeros(16, dtype=int)
        for t in range(self.N):
            blue = self.data[t]["蓝球"]
            last_blue[blue-1] = t
            for num in range(1, 17):
                self._blue_miss[num-1, t] = t - last_blue[num-1]
        return self
    
    # ── SQLite 查询接口 ────────────────────────────────────────
    
    @property
    def db(self):
        if self._db is None:
            if os.path.exists(DB_FILE):
                self._db = sqlite3.connect(DB_FILE, check_same_thread=False)
                self._db.row_factory = sqlite3.Row
        return self._db
    
    def db_query(self, sql, params=()):
        """执行 SQL 并返回所有行"""
        if not self.db:
            return []
        if sql.strip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE')):
            self.db.execute(sql, params)
            self.db.commit()
            return []
        return self.db.execute(sql, params).fetchall()
    
    def db_query_one(self, sql, params=()):
        """执行 SQL 返回第一行"""
        rows = self.db_query(sql, params)
        return rows[0] if rows else None
    
    def db_close(self):
        if self._db:
            self._db.close()
            self._db = None
    
    # ── 内部构建方法 ──────────────────────────────────────────
    
    def _build_red_features(self):
        """33个号码 × N期 × 8维特征"""
        N, D = self.N, self.data
        self.red_feat = np.zeros((33, N, 8))
        last_at = np.zeros(33, dtype=int)
        pools = np.array([r["奖池奖金"] for r in D], dtype=float)
        pool_bins = np.percentile(pools, [0, 30, 60, 90, 100])
        pool_corr = np.zeros((33, 4))
        for num in range(1, 34):
            for b in range(4):
                lo, hi = pool_bins[b], pool_bins[b+1]
                mask = (pools >= lo) & (pools < hi)
                cnt = sum(1 for t in range(N) if mask[t] and any(D[t][f"红球{j}"]==num for j in range(1,7)))
                pool_corr[num-1, b] = cnt / max(1, sum(mask))
        inherit = np.zeros(33)
        for t in range(1, N):
            prev = set(D[t-1][f"红球{j}"] for j in range(1,7))
            curr = set(D[t][f"红球{j}"] for j in range(1,7))
            for num in prev & curr:
                inherit[num-1] += 1
        inherit /= max(1, N-1)
        for t in range(N):
            reds = set(D[t][f"红球{j}"] for j in range(1,7))
            for num in range(1, 34):
                hit = 1 if num in reds else 0
                if hit: last_at[num-1] = t
                miss = t - last_at[num-1]
                s10=max(0,t-10); f10=sum(1 for s in range(s10,t+1) if any(D[s][f"红球{j}"]==num for j in range(1,7)))
                s20=max(0,t-20); f20=sum(1 for s in range(s20,t+1) if any(D[s][f"红球{j}"]==num for j in range(1,7)))
                s50=max(0,t-50); f50=sum(1 for s in range(s50,t+1) if any(D[s][f"红球{j}"]==num for j in range(1,7)))
                trend = miss - (t-1 - last_at[num-1]) if t > 0 else 0
                pb = min(3, max(0, np.searchsorted(pool_bins, pools[t]) - 1))
                self.red_feat[num-1, t] = [miss, f10, f20, f50, trend, pool_corr[num-1, pb], inherit[num-1], miss / max(1, t+1)]
    
    def _build_market_vars(self):
        """市场变量 [N, 14]"""
        N = self.N
        self.pool = np.array([r["奖池奖金"] for r in self.data], dtype=float)
        self.bet = np.array([r["总投注额"] for r in self.data], dtype=float)
        self.p1c = np.array([r["一等奖注数"] for r in self.data], dtype=float)
        self.p1a = np.array([r["一等奖奖金"] for r in self.data], dtype=float)
        self.p2c = np.array([r["二等奖注数"] for r in self.data], dtype=float)
        self.p2a = np.array([r["二等奖奖金"] for r in self.data], dtype=float)
        self.issues = [r["期号"] for r in self.data]
        self.dates = [r["开奖日期"] for r in self.data]
        prize1_total = self.p1c * self.p1a
        prize2_total = self.p2c * self.p2a
        major_ratio = np.zeros(N); mask = self.bet > 0
        major_ratio[mask] = (prize1_total[mask] + prize2_total[mask]) / self.bet[mask] * 100
        pool_bet_ratio = np.zeros(N); pool_bet_ratio[mask] = self.pool[mask] / self.bet[mask]
        bet_elasticity = np.zeros(N); bet_elasticity[1:] = self.bet[1:] / (self.pool[:-1] + 1) * 100
        span_arr=np.zeros(N); sum_arr=np.zeros(N); small_arr=np.zeros(N); cons_arr=np.zeros(N)
        for t in range(N):
            reds=sorted([self.data[t][f"红球{j}"] for j in range(1,7)]); s=sum(reds)
            span_arr[t]=reds[-1]-reds[0]; sum_arr[t]=s
            small_arr[t]=sum(1 for x in reds if x<=14)
            cons_arr[t]=sum(1 for j in range(5) if reds[j+1]-reds[j]==1)
        self.market = np.column_stack([self.pool/1e8, self.bet/1e8, self.p1c, self.p1a/1e4,
            self.p2c, self.p2a/1e4, prize1_total/1e8, major_ratio, pool_bet_ratio,
            bet_elasticity, span_arr, sum_arr, small_arr, cons_arr])
    
    def _build_profiles(self):
        """号码画像"""
        from collections import Counter
        self.profiles = []
        for t in range(self.N):
            d=self.data[t]; reds=sorted([d[f"红球{j}"] for j in range(1,7)])
            prime_set={2,3,5,7,11,13,17,19,23,29,31}
            self.profiles.append({
                'span':reds[-1]-reds[0],'sum':sum(reds),
                'odd':sum(1 for x in reds if x%2==1),
                'cons':sum(1 for j in range(5) if reds[j+1]-reds[j]==1),
                'z1':sum(1 for x in reds if 1<=x<=11),
                'z2':sum(1 for x in reds if 12<=x<=22),
                'z3':sum(1 for x in reds if 23<=x<=33),
                'bday':sum(1 for x in reds if 1<=x<=31),
                'non_bday':sum(1 for x in reds if 32<=x<=33),
                'prime':sum(1 for x in reds if x in prime_set),
                'same_tail':len(set(x%10 for x in reds)),
                'blue':d["蓝球"],
            })
    
    # ── 便捷查询接口 ──────────────────────────────────────────
    
    def get_red_features(self, t):
        """返回 [33, 8]"""
        return self.red_feat[:, t, :]
    
    def get_blue_features(self, t):
        """返回 [16, 4] 蓝球特征"""
        bf = np.zeros((16, 4))
        for num in range(1, 17):
            bf[num-1, 0] = self._blue_miss[num-1, t] if hasattr(self, '_blue_miss') else t
            appearances = sum(1 for s in range(max(0,t-10), t+1) if self.data[s]["蓝球"] == num)
            bf[num-1, 1] = appearances
            if t > 0:
                bf[num-1, 2] = self._blue_miss[num-1, t] - self._blue_miss[num-1, t-1] if hasattr(self, '_blue_miss') else 0
            bf[num-1, 3] = bf[num-1, 0] / max(1, t+1)
        return bf
    
    def get_market_state(self, t):
        """返回 [14] 市场状态向量"""
        return self.market[t]
    
    def get_profile(self, t):
        """返回dict"""
        return self.profiles[t]
    
    def pool_state(self, t):
        """0=枯竭~4=超高"""
        p = self.pool[t]
        if p < 5e6: return 0
        if p < 2e8: return 1
        if p < 1e9: return 2
        if p < 2e9: return 3
        return 4
    
    def pool_state_name(self, t):
        return ["枯竭","低位","正常","高位","超高"][self.pool_state(t)]
    
    def append_new(self, row_dict):
        self.data.append(row_dict)
        self._loaded = False
        self.load()
    
    @property
    def latest_t(self):
        return self.N - 1
    
    @property
    def latest_issue(self):
        return self.issues[-1]
    
    @property
    def next_issue(self):
        """推算下一期期号（格式: 年年期期期）"""
        last = self.issues[-1]
        year = int(last[:2])
        seq = int(last[2:]) + 1
        if seq > 999:
            year += 1
            seq = 1
        return f"{year:02d}{seq:03d}"