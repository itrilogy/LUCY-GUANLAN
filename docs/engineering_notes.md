# 双色球预测分析工具 · 工程笔记

## 项目概述

面向彩民的 Web 预测分析工具，基于 500.com 双色球历史数据 (2003~2026, 3481期)。
核心方法: 宏观市场状态感知 + 号码特征条件分布 + 前向/反向互逆验证。

技术栈: Flask + APScheduler + NumPy/scikit-learn + 纯静态前端。

## 设计原则

1. 诚实区分可预测与不可预测的边界
2. 号码不可预测 (全部统计检验通过), 市场行为可预测 (反馈回路 r=0.68)
3. 每个预测号码必须经过双向一致性校验

## 系统架构

```
app.py (Flask + APScheduler)
  ├── engine/data_hub.py    ← 数据层: 加载JSON, 预计算所有特征
  ├── engine/market.py      ← 市场模型: Regime分类 + 反馈回路 + Markov转移
  ├── engine/numbers.py     ← 号码分析: 条件分布 + 成本评分 + 候选采样
  ├── engine/validator.py   ← 双向验证: 前向→反向→一致性评分 + 回测
  ├── engine/predictor.py   ← 预测编排: 整合所有模块, 生成报告
  ├── web/templates/        ← Jinja2 模板
  └── web/static/           ← CSS
```

开奖日 22:00 调度流程 (`run_update`, 周二/四/日):
```
爬取 500.com (engine/crawler.py)
  → merge_rows 合并 JSON + SQLite draws
  → backfill_prediction_hits 回填 hit_red/hit_blue
  → DataHub.reload + Market/Number/Validator/Predictor 重建
  → Predictor.run → predict_result.json
```
启动: `STARTUP_FETCH=auto` 时仅在数据过期（≥STALE_DAYS 或缺开奖日数据）后台爬取。
CLI: `python3 scripts/crawl_update.py`（支持 `--data-only` / `--predict-only`）

### 反向验证索引
`Validator.backward` 用 `issue → t`（`DataHub.issue_to_t`）定位前一期，
不再使用 `draws.id - 1`，避免 SQLite 自增 id 与期序错位。

### 成本分近窗频率
`NumberModel` 预计算 hit 前缀和，`recent_freq_vector(t)` O(1) 取近 20 期频率；
历史拟合使用各期自身窗口，采样热路径复用 `_latest_recent`。

## 算法选型与参数来源

### 市场 Regime 分类
- **来源**: `ssq_bettor_behavior.py` → `MarketCycleAnalyzer`
- **方法**: GMM 聚类 (5类), 输入为 [log(奖池), log(投注), log(头奖)]
- **参数**: n_components=5, random_state=42, n_init=10
- **5类状态**: 
  - 0-崩溃态(1.8%): 均池0.2亿, 均头奖0.7注 —— 刚被掏空
  - 1-蓄水态(23.9%): 均池1.1亿, 均头奖2.3注 —— 缓慢累积中
  - 2-大奖态(4.4%): 均池3.8亿, 均头奖35.5注 —— 头奖爆发
  - 3-增长态(19.9%): 均池6.8亿, 均头奖13.8注 —— 快速增长
  - 4-成熟态(50.1%): 均池11.5亿, 均头奖6.4注 —— 高池稳态

### 奖池水位分级
- **来源**: `ssq_house_model.py` → `HouseParameters`
- **阈值**: 枯竭<0.05亿 / 低位<2亿 / 正常<10亿 / 高位<20亿 / 超高≥20亿
- **中文标签**: `pool_state_name()` 返回 ["枯竭","低位","正常","高位","超高"]

### 状态转移矩阵 (Markov)
- **来源**: `ssq_prob_kernel.py` → `ProbabilisticTransitionKernel`
- **方法**: KMeans 聚类 (K=12) → 市场变量12维标准化 → 聚类为12态
- **计数矩阵**: T[i][j] = #{t | state_t=i, state_{t+1}=j}
- **前向概率**: P(j|i) = T[i][j] / Σ_k T[i][k]
- **反向**: 贝叶斯公式 P(i|j) = P(j|i) · π_i / π_j
- **在engine/market.py中的实现**: `_build_markov()` 使用 market 矩阵作为输入

