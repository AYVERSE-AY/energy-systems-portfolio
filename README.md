# Energy Systems Portfolio · 电力系统分析作品集

用 Python 与 [pandapower](https://www.pandapower.org/) 完成的电力系统静态分析项目。
每个项目独立放在 `projects/NN-<主题>/`，包含可复现脚本、原始结果数据、图表与技术报告。

> 均为个人学习项目，用于练习建模与可复现分析流程，不构成工程咨询成果；
> 标准测试算例的结果不代表真实电网的安全水平。

## 项目一览

| 编号 | 项目 | 研究问题 | 主要量化结果 | 报告 |
|---|---|---|---|---|
| 01 | [IEEE 9 节点潮流与线路 N-1 筛查](projects/01-ieee9-loadflow-n1/) | 逐条退出线路后，电压与负载率如何变化；哪些场景越限、孤岛或无有效结果 | 基准 0.9576–1.0034 p.u.、最大负载率 65.46%；N-1 最低电压 0.794 p.u.、最大负载率 97.86%；9 个场景中 6 个全网有效、2 个部分覆盖、1 个无有效结果 | [REPORT](projects/01-ieee9-loadflow-n1/REPORT.md) |
| 02 | [储能接入对潮流与 N-1 的影响](projects/02-ieee9-storage-n1/) | 20 MW/80 MWh 储能三种运行模式下，基准潮流与 N-1 结果如何变化 | 基准 0.9545–0.9603 p.u.、负载率 65.42%–65.50%；N-1 最差 0.7358 p.u.（`L8` 开断）、最高 97.94%（`L7` 开断）；27 个场景中 18 全网有效、6 部分覆盖、3 无效 | [REPORT](projects/02-ieee9-storage-n1/REPORT.md) |

## 仓库结构

```
energy-systems-portfolio/
├── README.md                    # 项目导航（本文件）
├── requirements.txt             # 运行依赖（版本区间）
├── tools/
│   └── verify_cleanenv.py       # 干净环境结果比对（只读，不写正式数据）
├── docs/
│   ├── README.md                # 文档索引
│   └── technical-report-standard.md   # 技术报告写作规范
└── projects/
    └── 01-ieee9-loadflow-n1/
        ├── REPORT.md            # 技术报告：方法、结果、分析、局限、复现
        ├── CAREER_NOTES.md      # 求职材料（与技术报告分离，可选阅读）
        ├── data/                # 脚本输出：base_case.json、n1_results.csv
        ├── figures/             # 报告图表（由脚本生成）
        └── src/                 # 计算与绘图脚本
```

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python projects\01-ieee9-loadflow-n1\src\n1_analysis.py    # 基准潮流 + N-1
python projects\01-ieee9-loadflow-n1\src\make_figures.py   # 图表
```

结果写入对应项目的 `data/` 与 `figures/`，相对路径，无机器相关配置。

在另一个（干净）虚拟环境中重跑后，可只读比对是否复现一致，退出码 0 表示通过：

```powershell
python tools\verify_cleanenv.py --clean-dir <干净环境中的项目副本目录>
```

## 文档约定

- 技术报告只写研究问题、方法、结果、分析、结论、局限与复现方式；
- 简历与面试材料单独放在各项目的 `CAREER_NOTES.md`，不混入报告；
- 所有结论必须能追溯到 `data/` 下的输出文件，收敛性、结果有效性、约束符合性
  分别表述；
- 新项目按 [技术报告规范](docs/technical-report-standard.md) 撰写。

## 环境

- Python 3.13.9（当前唯一验证版本；3.10–3.12 未验证）
- pandapower 3.5.6、pandas 2.3.3、matplotlib 3.11.2（见 `requirements.txt`）
