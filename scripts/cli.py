#!/usr/bin/env python3
"""
统一 CLI（脚本路径，非 package）

用法（在 ssq_predictor/ 下）:
  python3 scripts/cli.py update
  python3 scripts/cli.py update --data-only
  python3 scripts/cli.py predict
  python3 scripts/cli.py check
  python3 scripts/cli.py serve
  python3 scripts/cli.py test

注意: CLI 数据变更后始终 full 重建模型（不 soft）。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def cmd_update(args):
    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from engine.validator import Validator
    from engine.predictor import Predictor

    print("CLI update...")
    dh = DataHub().load()
    print(f"本地: {dh.N} 期, 最新 {dh.latest_issue} ({dh.dates[-1]})")

    if not args.predict_only:
        stats = dh.update_from_remote(progress_callback=lambda m: print(f"  {m}"))
        if not stats.get("success"):
            print(f"爬取失败: {stats.get('error')}")
            if args.data_only:
                return 1
        else:
            print(
                f"合并 +{stats.get('added', 0)} / 更新 {stats.get('updated', 0)} "
                f"→ {stats.get('after_issue')} ({stats.get('after_n')} 期)"
            )

    if args.data_only:
        print("完成 (--data-only); CLI 未重建模型")
        return 0

    # 始终 full reinit
    dh = DataHub().reload()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    p = Predictor(dh, mm, nm, v)
    report = p.run(n_candidates=args.candidates)
    p.save(report)
    print(f"预测完成: 目标 {report.get('current_issue')} 耗时 {report.get('elapsed')}s")
    return 0


def cmd_predict(args):
    args.predict_only = True
    args.data_only = False
    return cmd_update(args)


def cmd_check(args):
    from scripts.init_data import main as init_main
    # init_data.main 直接 print 并可能 exit
    try:
        init_main()
    except SystemExit as e:
        if e.code not in (0, None):
            return int(e.code or 1)
    # smoke: load + backward + sample
    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from engine.validator import Validator

    DataHub._instance = None
    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    v.ensure_backward_lut()
    assert v._backward_lut is not None
    cands = nm.sample_candidates(20, "平衡")
    out = v.batch_validate(cands)
    print(f"smoke OK: N={dh.N} sample={len(cands)} validated={len(out)}")
    return 0


def cmd_serve(args):
    os.chdir(ROOT)
    # import app triggers scheduler
    from config import HOST, PORT
    import app as appmod
    print(f"启动 http://{HOST}:{PORT}")
    appmod.app.run(host=HOST, port=PORT, debug=False)
    return 0


def cmd_test(args):
    import subprocess
    r = subprocess.call([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    return r


def cmd_eval(args):
    import json
    import os
    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from engine.eval import run_walk_forward_smoke, save_kpi
    from config import DATA_DIR

    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    kpi = run_walk_forward_smoke(dh, mm, nm, n_test=args.n_test, seed=args.seed)
    out = args.out or os.path.join(DATA_DIR, "eval", "wf_smoke_latest.json")
    save_kpi(kpi, out)
    print(json.dumps(kpi, ensure_ascii=False, indent=2))
    print(f"saved → {out}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="ssq_predictor CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("update", help="爬取+full重建+预测")
    p_up.add_argument("--data-only", action="store_true")
    p_up.add_argument("--predict-only", action="store_true")
    p_up.add_argument("--candidates", type=int, default=2000)
    p_up.set_defaults(func=cmd_update)

    p_pr = sub.add_parser("predict", help="仅预测（full 重建）")
    p_pr.add_argument("--candidates", type=int, default=2000)
    p_pr.set_defaults(func=cmd_predict, data_only=False, predict_only=True)

    p_ck = sub.add_parser("check", help="数据校验 + 引擎冒烟")
    p_ck.set_defaults(func=cmd_check)

    p_sv = sub.add_parser("serve", help="启动 Flask")
    p_sv.set_defaults(func=cmd_serve)

    p_ts = sub.add_parser("test", help="pytest")
    p_ts.set_defaults(func=cmd_test)

    p_ev = sub.add_parser("eval", help="walk-forward smoke KPI")
    p_ev.add_argument("--n-test", type=int, default=40)
    p_ev.add_argument("--seed", type=int, default=42)
    p_ev.add_argument("--out", type=str, default=None)
    p_ev.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    raise SystemExit(args.func(args) or 0)


if __name__ == "__main__":
    main()
