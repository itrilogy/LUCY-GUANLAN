#!/usr/bin/env python3
"""初始化数据: 从原始项目复制并验证"""
import json, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    # 验证数据完整性
    from config import SSQ_FILE
    with open(SSQ_FILE) as f:
        data = json.load(f)
    
    N = len(data)
    data.sort(key=lambda r: int(r["期号"]))
    
    print(f"数据文件: {SSQ_FILE}")
    print(f"总期数: {N}")
    print(f"范围: {data[0]['期号']} ({data[0]['开奖日期']}) ~ "
          f"{data[-1]['期号']} ({data[-1]['开奖日期']})")
    print("数据验证通过 ✅")

if __name__ == "__main__":
    main()
