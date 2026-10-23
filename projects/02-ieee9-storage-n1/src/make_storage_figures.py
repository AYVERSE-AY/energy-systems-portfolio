"""Create comparison figures for the IEEE 9-bus BESS study.

Reads data/storage_base_results.csv and data/storage_n1_results.csv, writes to
figures/. Bars whose N-1 result covers only part of the network (one bus
islanded) are drawn hatched: their metrics describe the energised island only.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIGURES = ROOT / "figures"

PARTIAL_STATUS = "partial_coverage_islanded"

MODE_LABELS = {
    "standby": "Standby",
    "charge_20mw": "Charge 20 MW",
    "discharge_20mw": "Discharge 20 MW",
}
MODE_ORDER = ["standby", "charge_20mw", "discharge_20mw"]
COLORS = ["#7f8c8d", "#c0392b", "#2e86c1"]


def style_axis(ax: plt.Axes, ylabel: str, title: str) -> None:
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)


def partial_legend() -> Patch:
    return Patch(facecolor="white", edgecolor="#333333", hatch="//",
                 label="partial coverage (one bus islanded)")


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(DATA / "storage_base_results.csv")
    n1 = pd.read_csv(DATA / "storage_n1_results.csv")

    base["mode_label"] = base["storage_mode"].map(MODE_LABELS)
    base = base.set_index("storage_mode").loc[MODE_ORDER].reset_index()

    full = n1[n1["status"] == "ok"]
    n1_summary = (
        full.groupby("storage_mode")
        .agg(
            worst_vmin_pu=("vmin_pu", "min"),
            worst_loading_percent=("max_line_loading_percent", "max"),
        )
        .reindex(MODE_ORDER)
        .reset_index()
    )

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax = axes[0, 0]
    bars = ax.bar(base["mode_label"], base["vmin_pu"], color=COLORS)
    ax.axhline(0.90, color="#c0392b", linestyle="--", linewidth=1.2, label="0.90 p.u.")
    ax.set_ylim(0.93, 0.97)
    style_axis(ax, "Minimum voltage (p.u.)", "(a) Base case: minimum voltage")
    ax.legend(loc="lower right")
    for bar, value in zip(bars, base["vmin_pu"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.0008, f"{value:.4f}", ha="center", fontsize=8)

    ax = axes[0, 1]
    bars = ax.bar(base["mode_label"], base["max_line_loading_percent"], color=COLORS)
    ax.axhline(100, color="#c0392b", linestyle="--", linewidth=1.2, label="100% limit")
    ax.set_ylim(60, 105)
    style_axis(ax, "Maximum line loading (%)", "(b) Base case: maximum loading")
    ax.legend(loc="lower right")
    for bar, value in zip(bars, base["max_line_loading_percent"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.8, f"{value:.2f}%", ha="center", fontsize=8)

    ax = axes[1, 0]
    labels = [MODE_LABELS[mode] for mode in n1_summary["storage_mode"]]
    bars = ax.bar(labels, n1_summary["worst_vmin_pu"], color=COLORS)
    ax.axhline(0.90, color="#c0392b", linestyle="--", linewidth=1.2, label="0.90 p.u.")
    ax.set_ylim(0.70, 0.91)
    style_axis(ax, "Worst N-1 minimum voltage (p.u.)", "(c) N-1: worst minimum voltage (full coverage)")
    ax.legend(loc="lower right", fontsize=8)
    for bar, value in zip(bars, n1_summary["worst_vmin_pu"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.003, f"{value:.3f}", ha="center", fontsize=8)

    ax = axes[1, 1]
    bars = ax.bar(labels, n1_summary["worst_loading_percent"], color=COLORS)
    ax.axhline(100, color="#c0392b", linestyle="--", linewidth=1.2, label="100% limit")
    ax.set_ylim(80, 105)
    style_axis(ax, "Worst N-1 maximum loading (%)", "(d) N-1: worst line loading (full coverage)")
    ax.legend(loc="lower right", fontsize=8)
    for bar, value in zip(bars, n1_summary["worst_loading_percent"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.8, f"{value:.1f}%", ha="center", fontsize=8)

    fig.suptitle("IEEE 9-bus BESS study: 20 MW / 80 MWh at bus 9", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIGURES / "storage_modes_overview.png", dpi=200)
    plt.close(fig)

    line6 = n1[n1["outaged_line"] == 6].set_index("storage_mode").loc[MODE_ORDER]
    line8 = n1[n1["outaged_line"] == 8].set_index("storage_mode").loc[MODE_ORDER]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    ax = axes[0]
    hatches = ["//" if status == PARTIAL_STATUS else "" for status in line6["status"]]
    bars = ax.bar(
        [MODE_LABELS[m] for m in line6.index],
        line6["max_line_loading_percent"],
        color=COLORS,
        hatch=hatches,
        edgecolor="#333333",
        linewidth=0.8,
    )
    ax.axhline(100, color="#c0392b", linestyle="--", linewidth=1.2, label="100% limit")
    ax.set_ylim(80, 110)
    style_axis(ax, "Maximum line loading (%)", "Outage of line 6 (b8->b2)")
    for bar, value in zip(bars, line6["max_line_loading_percent"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.8, f"{value:.1f}%", ha="center", fontsize=9)

    ax = axes[1]
    bars = ax.bar([MODE_LABELS[m] for m in line8.index], line8["vmin_pu"], color=COLORS)
    ax.axhline(0.90, color="#c0392b", linestyle="--", linewidth=1.2, label="0.90 p.u.")
    ax.set_ylim(0.70, 0.88)
    style_axis(ax, "Minimum voltage (p.u.)", "Outage of line 8 (b9->b4)")
    for bar, value in zip(bars, line8["vmin_pu"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.003, f"{value:.3f}", ha="center", fontsize=9)

    fig.legend(
        handles=[
            plt.Line2D([], [], color="#c0392b", linestyle="--", label="100% loading limit"),
            plt.Line2D([], [], color="#c0392b", linestyle="--", label="0.90 p.u. voltage limit"),
            partial_legend(),
        ],
        loc="lower center",
        ncol=3,
        frameon=False,
        fontsize=9,
        bbox_to_anchor=(0.5, 0.0),
    )
    fig.suptitle("Critical N-1 outages with BESS operating modes "
                 "(hatched: metrics cover the energised island only)", fontsize=12)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    fig.savefig(FIGURES / "storage_critical_outages.png", dpi=200)
    plt.close(fig)

    print(f"Wrote figures to: {FIGURES}")


if __name__ == "__main__":
    main()
