# 数据结构文档

## 项目文件总览

```
ssq_predictor/
├── data/
│   ├── ssq_all.json          # 双色球全量历史数据 (3481期)
│   └── predict_result.json   # 最新预测结果 (自动生成)
├── config.py                 # 全局配置 (35项参数)
├── engine/*.py               # 引擎模块
└── web/templates/index.html  # 前端模板 (Jinja2)
```

---

## 1. data/ssq_all.json

**来源**: 500.com 历史数据, 通过 `lottery_crawler.py` 爬取
**规模**: 3481 期, 约 1.4 MB
**时间范围**: 2003-02-23 ~ 2026-07-23

**Schema** (每期一个对象, 共3481个):
```json
{
  "期号": "26084",
  "红球1": 1, "红球2": 5, "红球3": 6,
  "红球4": 10, "红球5": 12, "红球6": 16,
  "蓝球": 5,
  "快乐星期天": null,
  "奖池奖金": 480566551,
  "一等奖注数": 10,
  "一等奖奖金": 6809591,
  "二等奖注数": 107,
  "二等奖奖金": 211400,
  "总投注额": 348718788,
  "开奖日期": "2026-07-23"
}
```

| 字段 | 类型 | 说明 | 校验规则 |
|------|------|------|---------|
| 期号 | string | 5-6位, YYNNN 格式 | 唯一, 递增 |
| 红球1~6 | int | 1~33 | 升序排列, 互异 |
| 蓝球 | int | 1~16 | |
| 快乐星期天 | int|null | 2003-2004年有值, 后为null | |
| 奖池奖金 | int | 元 | ≥0 |
| 一等奖注数 | int | 注数 | ≥0 |
| 一等奖奖金 | int | 元/注 | >500万或0(空开) |
| 二等奖注数 | int | 注数 | ≥0 |
| 二等奖奖金 | int | 元/注 | >0或0(空开) |
| 总投注额 | int | 元 | >0 |
| 开奖日期 | string | YYYY-MM-DD | 合法日期 |

---

## 2. data/predict_result.json

**来源**: Predictor.run() 自动生成
**更新**: 每日 00:00 / 手动 / 首次启动

**Schema**:
```json
{
  "update_time": "2026-07-25 00:00:00",
  "current_issue": "26084",
  "elapsed": 10.3,

  "market": {
    "regime": "平衡",
    "regime_id": 0,
    "pool": 480566551,
    "bet": 348718788,
    "predicted_pool_range": [432509895, 528623206],
    "predicted_bet_range": [314000000, 386000000]
  },

  "predictions": [
    {
      "rank": 1,
      "reds": [16, 18, 19, 20, 25, 26],
      "blue": 1,
      "consistency": 0.33,
      "cost": 3.4,
      "est_prize1": 8,
      "passed": true
    }
  ],

  "popularity": {
    "hot": [24, 1, 5, 14, 28, 10, 12, 7, 16, 22],
    "cold": [33, 3, 20, 8, 30, 2, 26, 9, 17, 21],
    "birthday_effect": 1.16
  },

  "last_review": {
    "issue": "26083",
    "actual_reds": [7, 14, 15, 23, 28, 33],
    "actual_blue": 3
  },

  "stats": {
    "total_candidates": 2000,
    "top_score": 0.33,
    "avg_score": 0.3274
  }
}
```

| 字段路径 | 类型 | 说明 |
|---------|------|------|
| update_time | string | 最后更新时间 |
| current_issue | string | 最新一期期号 |
| elapsed | float | 本次预测耗时(秒) |
| market.regime | string | "蓄水"/"平衡"/"放水" |
| market.regime_id | int | 0~4 GMM聚类编号 |
| market.pool | int | 当前奖池(元) |
| market.bet | int | 当前投注(元) |
| market.predicted_pool_range | [int,int] | 下期奖池预测90%~110%区间 |
| market.predicted_bet_range | [int,int] | 下期投注预测90%~110%区间 |
| predictions[].rank | int | 排名 1~N |
| predictions[].reds | [int×6] | 推荐红球 |
| predictions[].blue | int | 推荐蓝球 |
| predictions[].consistency | float | 一致性评分 0~1 |
| predictions[].cost | float | 庄家成本分 |
| predictions[].est_prize1 | int | 预期头奖注数 |
| predictions[].passed | bool | score>0.2通过 |
| popularity.hot | [int×10] | 热门号码 (按综合评分) |
| popularity.cold | [int×10] | 冷门号码 |
| popularity.birthday_effect | float | 生日号效应 (1.16x) |
| last_review | object|null | 上期回顾 (可null) |
| stats.total_candidates | int | 候选总数 (默认2000) |
| stats.top_score | float | 最高一致性评分 |
| stats.avg_score | float | Top-N平均评分 |