### 反馈回路系数
- **来源**: `ssq_bettor_behavior.py` → `FeedbackLoopAnalyzer`
- **回路1**: 奖池→投注 (正向, r=0.678, lag=3)
  - log(投注_t) = α + β·log(奖池_{t-1})
  - 系数固化: `LinearRegression().fit()`
- **回路2**: 投注→头奖 (正向, r=0.574, lag=0)
  - log(头奖_t) = α + β·log(投注_t)
- **回路3**: 头奖→奖池 (负向, r=-0.341, lag=1)
  - 头奖总支出越高 → 下期奖池越低
- **脉冲响应**: 奖池+1亿 → 投注响应+877万, 半衰期 1.9期
- **在engine/market.py中的实现**: `_build_feedback()` 用 LinearRegression

### 生日号效应
- **来源**: `ssq_bettor_behavior.py` → `BehaviorInference`
- 1-31号段开出时头奖比 32-33 高出 1.16 倍
- **在engine/numbers.py中的实现**: `get_conditional_dist()` 中调整 bday 均值 ±0.08

### 号码特征无条件分布 (3468期实测)
- **来源**: `ssq_number_analysis.py` → `NumberLifecycle`
- 和值: N(μ=101, σ=22), 区间[58, 142]@95%
- 跨度: N(μ=24, σ=5), 区间[15, 33]@95%
- 一区数: μ=2.0, σ=1.0, 区间[0, 4]@95%
- 生日号: μ=5.7, σ=0.5, 区间[5, 6]@95% (组合约束: 33个球中只有2个非生日号)
- 连号: μ=0.9, σ=0.8
- 质数: μ=2.0, σ=1.0
- 同尾数: μ=1.0, σ=0.7

### 条件回归 R²
- **来源**: `ssq_zone_predictor.py` → `MarketConditionalModel`
- 所有号码特征 R² < 0.003
- 结论: 市场状态无法预测号码特征 —— 条件分布 ≈ 无条件分布

### 成本模型
- **来源**: `ssq_house_model.py` → `HouseCostModel`
- 成本分公式: `bday_cnt × 0.3 + (7 - span/5) × 0.15 + cons × 0.2 + recent_freq × 0.2 - big × 0.3`
- 正向: 高成本分 = 热门号码 = 更多人投注
- 成本-头奖相关系数: r=0.037 (p=0.031, 弱但显著)
- 验证: 高成本期(前25%)平均头奖 8.3注 vs 低成本期(后25%) 7.0注
- **在engine/numbers.py中的实现**: `_raw_cost_score()` + `estimate_prize1()`

## 双向验证算法 (核心创新)

### 前向通道
```
输入: 当前市场状态向量 + 候选号码组合
   ↓
HouseCostModel → 估算"如果开出这组号码, 头奖注数"
   ↓
输出: 预期头奖注数 (est_prize1)
```
实现: `engine/validator.py` → `forward()`

### 反向通道
```
输入: 预期头奖注数
   ↓
在历史3481期中找头奖注数最接近的top_k期
   ↓
统计这些期"开奖前"的市场Regime分布
   ↓
输出: 反推的Regime分布 + 最概然Regime
```
实现: `engine/validator.py` → `backward()`

### 一致性评分
```
score = regime_prob × 0.7 + concentration × 0.3

regime_prob = 反向推得的Regime中, 当前Regime的概率
concentration = 1 - 反向Regime分布的归一化熵

当 score > 0.2 → ✅ 通过 (passed=True)
```
实现: `engine/validator.py` → `consistency_score()`

### 历史回测
`backtest(n_test=200)`: 对最近200期做留一法验证
- 对每期t: 用t的市场状态预测t+1, 检查top-1推荐的命中数
- 返回平均命中数 vs 随机期望

