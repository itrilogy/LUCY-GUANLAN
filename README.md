<div align="center">
  <img src="web/static/brand/favicon.svg" width="88" height="88" alt="双色球市场分析" />
  &nbsp;&nbsp;
  <img src="web/static/brand/luxi-lab-main.svg" width="88" height="88" alt="鹿溪联合创新实验室" />
</div>

<h1 align="center">双色球市场分析系统</h1>

<p align="center">
  <strong>市场状态 · 组合结构 · 诚实评估</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Product-双色球市场分析-E74C3C" alt="product" />
  <img src="https://img.shields.io/badge/Lab-鹿溪联合创新实验室-0D5E42" alt="lab" />
  <img src="https://img.shields.io/badge/Version-V1.0-f1c40f" alt="version" />
  <img src="https://img.shields.io/badge/Stack-Python%20%7C%20Flask%20%7C%20NumPy-blue" alt="stack" />
</p>

<p align="center">
  <b>鹿溪联合创新实验室（LUXI Joint Innovation Lab）</b> 出品<br/>
  工程目录 <code>ssq_predictor</code> · 基于 500.com 等公开历史数据的本地 Web 分析工具
</p>

<p align="center">
  <img src="web/static/brand/logo.svg" width="360" alt="双色球市场分析 横版字锁" />
</p>

---

## 方法边界（诚实声明）

- **可分析**：奖池 / 投注 / 头奖注数等**市场状态**
- **近随机**：红蓝球开奖本身
- **一致性评分** = 前向/反向**自洽**，**不是中奖概率**

---

## 启动

```bash
cd ssq_predictor
pip install -r requirements.txt
make serve
# 或: python3 scripts/cli.py serve
# 访问 http://localhost:8080
```

## 日常命令

```bash
make update      # 爬取 + full 重建 + 预测（CLI）
make data-only   # 仅爬取合并
make predict     # 仅预测
make check       # 数据校验 + 冒烟
make test        # pytest
make eval        # walk-forward smoke KPI
```

等价：`python3 scripts/cli.py <subcommand>`（**不要** `python -m scripts`）。

## 数据更新

- 开奖日（二/四/日）22:00 自动爬取（进程内 soft reinit；到期 full）
- Web「更新」与 `GET /api/update` 同链路
- CLI 数据变更后**始终 full** 重建模型

## 目录

```
ssq_predictor/
├── app.py
├── config.py
├── Makefile
├── engine/          # data_hub, crawler, market, numbers, validator, predictor, evolution
├── scripts/         # cli.py, crawl_update.py, init_*
├── tests/
├── web/
│   ├── static/brand/   # favicon / logo / 鹿溪主 LOGO（完整自包含）
│   └── templates/
├── docs/            # 工程说明 + 软著/发行文档
└── data/
```

研究脚本已归档到上层仓库 `research/archive/`（若存在 monorepo 布局）。

---

## 品牌标识

运行时与本 README 均使用仓库内 **完整自包含** 资源（无外链图床、无 Obsidian 运行时依赖）。

| 用途 | 路径 |
|------|------|
| 产品 favicon / 顶栏 | [`web/static/brand/favicon.svg`](web/static/brand/favicon.svg) |
| 产品横版字锁 | [`web/static/brand/logo.svg`](web/static/brand/logo.svg) |
| **实验室主 LOGO** | [`web/static/brand/luxi-lab-main.svg`](web/static/brand/luxi-lab-main.svg)（官方 `LUXI LAB.svg` 拷贝） |
| 兼容路径 | [`web/static/brand/luxi-lab-lockup.svg`](web/static/brand/luxi-lab-lockup.svg)（与主 LOGO 同源） |
| 说明 | [`web/static/brand/README.md`](web/static/brand/README.md) |

官方主标源头（品牌治理，非运行依赖）：`Obsidian/departments/lab/鹿溪联合实验室/LUXI LAB.svg`  
平行归档：`Obsidian/departments/lab/双色球-市场分析-品牌资产/`（与见鹿、听默同级）

<p align="center">
  <img src="web/static/brand/luxi-lab-main.svg" width="120" height="120" alt="鹿溪联合创新实验室 LUXI Lab" />
  <br/>
  <sub>鹿溪联合创新实验室 · LUXI Joint Innovation Lab</sub>
</p>

---

## Phase 2 实验评分（默认关闭）

```bash
# 允许 multi/dual（本地实验）
export SSQ_ALLOW_EXPERIMENTAL_SCORING=1
export SSQ_SCORING_MODE=multi          # 或 dual
export SSQ_BACKWARD_MODE=conditional   # 可选条件近邻反向
make predict
# 或浏览器控制台: window.SSQ_MODE='multi' 后点「快速」
```

```bash
make eval   # → data/eval/wf_smoke_latest.json
python3 scripts/calibrate_forward_alpha.py
```

## 改造路线

见 [`docs/ENGINEERING_RENOVATION_PLAN.md`](docs/ENGINEERING_RENOVATION_PLAN.md)（Phase 0–4 / PR-00…17）。  
Phase 2 多目标排序默认仍 `legacy`。

## 软著与发行文档

完整材料目录：

- **总索引**：[docs/soft-copyright/00-软著与发行文档目录.md](docs/soft-copyright/00-软著与发行文档目录.md)
- **软著**：申请指引、功能特点、用户操作手册、设计说明书、源程序鉴别说明、权属模板  
- **发行**：发行说明、安装部署、用户手册、CHANGELOG、开源声明、免责、测试摘要、品牌版权、Go/No-Go 清单  

软件全称：**双色球市场分析系统**　版本：**V1.0**

---

<p align="center">
  <img src="web/static/brand/luxi-lab-main.svg" width="72" height="72" alt="LUXI Lab" />
  <br/>
  <sub>© 鹿溪联合创新实验室 · 本工具不作中奖承诺</sub>
</p>
