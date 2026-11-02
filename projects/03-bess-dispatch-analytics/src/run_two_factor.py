"""Capacity x power grid: where does the dispatch benefit saturate? (示意数据)"""

from __future__ import annotations

import csv

from scenario import RESULTS_DIR
from sensitivity import run_two_factor

CAPACITIES = (60, 100, 150, 200)
POWERS = (10, 20, 30, 40)


def main() -> None:
    rows = run_two_factor()
    lookup = {(r["case"]): r for r in rows}

    print("cost (元)  行=容量 kWh, 列=功率上限 kW")
    print("        " + "".join(f"{p:>9d}" for p in POWERS))
    for e in CAPACITIES:
        line = f"{e:>7d} "
        for p in POWERS:
            row = lookup[f"e={e}kWh,p={p}kW"]
            line += f"{row['cost_yuan']:>9.2f}" if row["cost_yuan"] is not None else f"{'-':>9s}"
        print(line)

    print("\nsaving vs fair baseline (%)")
    print("        " + "".join(f"{p:>9d}" for p in POWERS))
    for e in CAPACITIES:
        line = f"{e:>7d} "
        for p in POWERS:
            row = lookup[f"e={e}kWh,p={p}kW"]
            line += f"{row['saving_pct']:>9.2f}" if row["saving_pct"] is not None else f"{'-':>9s}"
        print(line)

    results_dir = RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)
    output = results_dir / "two_factor_summary.csv"
    fields = list(rows[0])
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {output}")
    print("示例数据，非真实电站收益。")


if __name__ == "__main__":
    main()
