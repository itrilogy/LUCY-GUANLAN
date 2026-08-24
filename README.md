<div align="center">
  <img src="web/static/brand/favicon.svg" width="88" height="88" alt="观澜 · GuanLan" />
  &nbsp;&nbsp;
  <img src="web/static/brand/luxi-lab-main.svg" width="88" height="88" alt="鹿溪联合创新实验室" />
</div>

<h1 align="center">观澜 · GuanLan</h1>

<p align="center">
  <strong>观澜 · GuanLan（双色球市场分析）</strong><br/>
  <em>观水有术，由表及澜</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Product-观澜%20GuanLan-E74C3C" alt="product" />
  <img src="https://img.shields.io/badge/Lab-鹿溪联合创新实验室-0D5E42" alt="lab" />
  <img src="https://img.shields.io/badge/Version-V1.0-f1c40f" alt="version" />
  <img src="https://img.shields.io/badge/Stack-Python%20%7C%20Flask%20%7C%20NumPy-blue" alt="stack" />
</p>

<p align="center">
  <b>鹿溪联合创新实验室（LUXI Joint Innovation Lab）</b> 出品<br/>
  工程目录 <code>ssq_predictor</code> · 基于公开历史数据的本地 Web 分析工具
</p>

<p align="center">
  <img src="web/static/brand/logo.svg" width="360" alt="观澜 · GuanLan 横版字锁" />
</p>

---

## 方法边界（诚实声明）

- **可分析**：奖池 / 投注 / 头奖注数等**市场状态**与组合空间拥挤度
- **近随机**：红蓝球开奖本身接近真随机
- **一致性 / final 等评分** = 模型内部自洽或结构排序，**不是中奖预言**

详细用户说明见软著/发行手册（文末链接）。

---

## 快速开始

在 **`ssq_predictor` 目录**下执行（本仓库根即该目录时直接用）：

```bash
# 1. 依赖（首次或 requirements 变更时）
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 可选：校验本地数据
make check

# 3. 启动 Web 服务（日常使用主入口）
make serve
```

浏览器打开：**http://localhost:8080**

停止服务：在运行 `make serve` 的终端按 **`Ctrl+C`**。

---

## `make serve` 说明

| 项 | 说明 |
|----|------|
| **作用** | 启动本地 Flask Web 分析服务 |
| **等价命令** | `python3 scripts/cli.py serve` |
| **默认地址** | `http://0.0.0.0:8080` → 本机访问 `http://localhost:8080` |
| **会做什么** | 加载 `data/` 历史数据与模型；按配置决定是否后台爬取；注册开奖日定时更新；提供页面与 API |
| **不会做什么** | 不跑 `make test` / `make cutover`；不替代 CLI 全量 `make update`（更新可在页面点「更新」） |

### 启动时行为摘要

1. 读取 `data/ssq_all.json` 与 SQLite，初始化市场/号码/验证引擎  
2. 应用 `config.py` 与 `data/eval/scoring_defaults.json`（cutover 结果，若有）  
3. `STARTUP_FETCH=auto`：数据可能过期时**后台**爬取；失败则继续用本地数据  
4. 默认 **`EVOLUTION_MODE=off`**：页面「全量(研究)」禁用（可用环境变量打开）  
5. 进程保持运行期间，**周二 / 周四 / 周日 22:00** 自动数据更新（soft reinit）  

### 常见问题

| 现象 | 处理 |
|------|------|
| 端口被占用 | 修改 `config.py` 中 `PORT`，或结束占用 8080 的进程 |
| 页面无 LOGO | 确认 `web/static/brand/` 完整（自包含，无外链） |
| 依赖缺失 | 重新 `pip install -r requirements.txt` |
| 必须在本目录执行 | 在含有 `Makefile` 的 `ssq_predictor/` 下运行 |

更完整的安装、升级、生产部署见：  
[`docs/release/02-安装部署手册.md`](docs/release/02-安装部署手册.md)  
操作界面说明见：  
[`docs/soft-copyright/03-用户操作手册-V1.0.md`](docs/soft-copyright/03-用户操作手册-V1.0.md)

---

## Make / CLI 命令一览

所有 `make` 目标均在 **`ssq_predictor/`** 下执行。  
等价 CLI：`python3 scripts/cli.py <子命令>`（**不要**使用 `python -m scripts`）。

| 命令 | 作用 | 典型场景 |
|------|------|----------|
| **`make serve`** | 启动 Web（Flask） | **日常打开用** |
| `make help` | 打印目标列表 | 查看有哪些命令 |
| `make check` | 数据校验 + 引擎冒烟 | 启动前自检 |
| `make update` | 爬取 + **full** 重建 + 预测 | 命令行完整更新 |
| `make data-only` | 仅爬取合并数据 | 只要最新开奖、不预测 |
| `make predict` | 仅用本地数据重跑预测 | 离线重算 |
| `make test` | `pytest` 自动化测试 | 改代码后 / 提交前 |
| `make eval` | walk-forward 冒烟 KPI | 看指标是否正常 |
| `make cutover` | G1–G5 门禁并写默认评分 | 决定是否默认 multi |
| `make migrate-rank` | predictions rank 迁移 | 旧库升级 |

```bash
make update      # 爬取 + full 重建 + 预测
make data-only   # 仅数据
make predict     # 仅预测
make check       # 校验
make test        # 测试
make eval        # 评估冒烟
make cutover     # 门禁 + scoring_defaults
make serve       # Web 服务
```