## 预测流水线 (engine/predictor.py)

```
Predictor.run(n_candidates=2000):
  1. 获取当前市场状态 (Regime + 奖池水位)
  2. NumberModel.sample_candidates(2000, pool_state) → 2000组候选
  3. Validator.batch_validate(candidates) → 一致性评分排序
  4. 取 Top-N (config.TOP_N=10) 输出
  5. _build_report() → 结构化报告 (含市场/号码/热度/回顾)
```

### 报告结构
```json
{
  "current_issue": "26084",
  "market": {"regime", "regime_id", "pool", "bet", 
             "predicted_pool_range", "predicted_bet_range"},
  "predictions": [{"reds", "blue", "consistency", "cost", "est_prize1", "passed"}],
  "popularity": {"hot"[10], "cold"[10], "birthday_effect"},
  "last_review": {"issue", "actual_reds", "actual_blue"},
  "stats": {"total_candidates", "top_score", "avg_score"}
}
```

## 已知局限性

1. 号码本身是独立随机过程 —— 任何"预测"本质上都是条件分布估计
2. 双向验证评分高 ≠ 中奖概率高 —— 只表示"这个号码在当前市场条件下合理"
3. 模型依赖 500.com 数据源 —— 源站变更可能导致爬虫失效
4. 彩民投注行为为反推估计 —— 无真实投注分布数据
5. 成本模型 r=0.037 —— 信号极弱, 仅为统计显著而非实用显著
6. Flask 开发服务器不适用于生产环境。建议：`gunicorn -w 1 -b 0.0.0.0:8080 app:app`（**单 worker**，避免多进程重复调度与内存模型分裂）。SQLite 访问已加 RLock；多 worker 非官方支持。

## 数据库

使用 SQLite 替代 JSON 全量扫描，关键加速：
- `scripts/init_db.py` — JSON → SQLite 迁移
- `engine/data_hub.py` — `db_query()/db_query_one()` SQLite 查询接口，启动时自动迁移
- `engine/validator.py` — `backward()` 改用 `ORDER BY ABS(prize1_cnt-?) LIMIT 20` 索引查询
- `app.py` — `GET /api/periods?page=N&per_page=M` 分页API

### 表结构

```sql
CREATE TABLE draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue TEXT NOT NULL UNIQUE,
    red1..red6 INT, blue INT,
    pool BIGINT, bet BIGINT,
    prize1_cnt INT, prize1_amt BIGINT,
    prize2_cnt INT, prize2_amt BIGINT,
    draw_date TEXT,
    span INT, sum_val INT,
    zone1,zone2,zone3 INT,
    odd_cnt INT, cons_pairs INT, bday_cnt INT
);
```

加速索引: `idx_prize1_cnt`, `idx_pool`, `idx_bet`, `idx_issue`

### 加速效果

| 环节 | 优化前 | 优化后 | 加速比 |
|------|--------|--------|-------|
| backward(prize) | O(3481) 全量扫描 | O(log N) B树索引 | **~500x** |
| 分区页渲染 | JSON 1.4MB加载 | SELECT LIMIT 200 | **~35x** |
| 遗传进化全量 | ~9分钟 | ~3-4分钟(预期) | **~2-3x** |

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-07-25 | 初始版本: 全量8模块, Flask+APScheduler, 前端深色主题 |
| 1.1 | 2026-07-26 | 新增: 遗传进化引擎(evolution.py), SQLite数据库, 批量评估优化, 分页分区表 |
| 1.2 | 2026-07-27 | 新增: 复式推荐(高频聚合), 双向验证优化, 后端渲染SVG图表(Y轴修正) |
| 1.3 | 2026-07-27 | 新增: 预测对照表(predict_batch+predictions), 批次流水号, 期次/批次筛选 |
| 1.4 | 2026-07-27 | 优化: 前端单页架构, 按钮区移至标题行, 历史趋势+分区合并到推理页, 全量进化弹窗进度 |
