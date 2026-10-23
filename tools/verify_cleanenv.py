"""Verify that a clean-environment run reproduces the committed project results.

用途
----
在另一个虚拟环境（干净环境）里重跑 `projects/01-ieee9-loadflow-n1/src/*.py`
之后，用它把干净环境的输出与本仓库工作区中的正式结果逐项比对，判断是否复现一致。

脚本**只读**：不写 CSV/JSON/图表，不创建目录，不修改仓库任何文件。
比对的基准是工作区中的正式结果；若这些文件与 HEAD 不一致，脚本会打印提示
（此时比对仍以工作区为准，不阻断退出码）。

用法
----
    # clean_dir 应为项目的完整副本目录，含有 data/ 与 figures/
    python tools/verify_cleanenv.py --clean-dir D:\\dsh-cleanenv\\work\\projects\\01-ieee9-loadflow-n1

    # 指定被比对的正式项目目录（默认：本仓库的 projects/01-ieee9-loadflow-n1）
    python tools/verify_cleanenv.py --clean-dir <dir> --project-dir <dir>

    # 放宽数值容差 / 跳过图表比对
    python tools/verify_cleanenv.py --clean-dir <dir> --tolerance 1e-6 --figures skip

通过条件（退出码 0）
--------------------
1. 干净环境存在 data/n1_results.csv 与 data/base_case.json；
2. CSV 行数、outaged_line 集合与正式结果完全一致；
3. 全部数值列最大绝对差 ≤ --tolerance（NaN 与 NaN 视为一致）；
4. status 等字符串列完全一致；
5. base_case.json 的 network / settings / results 各字段在容差内一致。

图表对比为**提示性检查**（退出码不受影响）：PNG 逐字节一致说明渲染也可复现，
不一致只代表 matplotlib 版本或平台差异，不构成数据错误。

退出码
------
0 = 全部通过；1 = 存在不满足项（会列出具体列/字段）；2 = 参数非法或自比对。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

NUMERIC_COLUMNS = [
    "vmin_pu",
    "vmax_pu",
    "max_line_loading_percent",
    "voltage_violations",
    "strict_voltage_violations",
    "line_overloads",
    "iterations",
    "buses_with_results",
    "lines_with_results",
]
STRING_COLUMNS = ["status", "from_bus_label", "to_bus_label", "islanded_buses"]
FIGURE_FILES = ["figures/n1_min_voltage.png", "figures/n1_max_loading.png"]
REQUIRED_FILES = ["data/n1_results.csv", "data/base_case.json"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric_equal(left, right, tolerance: float) -> bool:
    left_na, right_na = pd.isna(left), pd.isna(right)
    if left_na or right_na:
        return bool(left_na and right_na)
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def warn_if_reference_dirty(project: Path) -> None:
    """Notify when the comparison baseline differs from HEAD (advisory only)."""
    repo_root = project.parents[1]
    try:
        relative = [str((project / name).relative_to(repo_root)) for name in REQUIRED_FILES]
    except ValueError:
        return
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--quiet", "HEAD", "--", *relative],
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return
    if completed.returncode == 1:
        print("提示: 正式结果与 HEAD 不一致（工作区有改动），本次比对以工作区文件为基准")


def compare_csv(project: Path, clean: Path, tolerance: float) -> list[str]:
    failures: list[str] = []
    reference = pd.read_csv(project / "data/n1_results.csv")
    candidate = pd.read_csv(clean / "data/n1_results.csv")

    print(f"\n[CSV] 行数 正式={len(reference)} 干净={len(candidate)}")
    if len(reference) != len(candidate):
        failures.append(f"CSV 行数不一致：{len(reference)} vs {len(candidate)}")
        return failures

    if "outaged_line" in reference and "outaged_line" in candidate:
        if not reference["outaged_line"].tolist() == candidate["outaged_line"].tolist():
            failures.append("outaged_line 序列不一致")
            return failures
        if reference["outaged_line"].duplicated().any():
            failures.append("正式结果中 outaged_line 存在重复值，无法逐行比对")
            return failures
        reference = reference.set_index("outaged_line")
        candidate = candidate.set_index("outaged_line")

    for column in NUMERIC_COLUMNS:
        if column not in reference or column not in candidate:
            failures.append(f"缺少数值列 {column}")
            continue
        worst = 0.0
        mismatches = 0
        for index in reference.index:
            left, right = reference.at[index, column], candidate.at[index, column]
            if not numeric_equal(left, right, tolerance):
                mismatches += 1
                if not pd.isna(left) and not pd.isna(right):
                    worst = max(worst, abs(float(left) - float(right)))
        status = "OK" if mismatches == 0 else "FAIL"
        print(f"  {column:28s} max|diff|={worst:.3g}  不一致行={mismatches}  {status}")
        if mismatches:
            failures.append(f"{column}: {mismatches} 行不满足容差 {tolerance}")

    for column in STRING_COLUMNS:
        if column not in reference or column not in candidate:
            failures.append(f"缺少字符串列 {column}")
            continue
        left = reference[column].fillna("").astype(str)
        right = candidate[column].fillna("").astype(str)
        same = left.equals(right)
        print(f"  {column:28s} identical={same}")
        if not same:
            failures.append(f"{column} 不一致")

    return failures


def compare_json(project: Path, clean: Path, tolerance: float) -> list[str]:
    failures: list[str] = []
    reference = json.loads((project / "data/base_case.json").read_text(encoding="utf-8"))
    candidate = json.loads((clean / "data/base_case.json").read_text(encoding="utf-8"))

    print(
        f"\n[JSON] pandapower_version 正式={reference.get('pandapower_version')} "
        f"干净={candidate.get('pandapower_version')}"
    )

    for section in ("network", "settings", "results"):
        left_section = reference.get(section, {})
        right_section = candidate.get(section, {})
        for key, left in left_section.items():
            right = right_section.get(key)
            if isinstance(left, float) or isinstance(right, float):
                same = numeric_equal(left, right, tolerance)
            else:
                same = left == right
            mark = "OK" if same else "FAIL"
            print(f"  {section}.{key:28s} 正式={left!r:22s} 干净={right!r:22s} {mark}")
            if not same:
                failures.append(f"{section}.{key} 不一致：{left!r} vs {right!r}")
    return failures


def compare_figures(project: Path, clean: Path) -> None:
    print("\n[图] 提示性检查（不影响退出码）")
    for relative in FIGURE_FILES:
        left, right = project / relative, clean / relative
        if not (left.exists() and right.exists()):
            print(f"  {relative}: 缺少文件，跳过")
            continue
        same = sha256(left) == sha256(right)
        print(f"  {relative}: identical={same} ({left.stat().st_size} B vs {right.stat().st_size} B)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对比干净环境输出与仓库正式结果（只读，不写任何文件）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--clean-dir", required=True, help="干净环境中的项目副本目录（含 data/、figures/）")
    parser.add_argument(
        "--project-dir",
        default=str(Path(__file__).resolve().parent.parent / "projects" / "01-ieee9-loadflow-n1"),
        help="正式项目目录",
    )
    parser.add_argument("--tolerance", type=float, default=1e-9, help="数值列允许的最大绝对差")
    parser.add_argument("--figures", choices=["hash", "skip"], default="hash", help="图表检查方式")
    args = parser.parse_args()

    project = Path(args.project_dir).resolve()
    clean = Path(args.clean_dir).resolve()

    if args.tolerance < 0:
        print("参数错误: --tolerance 不能为负数")
        return 2
    if project == clean:
        print("参数错误: --clean-dir 与 --project-dir 指向同一目录，比对必然通过但没有意义")
        return 2

    print(f"正式项目: {project}")
    print(f"干净输出: {clean}")
    print(f"数值容差: {args.tolerance}")
    warn_if_reference_dirty(project)

    failures: list[str] = []
    for relative in REQUIRED_FILES:
        missing = [str(directory / relative) for directory in (project, clean) if not (directory / relative).exists()]
        if missing:
            failures.extend(f"缺少文件：{path}" for path in missing)
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1

    failures += compare_csv(project, clean, args.tolerance)
    failures += compare_json(project, clean, args.tolerance)
    if args.figures == "hash":
        compare_figures(project, clean)

    print("\n" + "=" * 60)
    if failures:
        print(f"结果: FAIL（{len(failures)} 项）")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("结果: PASS — 干净环境输出与正式结果在容差内完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