### 命令关系（怎么选）

| 你想… | 用 |
|--------|-----|
| 打开网站用界面 | **`make serve`** |
| 本机不装依赖、容器跑 | `docker compose up --build` |
| 只更新开奖数据 | `make data-only` 或页面「更新」 |
| 确认代码没坏 | `make test` |
| 重算默认评分策略 | `make cutover` |

---

## 数据更新

| 方式 | 说明 |
|------|------|
| Web「📥更新」 | 与 `GET /api/update` 同链路（爬取 + 预测） |
| `make update` | CLI 完整更新；模型 **full** 重建 |
| 定时任务 | 服务运行中：二/四/日 **22:00** 自动更新 |
| 启动检查 | `STARTUP_FETCH=auto` 时数据偏旧则后台爬取 |

数据文件主要在 `data/`（`ssq_all.json`、`ssq.db`、报告缓存等）。请定期备份。

---

## 评分默认与 cutover

默认由 [`data/eval/scoring_defaults.json`](data/eval/scoring_defaults.json) 控制（`make cutover` 写入）。  
Cutover 为 **go** 时：默认 `SCORING_MODE=multi`、`EVOLUTION_MODE=off`、条件反向。

```bash
make cutover   # G1–G5 → cutover_decision.md + scoring_defaults.json
make eval      # → data/eval/wf_smoke_latest.json
python3 scripts/calibrate_forward_alpha.py
```

环境变量覆盖（改完需**重启** `make serve`）：

```bash
export SSQ_SCORING_MODE=legacy
export SSQ_EVOLUTION_MODE=legacy_consistency   # 允许全量进化
export SSQ_SAMPLE_WEIGHTED=1                   # 近窗加权采样
export SSQ_SAMPLE_BLUE_MODE=empirical
export SSQ_FEATURES_CACHE=0                    # 关闭特征缓存
```

---

## Docker

```bash
docker compose up --build
# 访问 http://localhost:8080
# 单 worker gunicorn（与工程约定一致）
```

数据可挂载 `./data` 持久化。容器内默认不自动外网爬取（见 `docker-compose.yml`）。

---

## 目录结构

```
ssq_predictor/
├── app.py                 # Flask 入口 + 调度
├── config.py              # 配置与 cutover 覆盖
├── Makefile
├── Dockerfile / docker-compose.yml
├── engine/                # 分析引擎
├── scripts/               # cli / crawl / migrate / calibrate
├── tests/
├── web/
│   ├── static/brand/      # 品牌资源（完整自包含）
│   └── templates/
├── docs/                  # 工程 + 软著 + 发行
└── data/                  # 本地数据与评估产物
```

---

## 品牌标识

运行时与 README 均使用仓库内 **完整自包含** 资源（无外链图床）。

| 用途 | 路径 |
|------|------|
| 产品 favicon | [`web/static/brand/favicon.svg`](web/static/brand/favicon.svg) |
| 产品横版字锁 | [`web/static/brand/logo.svg`](web/static/brand/logo.svg) |
| **实验室主 LOGO** | [`web/static/brand/luxi-lab-main.svg`](web/static/brand/luxi-lab-main.svg) |
| 兼容 URL | [`web/static/brand/luxi-lab-lockup.svg`](web/static/brand/luxi-lab-lockup.svg)（与主 LOGO 同源） |
| 说明 | [`web/static/brand/README.md`](web/static/brand/README.md) |

官方主标源头（品牌治理，**非**运行依赖）：`Obsidian/.../鹿溪联合实验室/LUXI LAB.svg`  
平行归档：`Obsidian/.../双色球-市场分析-品牌资产/`（与见鹿、听默同级）

<p align="center">
  <img src="web/static/brand/luxi-lab-main.svg" width="120" height="120" alt="鹿溪联合创新实验室 LUXI Lab" />
  <br/>
  <sub>鹿溪联合创新实验室 · LUXI Joint Innovation Lab</sub>
</p>

---

## 改造与文档

- 工程改造计划（已落地）：[`docs/ENGINEERING_RENOVATION_PLAN.md`](docs/ENGINEERING_RENOVATION_PLAN.md)  
- Cutover 决策：[`data/eval/cutover_decision.md`](data/eval/cutover_decision.md)  

### 软著与发行

总索引：[`docs/soft-copyright/00-软著与发行文档目录.md`](docs/soft-copyright/00-软著与发行文档目录.md)

| 类型 | 路径 |
|------|------|
| 用户操作手册（软著） | [`docs/soft-copyright/03-用户操作手册-V1.0.md`](docs/soft-copyright/03-用户操作手册-V1.0.md) |
| 安装部署手册 | [`docs/release/02-安装部署手册.md`](docs/release/02-安装部署手册.md) |
| 用户使用手册（发行） | [`docs/release/03-用户使用手册-发行版.md`](docs/release/03-用户使用手册-发行版.md) |
| 免责声明 | [`docs/release/06-免责声明与使用规范.md`](docs/release/06-免责声明与使用规范.md) |

软件全称：**观澜 · GuanLan（双色球市场分析）**　版本：**V1.0**

---

<p align="center">
  <img src="web/static/brand/luxi-lab-main.svg" width="72" height="72" alt="LUXI Lab" />
  <br/>
  <sub>© 鹿溪联合创新实验室 · 本工具不作中奖承诺</sub>
</p>
