#!/usr/bin/env python3
"""
SQLite 数据库初始化 —— 从 JSON 迁移到 SQLite

用法: python3 scripts/init_db.py
"""

import json, os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

DB_FILE = os.path.join(DATA_DIR, "ssq.db")
JSON_FILE = os.path.join(DATA_DIR, "ssq_all.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue       TEXT NOT NULL UNIQUE,
    red1,red2,red3,red4,red5,red6 INT,
    blue        INT,
    pool        BIGINT,
    bet         BIGINT,
    prize1_cnt  INT,
    prize1_amt  BIGINT,
    prize2_cnt  INT,
    prize2_amt  BIGINT,
    draw_date   TEXT,
    span        INT,
    sum_val     INT,
    zone1,zone2,zone3 INT,
    odd_cnt     INT,
    cons_pairs  INT,
    bday_cnt    INT
);
CREATE INDEX IF NOT EXISTS idx_prize1_cnt ON draws(prize1_cnt);
CREATE INDEX IF NOT EXISTS idx_pool ON draws(pool);
CREATE INDEX IF NOT EXISTS idx_bet ON draws(bet);
CREATE INDEX IF NOT EXISTS idx_issue ON draws(issue);

-- 预测批次日增流水
CREATE TABLE IF NOT EXISTS predict_batch (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    target_issue TEXT NOT NULL,
    total_entries INT DEFAULT 0
);

-- 预测对照表（rank 为 TEXT：'1'..'12' 或 'A'..'D'）
CREATE TABLE IF NOT EXISTS predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    INT NOT NULL REFERENCES predict_batch(batch_id),
    saved_at    TEXT NOT NULL DEFAULT (datetime('now')),
    target_issue TEXT NOT NULL,
    entry_type  TEXT NOT NULL DEFAULT 'single',  -- 'single' 或 'compound'
    rank        TEXT NOT NULL,          -- '1'~'12' 或 'A'~'D'
    rank_order  INT NOT NULL DEFAULT 0, -- 排序键：1..12, 101..104
    reds        TEXT NOT NULL,          -- JSON数组
    blue        INT,
    reds_count  INT DEFAULT 6,
    blues_count INT DEFAULT 1,
    consistency REAL,
    cost        REAL,
    total_cost  INT DEFAULT 0,
    total_combos INT DEFAULT 0,
    est_prize1  INT,
    actual      INT DEFAULT NULL,
    hit_red     INT DEFAULT NULL,
    hit_blue    INT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_pred_batch ON predictions(batch_id);
CREATE INDEX IF NOT EXISTS idx_pred_target ON predictions(target_issue);
CREATE INDEX IF NOT EXISTS idx_pred_rank_order ON predictions(rank_order);
"""


def migrate():
    """JSON → SQLite 迁移"""
    print(f"读取数据: {JSON_FILE}")
    with open(JSON_FILE) as f:
        data = json.load(f)
    data.sort(key=lambda r: int(r["期号"]))
    
    print(f"共 {len(data)} 期，写入数据库...")
    
    conn = sqlite3.connect(DB_FILE)
    conn.executescript(SCHEMA)
    
    inserted = 0
    for r in data:
        reds = sorted([r[f"红球{j}"] for j in range(1, 7)])
        conn.execute("""
            INSERT OR IGNORE INTO draws
            (issue, red1,red2,red3,red4,red5,red6, blue,
             pool, bet, prize1_cnt, prize1_amt, prize2_cnt, prize2_amt, draw_date,
             span, sum_val, zone1,zone2,zone3, odd_cnt, cons_pairs, bday_cnt)
            VALUES (?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?)
        """, (
            r["期号"],
            reds[0], reds[1], reds[2], reds[3], reds[4], reds[5],
            r["蓝球"],
            r["奖池奖金"], r["总投注额"],
            r["一等奖注数"], r["一等奖奖金"],
            r["二等奖注数"], r["二等奖奖金"],
            r["开奖日期"],
            reds[-1] - reds[0],  # span
            sum(reds),           # sum_val
            sum(1 for x in reds if 1 <= x <= 11),   # zone1
            sum(1 for x in reds if 12 <= x <= 22),  # zone2
            sum(1 for x in reds if 23 <= x <= 33),  # zone3
            sum(1 for x in reds if x % 2 == 1),     # odd_cnt
            sum(1 for j in range(5) if reds[j+1]-reds[j] == 1),  # cons_pairs
            sum(1 for x in reds if 1 <= x <= 31),   # bday_cnt
        ))
        inserted += 1
    
    conn.commit()
    
    # 验证
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()
    
    print(f"迁移完成: {inserted} 条写入, {count} 条验证")
    print(f"数据库: {DB_FILE}")
    return True


if __name__ == "__main__":
    migrate()
