# 版本变更记录（CHANGELOG）

**软件全称：双色球市场分析系统**

格式参考 Keep a Changelog；版本语义：主.次.修订。

---

## [V1.0] — 2026-08-11

### 新增

- Web 主界面：推荐、复式、历史图、期号浏览、预测对照  
- 数据爬取、JSON/SQLite 合并、命中回填  
- 市场 Regime、反馈、Markov；号码特征与采样  
- 双向验证 + prize LUT；可选多目标排序（实验闸）  
- 开奖日调度与启动智能更新  
- CLI / Makefile：update、predict、check、serve、test、eval  
- 品牌资源：产品 favicon + 官方实验室主 LOGO 本地自包含  
- 软著与发行文档集  

### 说明

- 默认评分模式 `legacy`  
- 研究脚本归档至仓库 `research/archive/`  

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
| V1.0 | V1.0 | 首登建议版本 |
