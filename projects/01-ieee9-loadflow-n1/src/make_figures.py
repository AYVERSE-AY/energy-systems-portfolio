"""Create static figures for the IEEE 9-bus N-1 screening report.

Bar labels use the pandapower line index (``L<idx>``) and the 1-9 bus numbers
of the case9 data set (``b<from>->b<to>``), matching the tables in REPORT.md.
Scenarios whose results do not cover the whole in-service network are drawn
with a hatched pattern.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT_ROOT / "data" / "n1_results.csv"
FIGURES = PROJECT_ROOT / "figures"

PARTIAL_STATUS = "partial_coverage_islanded"
ISLANDED_STATUS = "islanded_no_valid_results"


def label(row: pd.Series) -> str:
    return f"L{int(row.outaged_line)} (b{row.from_bus_label}->b{row.to_bus_label})"


def voltage_color(value: float) -> str:
    if value < 0.90:
        return "#c0392b"
    if value < 0.95:
        return "#e67e22"
    return "#2e86c1"


def loading_color(value: float) -> str:
    if value > 100:
        return "#c0392b"
    if value > 90:
        return "#e67e22"
    return "#2e86c1"


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    results = pd.read_csv(RESULTS)
    valid = results[results["status"] != ISLANDED_STATUS].copy()
    partial = valid["status"] == PARTIAL_STATUS

    voltage = valid.sort_values("vmin_pu", ascending=True)
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    bars = ax.barh(
        [label(row) for _, row in voltage.iterrows()],
        voltage["vmin_pu"],
        color=[voltage_color(value) for value in voltage["vmin_pu"]],
        hatch=["//" if flag else "" for flag in partial.loc[voltage.index]],
        edgecolor="#333333",
        linewidth=0.8,
    )
    ax.axvline(0.90, color="#c0392b", linestyle="--", linewidth=1.2)
    ax.axvline(0.95, color="#e67e22", linestyle=":", linewidth=1.2)
    ax.set_xlim(0.75, 1.02)
    ax.set_xlabel("Minimum bus voltage over buses with results (p.u.)")
    ax.set_title("IEEE 9-bus N-1 screening: minimum bus voltage")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    for bar, value in zip(bars, voltage["vmin_pu"]):
        ax.text(
            value + 0.003,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.3f}",
            va="center",
            fontsize=9,
        )
    handles = [
        plt.Line2D([], [], color="#c0392b", linestyle="--", label="0.90 p.u. limit"),
        plt.Line2D([], [], color="#e67e22", linestyle=":", label="0.95 p.u. strict limit"),
        Patch(facecolor="#bbbbbb", edgecolor="#333333", hatch="//",
              label="partial coverage (islanded bus)"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3,
              frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "n1_min_voltage.png", dpi=200)
    plt.close(fig)

    loading = valid.sort_values("max_line_loading_percent", ascending=False)
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    bars = ax.barh(
        [label(row) for _, row in loading.iterrows()],
        loading["max_line_loading_percent"],
        color=[loading_color(value) for value in loading["max_line_loading_percent"]],
        hatch=["//" if flag else "" for flag in partial.loc[loading.index]],
        edgecolor="#333333",
        linewidth=0.8,
    )
    ax.axvline(100, color="#c0392b", linestyle="--", linewidth=1.2)
    ax.set_xlim(0, 112)
    ax.set_xlabel("Maximum line loading over lines with results (%)")
    ax.set_title("IEEE 9-bus N-1 screening: maximum line loading")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    for bar, value in zip(bars, loading["max_line_loading_percent"]):
        ax.text(
            value + 1,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}%",
            va="center",
            fontsize=9,
        )
    handles = [
        plt.Line2D([], [], color="#c0392b", linestyle="--", label="100% loading limit"),
        Patch(facecolor="#bbbbbb", edgecolor="#333333", hatch="//",
              label="partial coverage (islanded bus)"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2,
              frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "n1_max_loading.png", dpi=200)
    plt.close(fig)

    print(f"Wrote figures to: {FIGURES}")


if __name__ == "__main__":
    main()
