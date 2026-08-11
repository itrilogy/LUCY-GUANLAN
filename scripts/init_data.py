#!/usr/bin/env python3
"""初始化/校验本地双色球数据完整性"""
import json, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from config import SSQ_FILE
    with open(SSQ_FILE, encoding="utf-8") as f:
        data = json.load(f)

    N = len(data)
    data.sort(key=lambda r: int(r["期号"]))

    # 基础完整性
    issues = []
    seen = set()
    for r in data:
        issue = r.get("期号")
        if issue in seen:
            issues.append(f"重复期号 {issue}")
        seen.add(issue)
        reds = [r.get(f"红球{j}") for j in range(1, 7)]
        if any(x is None or not (1 <= x <= 33) for x in reds):
            issues.append(f"{issue} 红球越界/缺失")
        elif len(set(reds)) != 6:
            issues.append(f"{issue} 红球重复")
        blue = r.get("蓝球")
        if blue is None or not (1 <= blue <= 16):
            issues.append(f"{issue} 蓝球越界/缺失")
        if not r.get("开奖日期"):
            issues.append(f"{issue} 缺开奖日期")

    # 期号连续性（跨年允许跳号）
    gaps = []
    for i in range(1, N):
        a, b = int(data[i - 1]["期号"]), int(data[i]["期号"])
        if b - a > 1 and data[i - 1]["期号"][:2] == data[i]["期号"][:2]:
            gaps.append((data[i - 1]["期号"], data[i]["期号"]))

    print(f"数据文件: {SSQ_FILE}")
    print(f"总期数: {N}")
    print(
        f"范围: {data[0]['期号']} ({data[0]['开奖日期']}) ~ "
        f"{data[-1]['期号']} ({data[-1]['开奖日期']})"
    )
    if gaps:
        print(f"同年内期号缺口: {len(gaps)} 处, 示例 {gaps[:5]}")
    if issues:
        print(f"校验问题: {len(issues)}")
        for msg in issues[:20]:
            print(f"  - {msg}")
        sys.exit(1)
    print("数据验证通过 ✅")


if __name__ == "__main__":
    main()
