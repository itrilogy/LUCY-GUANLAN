#!/usr/bin/env python3
"""
predictions.rank TEXT + rank_order 迁移

用法: python3 scripts/migrate_predictions_rank_v2.py
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

DB_FILE = os.path.join(DATA_DIR, "ssq.db")


def rank_order(label) -> int:
    s = str(label)
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s.isalpha():
        return 100 + (ord(s.upper()) - 64)
    return 0


def migrate():
    if not os.path.exists(DB_FILE):
        print(f"无数据库: {DB_FILE}，跳过")
        return True

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "predictions" not in tables:
        print("predictions 表不存在，跳过")
        conn.close()
        return True

    cols = [r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()]
    if "rank_order" not in cols:
        print("ADD COLUMN rank_order ...")
        conn.execute(
            "ALTER TABLE predictions ADD COLUMN rank_order INT NOT NULL DEFAULT 0"
        )
        conn.commit()

    # 回填 rank_order + 字符串化 rank
    rows = conn.execute(
        "SELECT id, rank, rank_order FROM predictions"
    ).fetchall()
    for r in rows:
        label = str(r["rank"])
        ro = rank_order(label)
        conn.execute(
            "UPDATE predictions SET rank=?, rank_order=? WHERE id=?",
            (label, ro, r["id"]),
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pred_rank_order ON predictions(rank_order)"
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    conn.close()
    print(f"迁移完成: {n} 条 predictions (rank TEXT 语义 + rank_order)")
    return True


if __name__ == "__main__":
    migrate()