---

## 3. DataHub 内部数据结构 (engine/data_hub.py)

### 3a. red_feat [33, N, 8] —— 号码特征张量

`red_feat[num-1, t, :]` = 号码num在第t期的8维特征

| 通道 | 名称 | Python 类型 | 单位 | 说明 |
|------|------|------------|------|------|
| 0 | miss | np.int32 | 期 | 遗漏值 (距上次出现) |
| 1 | freq_10 | np.int32 | 次 | 近10期出现次数 |
| 2 | freq_20 | np.int32 | 次 | 近20期出现次数 |
| 3 | freq_50 | np.int32 | 次 | 近50期出现次数 |
| 4 | trend | np.int32 | 期 | 遗漏变化 (+=变冷, -=变热) |
| 5 | pool_corr | np.float64 | — | 当前奖池区间下的出现概率 |
| 6 | inherit_rate | np.float64 | — | 该号码跨期重复的概率 |
| 7 | rel_miss | np.float64 | — | miss / max(1, t+1) |

**计算方式**: `_build_red_features()` 方法
- 遍历每期每个号码
- miss = t - last_appear_t
- freq = 滑动窗口计数 (10/20/50)
- trend = miss_t - miss_{t-1}
- pool_corr = 该号码在4个奖池分位区间的条件概率
- inherit_rate = 全局统计: 该号码在上期出现后本期又出现的频率

### 3b. market [N, 14] —— 市场状态矩阵

`market[t, :]` = 第t期的14维市场状态

| 索引 | 字段名 | 类型 | 单位 | 计算公式 |
|------|--------|------|------|---------|
| 0 | pool | float64 | 亿 | pool[t] / 1e8 |
| 1 | bet | float64 | 亿 | bet[t] / 1e8 |
| 2 | p1c | float64 | 注 | prize1_cnt[t] |
| 3 | p1a | float64 | 万 | prize1_amt[t] / 1e4 |
| 4 | p2c | float64 | 注 | prize2_cnt[t] |
| 5 | p2a | float64 | 万 | prize2_amt[t] / 1e4 |
| 6 | prize1_total | float64 | 亿 | p1c × p1a / 1e8 |
| 7 | major_prize_ratio | float64 | % | (prize1_total+prize2_total)/bet×100 |
| 8 | pool_bet_ratio | float64 | — | pool / bet |
| 9 | bet_elasticity | float64 | % | bet[t] / (pool[t-1]+1) × 100 |
| 10 | span | float64 | — | reds[-1]-reds[0] |
| 11 | sum | float64 | — | sum(reds) |
| 12 | small_count | float64 | 个 | #reds ≤ 14 |
| 13 | cons_pairs | float64 | 对 | 连号对数 |

### 3c. profiles [N × dict] —— 号码画像

每期画像 (共14个特征):
```python
{
    'span': int,      # 跨度
    'sum': int,       # 和值
    'odd': int,       # 奇数个数
    'cons': int,      # 连号对数
    'z1': int,        # 一区(1-11)个数
    'z2': int,        # 二区(12-22)个数
    'z3': int,        # 三区(23-33)个数
    'bday': int,      # 生日号(1-31)个数
    'non_bday': int,  # 非生日号(32-33)个数
    'prime': int,     # 质数个数
    'same_tail': int, # 同尾号对数
    'blue': int,      # 蓝球
}
```

---

## 4. 配置参数 (config.py)

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| SSQ_FILE | str | data/ssq_all.json | 数据文件路径 |
| PREDICT_FILE | str | data/predict_result.json | 预测结果输出路径 |
| SSQ_URL | str | (500.com) | 数据源URL |
| FETCH_LIMIT | int | 5000 | 爬取上限 |
| PORT | int | 8080 | Web服务端口 |
| HOST | str | 0.0.0.0 | 监听地址 |
| POOL_LOW | float | 2e8 | 蓄水/平衡分界 |
| POOL_HIGH | float | 10e8 | 平衡/放水分界 |
| BIRTHDAY_EFFECT | float | 1.16 | 生日号效应量 |
| N_CANDIDATES | int | 10000 | 候选采样数 |
| TOP_N | int | 10 | 推荐输出数 |
| UPDATE_HOUR | int | 0 | 每日更新小时 |
| UPDATE_MINUTE | int | 0 | 每日更新分钟 |

