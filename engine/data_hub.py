#!/usr/bin/env python3
"""
DataHub —— 统一数据入口

整合: 号码特征预计算 + 市场变量 + 号码画像 + SQLite查询
首次启动自动从 JSON 迁移到 SQLite。
支持从 500.com 增量爬取并同步 JSON / SQLite / 内存特征。
"""

import json, os, sqlite3, threading
import numpy as np

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
                    rank TEXT NOT NULL,
                    rank_order INT NOT NULL DEFAULT 0,
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
            # 增量：旧库可能缺 rank_order
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()]
                if "rank_order" not in cols:
                    conn.execute("ALTER TABLE predictions ADD COLUMN rank_order INT NOT NULL DEFAULT 0")
            except Exception:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_batch ON predictions(batch_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_target ON predictions(target_issue)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_rank_order ON predictions(rank_order)")
            conn.commit()
            conn.close()
        except Exception:
            pass


def _row_to_draw_tuple(r: dict) -> tuple:
    """JSON 行 → draws 表插入参数"""
    reds = sorted([r[f"红球{j}"] for j in range(1, 7)])
    return (
        r["期号"],
        reds[0], reds[1], reds[2], reds[3], reds[4], reds[5],
        r["蓝球"],
        r.get("奖池奖金") or 0,
        r.get("总投注额") or 0,
        r.get("一等奖注数") or 0,
        r.get("一等奖奖金") or 0,
        r.get("二等奖注数") or 0,
        r.get("二等奖奖金") or 0,
        r.get("开奖日期") or "",
        reds[-1] - reds[0],
        sum(reds),
        sum(1 for x in reds if 1 <= x <= 11),
        sum(1 for x in reds if 12 <= x <= 22),
        sum(1 for x in reds if 23 <= x <= 33),
        sum(1 for x in reds if x % 2 == 1),
        sum(1 for j in range(5) if reds[j + 1] - reds[j] == 1),
        sum(1 for x in reds if 1 <= x <= 31),
    )


class DataHub:
    """单例数据入口，提供所有预计算特征 + SQLite查询"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
            cls._instance._db = None
            cls._instance._db_lock = threading.RLock()
        return cls._instance

    def load(self, path=None, force=False):
        """加载数据并预计算所有特征。force=True 时强制从磁盘重载。"""
        if self._loaded and not force:
            return self

        path = path or SSQ_FILE
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.sort(key=lambda r: int(r["期号"]))
        self.data = data
        self.N = len(data)

        # 自动迁移到 SQLite（首次）
        _auto_migrate()
        # 重载时关闭旧连接，避免读到过期缓存
        self.db_close()

        self._build_red_features()
        self._build_market_vars()
        self._build_profiles()

        self._loaded = True
        # 预计算蓝球遗漏
        self._blue_miss = np.zeros((16, self.N), dtype=int)
        last_blue = np.zeros(16, dtype=int)
        for t in range(self.N):
            blue = self.data[t]["蓝球"]
            last_blue[blue - 1] = t
            for num in range(1, 17):
                self._blue_miss[num - 1, t] = t - last_blue[num - 1]
        return self

    def reload(self, path=None):
        """强制从 JSON 重载并重建特征"""
        return self.load(path=path, force=True)

    # ── SQLite 查询接口 ────────────────────────────────────────

    @property
    def db(self):
        if self._db is None:
            if os.path.exists(DB_FILE):
                self._db = sqlite3.connect(DB_FILE, check_same_thread=False)
                self._db.row_factory = sqlite3.Row
        return self._db

    def db_query(self, sql, params=()):
        """执行 SQL 并返回所有行（读写均持 RLock）"""
        if not self.db:
            return []
        lock = getattr(self, "_db_lock", None)
        if lock is None:
            self._db_lock = threading.RLock()
            lock = self._db_lock
        with lock:
            if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE")):
                self.db.execute(sql, params)
                self.db.commit()
                return []
            return self.db.execute(sql, params).fetchall()

    def db_query_one(self, sql, params=()):
        """执行 SQL 返回第一行"""
        rows = self.db_query(sql, params)
        return rows[0] if rows else None

    def db_close(self):
        lock = getattr(self, "_db_lock", None)
        if lock:
            with lock:
                if self._db:
                    self._db.close()
                    self._db = None
        else:
            if self._db:
                self._db.close()
                self._db = None

    # ── 内部构建方法 ──────────────────────────────────────────

    def _build_red_features(self):
        """33个号码 × N期 × 8维特征（向量化加速）"""
        N, D = self.N, self.data
        self.red_feat = np.zeros((33, N, 8))

        # 命中矩阵 hits[t, num-1] — O(N) 构建
        hits = np.zeros((N, 33), dtype=np.int8)
        for t in range(N):
            for j in range(1, 7):
                hits[t, D[t][f"红球{j}"] - 1] = 1

        pools = np.array([r["奖池奖金"] for r in D], dtype=float)
        pool_bins = np.percentile(pools, [0, 30, 60, 90, 100])
        # 奖池分位条件概率
        pool_corr = np.zeros((33, 4))
        for b in range(4):
            lo, hi = pool_bins[b], pool_bins[b + 1]
            mask = (pools >= lo) & (pools < hi if b < 3 else pools <= hi)
            denom = max(1, int(mask.sum()))
            pool_corr[:, b] = hits[mask].sum(axis=0) / denom

        # 跨期继承率
        inherit = np.zeros(33)
        if N > 1:
            inherit = (hits[:-1] * hits[1:]).sum(axis=0).astype(float) / (N - 1)

        # 滑动窗口频率（前缀和）
        csum = np.vstack([np.zeros((1, 33), dtype=np.int32), np.cumsum(hits, axis=0)])

        def win_count(t, w):
            lo = max(0, t + 1 - w)
            return csum[t + 1] - csum[lo]

        # 遗漏值：上次出现位置
        last_at = np.full(33, -1, dtype=int)
        prev_miss = np.zeros(33, dtype=int)
        pool_bin_idx = np.clip(np.searchsorted(pool_bins, pools) - 1, 0, 3)

        for t in range(N):
            # 更新 last_at
            appeared = np.where(hits[t] == 1)[0]
            last_at[appeared] = t
            miss = t - last_at
            # 未出现过的号码：遗漏记为 t（与旧逻辑 last_at 初值0 略有差异，更合理）
            miss = np.where(last_at < 0, t, miss)

            f10 = win_count(t, 10)
            f20 = win_count(t, 20)
            f50 = win_count(t, 50)
            trend = miss - prev_miss if t > 0 else np.zeros(33, dtype=int)
            prev_miss = miss.copy()

            pb = pool_bin_idx[t]
            self.red_feat[:, t, 0] = miss
            self.red_feat[:, t, 1] = f10
            self.red_feat[:, t, 2] = f20
            self.red_feat[:, t, 3] = f50
            self.red_feat[:, t, 4] = trend
            self.red_feat[:, t, 5] = pool_corr[:, pb]
            self.red_feat[:, t, 6] = inherit
            self.red_feat[:, t, 7] = miss / max(1, t + 1)

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
        # 期号 → 内存下标（供 validator 等按 issue 定位，不依赖 SQLite id）
        self.issue_to_t = {issue: t for t, issue in enumerate(self.issues)}
        prize1_total = self.p1c * self.p1a
        prize2_total = self.p2c * self.p2a
        major_ratio = np.zeros(N)
        mask = self.bet > 0
        major_ratio[mask] = (prize1_total[mask] + prize2_total[mask]) / self.bet[mask] * 100
        pool_bet_ratio = np.zeros(N)
        pool_bet_ratio[mask] = self.pool[mask] / self.bet[mask]
        bet_elasticity = np.zeros(N)
        bet_elasticity[1:] = self.bet[1:] / (self.pool[:-1] + 1) * 100
        span_arr = np.zeros(N)
        sum_arr = np.zeros(N)
        small_arr = np.zeros(N)
        cons_arr = np.zeros(N)
        for t in range(N):
            reds = sorted([self.data[t][f"红球{j}"] for j in range(1, 7)])
            s = sum(reds)
            span_arr[t] = reds[-1] - reds[0]
            sum_arr[t] = s
            small_arr[t] = sum(1 for x in reds if x <= 14)
            cons_arr[t] = sum(1 for j in range(5) if reds[j + 1] - reds[j] == 1)
        self.market = np.column_stack([
            self.pool / 1e8, self.bet / 1e8, self.p1c, self.p1a / 1e4,
            self.p2c, self.p2a / 1e4, prize1_total / 1e8, major_ratio, pool_bet_ratio,
            bet_elasticity, span_arr, sum_arr, small_arr, cons_arr,
        ])

    def _build_profiles(self):
        """号码画像"""
        self.profiles = []
        for t in range(self.N):
            d = self.data[t]
            reds = sorted([d[f"红球{j}"] for j in range(1, 7)])
            prime_set = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}
            self.profiles.append({
                "span": reds[-1] - reds[0],
                "sum": sum(reds),
                "odd": sum(1 for x in reds if x % 2 == 1),
                "cons": sum(1 for j in range(5) if reds[j + 1] - reds[j] == 1),
                "z1": sum(1 for x in reds if 1 <= x <= 11),
                "z2": sum(1 for x in reds if 12 <= x <= 22),
                "z3": sum(1 for x in reds if 23 <= x <= 33),
                "bday": sum(1 for x in reds if 1 <= x <= 31),
                "non_bday": sum(1 for x in reds if 32 <= x <= 33),
                "prime": sum(1 for x in reds if x in prime_set),
                "same_tail": len(set(x % 10 for x in reds)),
                "blue": d["蓝球"],
            })

    # ── 便捷查询接口 ──────────────────────────────────────────

    def get_red_features(self, t):
        """返回 [33, 8]"""
        return self.red_feat[:, t, :]

    def get_blue_features(self, t):
        """返回 [16, 4] 蓝球特征"""
        bf = np.zeros((16, 4))
        for num in range(1, 17):
            bf[num - 1, 0] = self._blue_miss[num - 1, t] if hasattr(self, "_blue_miss") else t
            appearances = sum(
                1 for s in range(max(0, t - 10), t + 1) if self.data[s]["蓝球"] == num
            )
            bf[num - 1, 1] = appearances
            if t > 0:
                bf[num - 1, 2] = (
                    self._blue_miss[num - 1, t] - self._blue_miss[num - 1, t - 1]
                    if hasattr(self, "_blue_miss")
                    else 0
                )
            bf[num - 1, 3] = bf[num - 1, 0] / max(1, t + 1)
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
        if p < 5e6:
            return 0
        if p < 2e8:
            return 1
        if p < 1e9:
            return 2
        if p < 2e9:
            return 3
        return 4

    def pool_state_name(self, t):
        return ["枯竭", "低位", "正常", "高位", "超高"][self.pool_state(t)]

    # ── 数据持久化 / 增量更新 ──────────────────────────────────

    def save_json(self, path=None):
        """将当前 data 写回 JSON（按期号升序）"""
        path = path or SSQ_FILE
        sorted_data = sorted(self.data, key=lambda r: int(r["期号"]))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted_data, f, ensure_ascii=False, indent=2)
        return path

    def _upsert_draw_sqlite(self, row: dict):
        """将单期写入/覆盖 SQLite draws 表"""
        if not self.db:
            _auto_migrate()
            self.db_close()
            if not self.db:
                return
        params = _row_to_draw_tuple(row)
        self.db_query(
            """
            INSERT INTO draws
            (issue, red1,red2,red3,red4,red5,red6, blue,
             pool, bet, prize1_cnt, prize1_amt, prize2_cnt, prize2_amt, draw_date,
             span, sum_val, zone1,zone2,zone3, odd_cnt, cons_pairs, bday_cnt)
            VALUES (?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?)
            ON CONFLICT(issue) DO UPDATE SET
                red1=excluded.red1, red2=excluded.red2, red3=excluded.red3,
                red4=excluded.red4, red5=excluded.red5, red6=excluded.red6,
                blue=excluded.blue, pool=excluded.pool, bet=excluded.bet,
                prize1_cnt=excluded.prize1_cnt, prize1_amt=excluded.prize1_amt,
                prize2_cnt=excluded.prize2_cnt, prize2_amt=excluded.prize2_amt,
                draw_date=excluded.draw_date,
                span=excluded.span, sum_val=excluded.sum_val,
                zone1=excluded.zone1, zone2=excluded.zone2, zone3=excluded.zone3,
                odd_cnt=excluded.odd_cnt, cons_pairs=excluded.cons_pairs,
                bday_cnt=excluded.bday_cnt
            """,
            params,
        )

    def append_new(self, row_dict, rebuild=True):
        """
        追加或覆盖一期数据，同步 JSON + SQLite。
        rebuild=True 时全量重建特征（默认）。
        """
        if not self._loaded:
            self.load()
        issue = str(row_dict["期号"])
        existing = {r["期号"]: i for i, r in enumerate(self.data)}
        if issue in existing:
            self.data[existing[issue]] = row_dict
        else:
            self.data.append(row_dict)
        self.data.sort(key=lambda r: int(r["期号"]))
        self.save_json()
        self._upsert_draw_sqlite(row_dict)
        if rebuild:
            self.reload()
        return self

    def merge_rows(self, rows: list, rebuild=True) -> dict:
        """
        批量合并远端数据。已存在期号若字段有变化则覆盖。
        返回统计: added / updated / unchanged / total
        """
        if not self._loaded:
            self.load()
        by_issue = {r["期号"]: r for r in self.data}
        added, updated, unchanged = 0, 0, 0
        changed_rows = []

        for row in rows:
            issue = str(row["期号"])
            row = dict(row)
            row["期号"] = issue
            if issue not in by_issue:
                by_issue[issue] = row
                added += 1
                changed_rows.append(row)
            else:
                old = by_issue[issue]
                keys = [
                    "红球1", "红球2", "红球3", "红球4", "红球5", "红球6", "蓝球",
                    "奖池奖金", "一等奖注数", "一等奖奖金", "二等奖注数", "二等奖奖金",
                    "总投注额", "开奖日期",
                ]
                if any(old.get(k) != row.get(k) for k in keys):
                    by_issue[issue] = row
                    updated += 1
                    changed_rows.append(row)
                else:
                    unchanged += 1

        if added or updated:
            self.data = sorted(by_issue.values(), key=lambda r: int(r["期号"]))
            self.save_json()
            for row in changed_rows:
                self._upsert_draw_sqlite(row)
            if rebuild:
                self.reload()
        return {
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "total": len(self.data),
            "latest_issue": self.data[-1]["期号"] if self.data else None,
            "latest_date": self.data[-1].get("开奖日期") if self.data else None,
        }

    def update_from_remote(self, progress_callback=None) -> dict:
        """
        从 500.com 爬取最新数据并合并到本地。
        新开奖到位后自动回填预测命中。
        """
        from engine.crawler import fetch_ssq_data

        if not self._loaded:
            self.load()

        before_issue = self.latest_issue
        before_n = self.N
        remote = fetch_ssq_data(progress_callback=progress_callback)
        if not remote:
            return {
                "success": False,
                "error": "爬取失败或无数据",
                "added": 0,
                "updated": 0,
                "before_issue": before_issue,
                "before_n": before_n,
            }

        stats = self.merge_rows(remote, rebuild=True)
        hit_stats = self.backfill_prediction_hits()
        stats.update({
            "success": True,
            "before_issue": before_issue,
            "before_n": before_n,
            "after_issue": self.latest_issue,
            "after_n": self.N,
            "hit_backfill": hit_stats,
            "remote_n": len(remote),
            "remote_latest": remote[-1]["期号"] if remote else None,
        })
        return stats

    def backfill_prediction_hits(self) -> dict:
        """
        用已开奖数据回填 predictions 表的 hit_red / hit_blue。
        仅处理 hit_red IS NULL 且 target_issue 已在 draws 中的记录。
        """
        if not self.db:
            return {"updated": 0}

        rows = self.db_query("""
            SELECT p.id, p.reds, p.blue, p.entry_type,
                   d.red1, d.red2, d.red3, d.red4, d.red5, d.red6, d.blue AS actual_blue
            FROM predictions p
            JOIN draws d ON p.target_issue = d.issue
            WHERE p.hit_red IS NULL
        """)

        updated = 0
        for r in rows:
            try:
                pred_reds = json.loads(r[1]) if isinstance(r[1], str) else r[1]
                if not isinstance(pred_reds, list):
                    continue
                actual_reds = {r[4], r[5], r[6], r[7], r[8], r[9]}
                hit_red = len(set(pred_reds) & actual_reds)

                # 蓝球：单注为 int；复式可能是 JSON 数组字符串
                pred_blue = r[2]
                actual_blue = r[10]
                hit_blue = 0
                if pred_blue is not None:
                    if isinstance(pred_blue, str) and pred_blue.strip().startswith("["):
                        try:
                            blues = json.loads(pred_blue)
                            hit_blue = 1 if actual_blue in blues else 0
                        except Exception:
                            hit_blue = 0
                    else:
                        try:
                            hit_blue = 1 if int(pred_blue) == int(actual_blue) else 0
                        except (TypeError, ValueError):
                            hit_blue = 0

                self.db_query(
                    "UPDATE predictions SET hit_red=?, hit_blue=? WHERE id=?",
                    (hit_red, hit_blue, r[0]),
                )
                updated += 1
            except Exception:
                continue

        return {"updated": updated}

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
