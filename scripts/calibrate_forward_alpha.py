#!/usr/bin/env python3
"""
时间序列标定 FORWARD_COST_ALPHA

在历史期 t 上：f_t = predict_p1c_from_market(bet_t)
             g_t = g_cost_p1c(actual_reds_t)
选择 α 使 Var(α g)/Var(f+α g) ∈ [0.05, 0.10]
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import numpy as np
    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from config import ENGINE_STATE_FILE

    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)

    f_list, g_list = [], []
    for t in range(dh.N):
        f_list.append(mm.predict_p1c_from_market(dh.bet[t]))
        reds = sorted([dh.data[t][f"红球{j}"] for j in range(1, 7)])
        g_list.append(nm.g_cost_p1c(reds, t=t))
    f = np.asarray(f_list, dtype=float)
    g = np.asarray(g_list, dtype=float)

    best_a, best_share, best_dist = 0.05, None, 1e9
    target = 0.075
    for a in np.linspace(0.0, 0.5, 51):
        hat = f + a * g
        vhat = float(np.var(hat))
        if vhat < 1e-12:
            continue
        share = float(np.var(a * g) / vhat)
        dist = abs(share - target)
        if 0.05 <= share <= 0.10 and dist < best_dist:
            best_a, best_share, best_dist = float(a), share, dist
        elif best_share is None and dist < best_dist:
            best_a, best_share, best_dist = float(a), share, dist

    print(f"alpha={best_a:.4f} var_share={best_share:.4f} (target ~0.075)")
    # 写入 engine_state
    st = {}
    if os.path.exists(ENGINE_STATE_FILE):
        try:
            with open(ENGINE_STATE_FILE, encoding="utf-8") as fp:
                st = json.load(fp)
        except Exception:
            st = {}
    st.update({
        "forward_cost_alpha": best_a,
        "alpha_var_share": best_share,
        "alpha_train_range": [0, dh.N - 1],
    })
    with open(ENGINE_STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(st, fp, ensure_ascii=False, indent=2)
    print(f"saved → {ENGINE_STATE_FILE}")
    print(f"export SSQ_FORWARD_COST_ALPHA={best_a:.4f}")


if __name__ == "__main__":
    main()
