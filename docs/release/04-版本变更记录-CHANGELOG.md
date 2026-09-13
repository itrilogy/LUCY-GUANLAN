# 版本变更记录（CHANGELOG）

**软件全称：双色球市场分析系统**

格式参考 Keep a Changelog；版本语义：主.次.修订。

---

## [V1.1] — 2026-09-13

### 新增与重构（LUXI Design 范式对齐）

- **设计令牌系统**：
  - 新增 `web/static/tokens.css`，全量接入 LUXI Core 四色（`#0D5E42`、`#F5F7FA`、`#00D2FF`、`#F1C40F`）与 `[data-product="guanlan"]` Accent（`#E74C3C` / `#3498DB`）；
  - 吸收 `DESIGN_AMENDMENT_DRAFT_v1.1` 补正令牌：文字专用色（面字分离，对比度保证 ≥ 4.5:1）、控件 5 档高度（`--control-xs/sm/md/lg/xl`）与输入框专用变量；
  - 支持 `dark`（深色·数据）、`light`（亮色·工作台）、`ink`（沉浸·专注）三套主题及两档密度动态切换与本地状态持久化。
- **品牌方标规范（GUANLAN 12 款方标对齐）**：
  - 重绘 `web/static/brand/favicon.svg` 与 `logo.svg`，完全对齐 12 款产品方标中 GUANLAN 权威标准：48×48 鹿溪绿圆角砖 + 红蓝双球（红左下、蓝右上） + 底部进化蓝溪流（`.stream`） + 右上角金色源启星（`.star`）；
  - 移除了产品顶栏、页脚与 README 中误用的官方写实主标 `luxi-lab-main.svg` 及其白色方框；
  - 引入官方统一符号标 `luxi-lab.svg` / `luxi-lab-gold.svg`，落实角本位符号标无方框原则；
  - `README.md` 顶栏落实 64×64 双标等大居中（观澜产品方标 × 实验室符号标）。
- **序列推荐控件重构**：
  - 彻底解决原 3 列窄网格排版挤压导致综合评分与自洽度文字截断的缺陷；
  - 全新设计为专业舒展的**双列分层推演卡片**系统（`.pred-card`），单卡空间提升至 ~550px；
  - 顶栏清晰呈现序列号、算法分类徽章与突出展示的综合评分；
  - 核心出球轨道采用 28px 饱满大球与规范呼吸间距，支持单注快速复制；
  - 底部指标矩阵网格平铺展示抗拥挤度、组合结构、市场匹配与模型自洽度，无任何文字截断。
- **视觉降噪与口径规范**：
  - 收敛按钮层级，落实“每屏一个 Primary（鹿溪绿实底白字）”；
  - 全面清除界面功能性 Emoji，替换为语义矢量 SVG 图标；
  - 所有图表容器补充结构化口径说明，顶栏常驻“非中奖预言”方法边界声明。

---

## [V1.0] — 2026-08-11

### 新增

- Web 主界面：推荐、复式、历史图、期号浏览、预测对照  
- 数据爬取、JSON/SQLite 合并、命中回填  
- 市场 Regime、反馈、Markov；号码特征与采样  
- 双向验证 + prize LUT；可选多目标排序（实验闸 / cutover）  
- 开奖日调度与启动智能更新；soft reinit  
- CLI / Makefile：update、predict、check、serve、test、eval、cutover  
- Walk-forward 对比评估 + G1–G5 cutover 门禁产物  
- 特征缓存 features.npz；加权采样 / 经验蓝球（环境开关）  
- Dockerfile + docker-compose（gunicorn -w 1）  
- 品牌资源：产品 favicon + 官方实验室主 LOGO 本地自包含  
- 软著与发行文档集  

### 说明

- 默认 `EVOLUTION_MODE=off`  
- 默认评分：`data/eval/scoring_defaults.json`（cutover 结果）覆盖；未 cutover 时为 legacy  
- 研究脚本归档至上层 `research/archive/`  

### 兼容性

- 首发版本，无前序兼容承诺  

---

## [未发布]

### 计划

- Walk-forward 完整门禁与评分默认策略评估  
- 生产部署模板（systemd/Docker）可选  

---

## 版本对照

| 版本 | 软著版本号 | 备注 |
|------|------------|------|
| V1.1 | V1.0 | 设计范式对齐与推荐控件重构（LUXI Design v1.1） |
| V1.0 | V1.0 | 首登建议版本 |
