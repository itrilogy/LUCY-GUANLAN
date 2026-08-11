# 双色球市场分析（ssq_predictor）

鹿溪联合实验室出品 · 基于 500.com 历史数据的 Web 分析工具。

**方法边界（诚实声明）**  
- 可分析：奖池 / 投注 / 头奖注数等**市场状态**  
- 近随机：红蓝球开奖本身  
- 一致性评分 = 前向/反向**自洽**，**不是中奖概率**

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
│   ├── static/brand/   # favicon / logo / 鹿溪标
│   └── templates/
├── docs/            # 含 ENGINEERING_RENOVATION_PLAN.md
└── data/
```

研究脚本已归档到仓库根 `research/archive/`。

## 品牌

- 产品 favicon：`web/static/brand/favicon.svg`
- **实验室主 LOGO**：`web/static/brand/luxi-lab-main.svg`  
  官方源文件：`Obsidian/departments/lab/鹿溪联合实验室/LUXI LAB.svg`
- 几何实验标（非主标/已更名）：`luxi-lab-mark-geometric-legacy.svg`

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
make eval   # walk-forward smoke KPI → data/eval/wf_smoke_latest.json
python3 scripts/calibrate_forward_alpha.py
```

## 改造路线

见 [`docs/ENGINEERING_RENOVATION_PLAN.md`](docs/ENGINEERING_RENOVATION_PLAN.md)（Phase 0–4 / PR-00…17）。  
本交付覆盖 Phase 0–1 主路径；Phase 2 多目标排序默认仍 `legacy`。

## 软著与发行文档

完整材料目录：

- **总索引**：[docs/soft-copyright/00-软著与发行文档目录.md](docs/soft-copyright/00-软著与发行文档目录.md)
- **软著**：申请指引、功能特点、用户操作手册、设计说明书、源程序鉴别说明、权属模板  
- **发行**：发行说明、安装部署、用户手册、CHANGELOG、开源声明、免责、测试摘要、品牌版权、Go/No-Go 清单  

软件全称：**双色球市场分析系统**　版本：**V1.0**
