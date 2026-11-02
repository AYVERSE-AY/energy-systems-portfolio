# 03 · 工商业储能智能调度与收益分析

本目录是 `energy-systems-portfolio` 的第三个项目：面向工商业用户侧储能（BESS）的调度仿真与收益分析平台。

> 当前处于**阶段 2：分时电价经济调度**。已实现单步模型、多时段仿真、24 时段基准场景
> 与 MILP 经济调度（`src/optimization.py`，HiGHS）；电价与负荷为示例数据。需量管理、
> 投资回收期与可视化尚未实现。

## 目标

- 输入：分时电价、负荷曲线、储能参数（容量、功率、效率、SOC 区间）。
- 处理：逐时/SOC 递推的物理仿真 + 调度策略（峰谷套利、需量管理）。
- 输出：日电费对比、年收益、回收期，以及可视化与可复现的实验记录。

## 目录结构

```
03-bess-dispatch-analytics/
├── src/          # 业务代码（模型、调度、收益计算）
├── tests/        # pytest 测试
├── data/         # 输入数据（电价、负荷样例）
├── results/      # 运行产物（默认不入库）
├── docs/         # 设计说明与实验记录
├── .venv/        # 项目虚拟环境（不入库）
├── README.md
└── PROJECT_STATUS.md
```

## 环境

- Python 3.13.9（`D:\python\python.exe`），虚拟环境位于本目录 `.venv`。
- 依赖见根目录 `requirements.txt`。

```powershell
cd projects\03-bess-dispatch-analytics
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

注意：本机请始终使用 `python -m pip`，不要直接调用全局 `pip.exe`。

## 约定

- 物理模型（能量平衡、SOC）与调度策略、收益计算分层实现，互不耦合。
- 默认参数必须标注来源或"行业经验值、待标定"。
- 示例数据一律标记为示意数据，不作为真实项目依据。
