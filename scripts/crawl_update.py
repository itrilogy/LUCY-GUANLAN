#!/usr/bin/env python3
"""
手动触发：爬取 500.com 最新开奖 → 合并本地 JSON/SQLite → 重建特征 → 重跑预测

用法:
  python3 scripts/crawl_update.py              # 完整更新
  python3 scripts/crawl_update.py --predict-only  # 仅重跑预测
  python3 scripts/crawl_update.py --data-only     # 仅更新数据，不预测
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="双色球数据爬取与预测更新")
    parser.add_argument(
        "--predict-only",
        action="store_true",
        help="跳过爬取，仅用本地数据重跑预测",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="仅爬取/合并数据，不运行预测",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=2000,
        help="候选采样数 (默认 2000)",
    )
    args = parser.parse_args()

    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from engine.validator import Validator
    from engine.predictor import Predictor

    print("开始更新...")
    dh = DataHub().load()
    print(f"本地数据: {dh.N} 期, 最新 {dh.latest_issue} ({dh.dates[-1]})")

    if not args.predict_only:
        print("爬取远端数据...")
        stats = dh.update_from_remote(progress_callback=lambda m: print(f"  {m}"))
        if not stats.get("success"):
            print(f"爬取失败: {stats.get('error')}")
            if args.data_only:
                sys.exit(1)
            print("继续使用本地数据预测...")
        else:
            print(
                f"合并结果: +{stats.get('added', 0)} 新增, "
                f"{stats.get('updated', 0)} 更新, "
                f"未变 {stats.get('unchanged', 0)}"
            )
            print(
                f"数据范围: {stats.get('before_issue')} → {stats.get('after_issue')} "
                f"({stats.get('before_n')} → {stats.get('after_n')} 期)"
            )
            if stats.get("hit_backfill"):
                print(f"预测回填: {stats['hit_backfill'].get('updated', 0)} 条")

    if args.data_only:
        print("数据更新完成 (--data-only)")
        return

    # 数据可能已变，重建下游模型
    dh = DataHub().reload()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    validator = Validator(dh, mm, nm)
    predictor = Predictor(dh, mm, nm, validator)

    print(f"运行预测 (候选 {args.candidates})...")
    report = predictor.run(n_candidates=args.candidates)
    predictor.save(report)

    print(f"更新完成: 数据最新期={dh.latest_issue}, 预测目标={report['current_issue']}")
    print(f"预测 {len(report['predictions'])} 组号码")
    print(f"耗时: {report['elapsed']}s")


if __name__ == "__main__":
    main()
