# 推理预测算法说明

## 整体流程

```
启动 → DataHub加载 → MarketModel初始化 → 等待用户操作
                                                 ↓
用户点击「快速推理」 → 采样2000候选 → 双向验证 → 排序Top10 → 复式规划 → 输出报告
                                                 ↓
用户点击「🧬全量」    → 遗传进化30代 → 最佳权重 → 同上流程（用进化权重）
                                                 ↓
用户点击「📥更新」    → 爬取新数据 → 刷新DataHub → 同上流程
```

---

## 一、数据准备（启动时一次性完成）

### DataHub.load()

| 预计算内容 | 维度 | 说明 |
|-----------|------|------|
| 号码特征矩阵 | [33, 3481, 8] | 每期每个号码的遗漏值/近10期频/近20期频/近50期频/趋势/奖池相关/继承率/相对遗漏 |
| 市场状态向量 | [3481, 14] | 奖池/投注/头奖/二等奖/奖池头奖比/投注弹性/跨度/和值/小号数/连号数 |
| 号码画像 | [3481, dict] | 跨度/和值/奇数/连号/三区分布/质数/同尾/蓝球 |
| 蓝球遗漏 | [16, 3481] | 每个蓝球相对每期的遗漏期数 |

### MarketModel.__init__()

| 模型 | 方法 | 输出 |
|------|------|------|
| GMM 5类 | `_build_regime_model()` | 5类Regime标签、每类统计 |
| 线性回归 | `_build_feedback()` | 奖池→投注、投注→头奖 系数 |
| KMeans 12态 | `_build_markov()` | 12态Markov链 T_fwd/T_bwd，5类Regime转移矩阵 |

---

## 二、候选采样（2000组）

`NumberModel.sample_candidates(n, pool_state)`

### 条件分布微调

根据奖池水位调整号码概率权重：

```python
# 蓄水期(奖池低): 倾向冷门号 → 减少多人投注
# 放水期(奖池高): 倾向热门号 → 增加多人中奖

probability_weight[num] = baseline + adjustment_by_pool_state
```

影响因素：

| 因子 | 权重 | 说明 |
|------|------|------|
| 遗漏趋势 | 0.3 | 倾向遗漏值正在增加的号码（变冷） |
| 近期频率 | 0.3 | 倾向近20期高频号码（热号） |
| 生日号效应 | 1.16x | 1-31号段被更多人投注的概率乘数 |
| 奖池相关 | 0.2 | 在当前奖池区间下该号码的历史出现概率 |

### 拒绝采样

从 33 个球中按加权概率抽样 6 个，升序排列，去重，生成一组候选。

---

## 三、双向验证（核心算法）

对每组候选号码 `(reds, blue)`：

### 3a. 前向通道

```python
def forward(reds, bet_amount):
    cost = _raw_cost_score(reds)  # 号码→成本分
    est_prize = cost_to_prize_regression.predict([[cost]])  # 成本分→头奖注数
    return int(est_prize)
```

成本分公式：

```
cost = birthday_cnt × 0.3          # 生日号(1-31)个数
     + cons_pairs × 0.2             # 连号对数
     + (7 - span/5) × 0.15          # 小跨度（越小成本越高）
     + recent_freq × 0.2            # 近20期出现频率
     - big × 0.3                    # 大号(32-33)个数（低成本，少人买）
     - small × 0.1                  # 小号修正
```

成本分 → 头奖注数的回归模型（LinearRegression，历史数据拟合）：
- 相关系数 r=0.037 (p=0.031)
- 高成本期(前25%)平均头奖 8.3注 vs 低成本期(后25%) 7.0注

### 3b. 反向通道

```python
def backward(prize1_count):
    # SQLite索引查询
    SELECT id, prize1_cnt FROM draws
    ORDER BY ABS(prize1_cnt - ?) LIMIT 20

    # 统计这些期的"开奖前"市场特征
    return {
        'regime_dist': {0:0.1, 2:0.7, 4:0.2},  # 5类Regime占比
        'avg_pool_before': 4.2e8,               # 前一期均奖池
        'avg_bet_before': 3.1e8,                # 前一期均投注
    }
```

SQLite 索引 `idx_prize1_cnt` 将查询从 `O(3481)` 降至 `O(log N)`。

### 3c. 一致性评分

```python
score = regime_prob × 0.7 + concentration × 0.3

regime_prob = 反向推得的Regime中，当前Regime的概率占比
              例如当前Regime=2，反向分布中Regime 2占70% → regime_prob=0.7

concentration = 1 - entropy / max_entropy
              反向Regime分布的集中度（单一Regime越集中越好）
```

分数范围 `[0, 1]`，越高表示该号码组合在当前市场状态下越**自洽**。

