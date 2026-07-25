#!/usr/bin/env python3
"""手动触发数据爬取与预测更新"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data_hub import DataHub
from engine.market import MarketModel
from engine.numbers import NumberModel
from engine.validator import Validator
from engine.predictor import Predictor

def main():
    print("开始更新...")
    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    p = Predictor(dh, mm, nm, v)
    
    report = p.run(n_candidates=2000)
    p.save(report)
    
    print(f"更新完成: {report['current_issue']}")
    print(f"预测 {len(report['predictions'])} 组号码")
    print(f"耗时: {report['elapsed']}s")

if __name__ == "__main__":
    main()
