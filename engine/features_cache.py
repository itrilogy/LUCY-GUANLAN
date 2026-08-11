#!/usr/bin/env python3
"""
特征缓存（Phase 4）

将 red_feat / market / blue_miss 关键到 data/features.npz，
DataHub 在数据指纹未变时可快速加载。
"""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from config import FEATURES_FILE, SSQ_FILE


def data_fingerprint(ssq_path=None) -> str:
    path = ssq_path or SSQ_FILE
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    # also size/mtime for speed
    st = os.stat(path)
    h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:32]


def save_features(dh, path=None, fingerprint=None):
    path = path or FEATURES_FILE
    fp = fingerprint or data_fingerprint()
    np.savez_compressed(
        path,
        red_feat=dh.red_feat,
        market=dh.market,
        blue_miss=dh._blue_miss,
        pool=dh.pool,
        bet=dh.bet,
        p1c=dh.p1c,
        fingerprint=np.array([fp]),
        N=np.array([dh.N]),
        latest_issue=np.array([dh.latest_issue]),
    )
    meta = {"fingerprint": fp, "N": dh.N, "latest_issue": dh.latest_issue, "path": path}
    with open(path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def try_load_features(dh, path=None) -> bool:
    """若指纹匹配则填充 dh 特征数组，返回 True。"""
    path = path or FEATURES_FILE
    if not os.path.exists(path):
        return False
    try:
        fp = data_fingerprint()
        z = np.load(path, allow_pickle=True)
        cached_fp = str(z["fingerprint"][0])
        if cached_fp != fp:
            return False
        if int(z["N"][0]) != dh.N:
            return False
        dh.red_feat = z["red_feat"]
        dh.market = z["market"]
        dh._blue_miss = z["blue_miss"]
        # pool/bet/p1c 仍由 _build_market_vars 构建更稳妥；若形状一致可跳过
        return True
    except Exception:
        return False