### 3d. T_bwd 调整（Regime 转移一致性）

```python
tbd_prior = regime_T_bwd[current_regime]  # 当前Regime的前一期期望分布
# 例如 regime 2 → 前一期最可能是 regime 2(55%) 或 1(30%)

overlap = 0
for regime_k, prob in backward_result['regime_dist'].items():
    overlap += min(prob / total, tbd_prior[regime_k])

tbd_bonus = overlap × 0.2  # 最高 +20%
adjusted_score = min(1.0, score × (1.0 + tbd_bonus))
```

如果候选号码推得的"前一期市场状态"与 T_bwd 期望的状态一致 → 加分。
这确保了前后期的 Regime 转移符合历史统计规律。

---

## 四、排序与扩展

### Top-10

2000 候选按 `adjusted_score` 降序排序，取前 10 作为推荐号码。

### 第 11-12 注

基于 Top-10 红球的频率统计：

```python
# #11: 出现频率最高的6个红球 + 出现频率最高的蓝球
# #12: 出现频率第7-12名的6个红球 + 出现频率第二高的蓝球
```

### 复式推荐（4套）

基于全部 2000 候选的加权覆盖率优化：

```
目标: 选择红球集R和蓝球集B, 使:
  Score(R,B) = Σ consistency(c) × |c.reds∩R|/6 × blue_match(c,B)

贪心算法:
  1. 初始基底：Top-6 最高权重红球
  2. 每步选"边际覆盖率/成本增量"比率最高的球加入
  3. 到预设球数停止
```

每套复式也做独立验证：

```python
def _compound_validation(reds, blues, candidates):
    # 前向: 复式整体预期头奖
    avg_est_prize = mean(forward(c) for c in covered_candidates)
    # 反向: 从整体头奖推Regime
    back_result = backward(avg_est_prize)
    # 评分: 当前Regime在反向分布中的概率
    score = regime_prob × 0.7 + concentration × 0.3
```

---

## 五、全量遗传进化（可选）

### 基因结构

```python
class PatternGene:
    w_red[8]       # 红球8个特征的权重: [遗漏,近10期频,近20期频,近50期频,趋势,奖池相关,继承率,相对遗漏]
    w_blue[4]      # 蓝球4个特征的权重
    inherit_bias   # 偏好/回避上期号码
    span_bias      # 跨度修正
```

### 进化参数

| 参数 | 值 |
|------|-----|
| 种群 | 200 |
| 代数 | 30 |
| 训练期 | 后 696 期（test_ratio=0.2） |
| 适应度 | 双向验证一致性评分（前向→反向→评分） |
| 选择 | 保留 Top-15 精英 |
| 变异率 | 30% |
| 杂交率 | 70% |
| 预计耗时 | ~10 分钟 |

### 进化流程

```
for 30 代:
  1. 评估: 每个基因在 696 期测试集上
     predict() → forward() → backward(LUT查表) → consistency_score
  2. 选择: Top-15 精英直接进入下一代
  3. 繁殖:
     70% 杂交: 两个精英父母各继承一半权重
     30% 变异: 基因复制后随机扰动权重
  4. 进度写入: data/progress.json → 前端轮询
```

### LUT 加速

预计算 `backward_lut[0..200]`（每个可能头奖注数的反向结果），进化时直接查表。
结果与扫描 3481 期完全等价，复杂度从 `O(2000×696×3481)` 降至 `O(2000×696×查表)`。

---

## 六、页面内容

完成推理后，页面按以下顺序渲染：

```
1. 宏观仪表盘（5 卡片）
   - 市场状态 + 奖池 + 投注额 + 热门号码 + 按钮区

2. 推荐号码（12 注，3 列网格）
   - 第 1-10 注: 双向验证排序
   - 第 11-12 注: Top-10 频率聚合

3. 复式推荐（4 套，横向自适应）
   - 经济/标准/豪华/高频聚合

4. 复式构建步骤（贪心扩展轨迹）

5. 区间分布概况
   - 🔴 红球三区（1-11 / 12-22 / 23-33）
   - 🔵 蓝球四区（1-4 / 5-8 / 9-12 / 13-16）

6. 历史趋势
   - 红球频率图 + 蓝球频率图（SVG，Y轴 min-1 ~ max+1）
   - 奖池曲线（SVG 折线，Y轴 0 ~ max+1）
   - 市场状态分布（5 类 Regime + 样本号码）

7. 反向回溯 T_bwd
   - 当前 Regime → -1步 → -2步 → ... → -5步
   - 每步显示最概然 Regime、概率、奖池区间

8. 每期号码分布（33红+16蓝 网格，分页）
```