---

## 5. SQLite 数据库 (ssq.db)

引擎启动时自动从 JSON 迁移。包含 draws、predict_batch、predictions 三张表及加速索引。

### 5a. draws 表（开奖数据）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| issue | TEXT UNIQUE | 期号 |
| red1~red6 | INT | 6个红球 |
| blue | INT | 蓝球 |
| pool | BIGINT | 奖池奖金(元) |
| bet | BIGINT | 总投注额(元) |
| prize1_cnt | INT | 一等奖注数 |
| prize1_amt | BIGINT | 一等奖奖金(元) |
| prize2_cnt | INT | 二等奖注数 |
| prize2_amt | BIGINT | 二等奖奖金 |
| draw_date | TEXT | 开奖日期 |
| span | INT | 红球跨度 |
| sum_val | INT | 红球和值 |
| zone1~zone3 | INT | 三区分布 |
| odd_cnt | INT | 奇数个数 |
| cons_pairs | INT | 连号对数 |
| bday_cnt | INT | 生日号(1-31)个数 |

### 5b. predict_batch 表（批次流水）

| 列名 | 类型 | 说明 |
|------|------|------|
| batch_id | INTEGER PK | 自增流水号 |
| created_at | TEXT | 创建时间 |
| target_issue | TEXT | 目标期号 |
| total_entries | INT | 总条数 |

### 5c. predictions 表（预测对照）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| batch_id | INT | 批次号(关联predict_batch) |
| entry_type | TEXT | 'single' 或 'compound' |
| rank | INT | 排名(1~12)或代号(A~D) |
| reds | TEXT | 红球JSON数组 |
| blue | INT/TEXT | 蓝球值或JSON数组(复式) |
| reds_count | INT | 红球数 |
| blues_count | INT | 蓝球数 |
| consistency/cost | REAL | 评分/成本 |
| total_cost/combos | INT | 总金额/注数 |
| hit_red/hit_blue | INT | 实际命中数 |

### 加速索引

```sql
CREATE INDEX idx_prize1_cnt ON draws(prize1_cnt);
CREATE INDEX idx_pool ON draws(pool);
CREATE INDEX idx_bet ON draws(bet);
CREATE INDEX idx_issue ON draws(issue);
CREATE INDEX idx_pred_batch ON predictions(batch_id);
CREATE INDEX idx_pred_target ON predictions(target_issue);
```

## 6. 引擎模块函数签名

### engine/data_hub.py
```python
class DataHub:
    def load(path=None) -> DataHub       # 加载数据 (单例)
    def get_red_features(t) -> [33,8]    # t期号码特征
    def get_market_state(t) -> [14]      # t期市场状态
    def get_profile(t) -> dict           # t期号码画像
    def pool_state(t) -> int             # 0枯竭~4超高
    def pool_state_name(t) -> str        # 中文名
    def append_new(row_dict)             # 追加新期
    latest_t, latest_issue               # 属性
```

### engine/market.py
```python
class MarketModel:
    def get_regime(t) -> int             # Regime编号 0~4
    def get_pool_state(t) -> str         # "蓄水/平衡/放水"
    def get_regime_description(t) -> dict # 完整描述
    def impulse_response(pool_shock)     # 脉冲响应
    def predict_bet(pool) -> float       # 投注预测
    def get_markov_state(t) -> int       # Markov态
    def forward_markov(state_k, steps)   # Markov前推
    def get_transition_prob(from, to)    # 转移概率
```

### engine/numbers.py
```python
class NumberModel:
    def get_unconditional_dist() -> dict            # 无条件分布
    def get_conditional_dist(pool_state) -> dict     # 条件分布
    def cost_score(reds) -> float                   # 成本分
    def estimate_prize1(reds, bet_amount) -> int     # 头奖估算
    def sample_candidates(n, pool_state) -> list     # 候选采样
    def get_popularity_analysis(top_n) -> dict       # 热门分析
```

### engine/validator.py
```python
class Validator:
    def forward(reds, bet_amount) -> int                     # 前向
    def backward(prize1_count, top_k) -> dict                # 反向
    def consistency_score(reds, regime, bet) -> float        # 一致性
    def batch_validate(candidates) -> list                   # 批量验证
    def backtest(n_test) -> dict                             # 历史回测
```

### engine/predictor.py
```python
class Predictor:
    def run(n_candidates) -> dict    # 完整预测流水线
    def save(report)                 # 保存JSON
    def load_saved() -> dict         # 加载已保存结果
```
