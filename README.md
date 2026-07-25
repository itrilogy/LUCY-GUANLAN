# 双色球预测分析工具

基于 500.com 历史数据 (2003~2026, 3481期) 的 Web 预测分析工具。

**核心方法**:
- 宏观市场状态感知 (Regime 分类 + 奖池水位)
- 号码特征条件分布 (双向一致性验证)
- 前向→反向互逆校验 (预测自洽性评分)

**启动**:
```bash
pip install -r requirements.txt
python3 app.py
# 访问 http://localhost:5000
```

**目录结构**:
```
ssq_predictor/
├── app.py              # Flask 入口 + 调度器
├── config.py           # 全局配置
├── engine/             # 核心引擎
│   ├── data_hub.py     # 数据层
│   ├── market.py       # 市场模型
│   ├── numbers.py      # 号码分析
│   ├── validator.py    # 双向验证
│   └── predictor.py    # 预测编排
├── web/                # 前端
├── docs/               # 文档
└── data/               # 数据
```
