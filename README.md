# Energy Systems Portfolio · 电力系统与储能分析作品集

用 Python + [pandapower](https://www.pandapower.org/) 做电力系统潮流与 N-1 安全分析的个人学习项目集。
每个项目都独立放在 `projects/NN-<主题>/` 下，包含可复现的脚本、原始数据 CSV、图表和一份中文报告。

> 说明：这些是个人学习项目，用于练习建模与可复现分析流程，**不是**企业项目或实际工程咨询成果。
> IEEE 9 节点是标准测试算例，不代表真实区域电网。

## 项目索引

| 编号 | 项目 | 一句话结论 | 报告 |
|---|---|---|---|
| 01 | IEEE 9 节点潮流与 N-1 越限分析 | 基准无越限；断线 8 电压跌至 0.794 p.u. 最严重，断线 7 同时逼近电压与负载上限 | [REPORT](projects/01-ieee9-loadflow-n1/REPORT.md) |
| 02 | 储能接入对潮流与 N-1 安全性的影响 | 20 MW/80 MWh 储能放电可把线路 6 断线后的负载率从 95.94% 降到 87.12%；充电则会过载到 104.98% | [REPORT](projects/02-ieee9-storage-n1/REPORT.md) |

## 目录结构

```
energy-systems-portfolio/
├── README.md                 # 本文件：项目索引与使用说明
├── requirements.txt          # 运行依赖
├── docs/                     # 各项目报告的集中副本，方便快速浏览
├── projects/
│   ├── 01-ieee9-loadflow-n1/
│   │   ├── REPORT.md         # 项目报告（方法、结果、结论、限制）
│   │   ├── data/             # 计算输出的原始 CSV
│   │   ├── figures/          # 报告用图（PNG）
│   │   └── src/              # 可复现脚本
│   └── 02-ieee9-storage-n1/
│       ├── REPORT.md
│       ├── data/
│       ├── figures/
│       └── src/
```

## 快速开始

```bash
pip install -r requirements.txt

# 项目 01：基准潮流 + 9 条线路逐条 N-1 扫描
python projects/01-ieee9-loadflow-n1/src/n1_analysis.py
python projects/01-ieee9-loadflow-n1/src/make_figures.py

# 项目 02：储能 standby / 充电 / 放电 三模式对比 + N-1
python projects/02-ieee9-storage-n1/src/storage_analysis.py
python projects/02-ieee9-storage-n1/src/make_storage_figures.py
```

脚本会把结果写到对应项目的 `data/`、`figures/` 目录下。

## 统一的分析设定

- **算例**：pandapower 内置 `case9`（9 母线 / 9 线路 / 3 负荷 / 2 发电机 / 1 平衡节点）。
- **潮流**：牛顿-拉夫逊法，`max_iteration=10`，`tolerance_mva=1e-8`。
- **N-1**：逐条把线路设为 `in_service=False`，用 `copy.deepcopy(net)` 复制网络后重算交流潮流。
- **主判据**：母线电压 0.90–1.10 p.u.，线路负载率 ≤ 100%。
- **辅助判据**：母线电压 0.95–1.05 p.u.，用于观察运行裕度。
- **孤岛处理**：断线后若只剩平衡节点有有效结果，标记为「孤岛/无效」，不按「无越限」计入统计。

## 新增一个项目

1. 新建 `projects/NN-<短横线主题>/`（NN 递增，如 `03-load-growth-n1`）。
2. 放入 `src/`、`data/`、`figures/` 与 `REPORT.md`，报告沿用「项目目标 / 数据与方法 / 结果 / 关键发现 / 限制」五段式。
3. 在本文件的项目索引表里加一行。
4. 提交：`git add . && git commit -m "feat(03): <主题>" && git push`。

## 环境

- Python 3.10+，pandapower 3.x，pandas，matplotlib
- 开发环境：Windows + PowerShell；脚本本身跨平台

## 参考

- pandapower 文档：https://pandapower.readthedocs.io/
- IEEE 9 节点系统：pandapower 内置 `pandapower.networks.case9()`
