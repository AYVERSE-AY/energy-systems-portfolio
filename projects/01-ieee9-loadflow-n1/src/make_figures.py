"""Create static figures for the IEEE 9-bus N-1 screening report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "work" / "n1_results.csv"
FIGURES = ROOT / "outputs" / "figures"


def label(row: pd.Series) -> str:
    return f"L{int(row.outaged_line)} ({int(row.from_bus)}->{int(row.to_bus)})"


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    results = pd.read_csv(RESULTS)
    valid = results[results["status"] == "ok"].copy()

    voltage = valid.sort_values("vmin_pu", ascending=True).head(7)
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = [
        "#c0392b" if value < 0.90 else "#e67e22" if value < 0.95 else "#2e86c1"
        for value in voltage["vmin_pu"]
    ]
    bars = ax.barh([label(row) for _, row in voltage.iterrows()], voltage["vmin_pu"], color=colors)
    ax.axvline(0.90, color="#c0392b", linestyle="--", linewidth=1.2, label="0.90 p.u. limit")
    ax.axvline(0.95, color="#e67e22", linestyle=":", linewidth=1.2, label="0.95 p.u. strict limit")
    ax.set_xlim(0.75, 1.02)
    ax.set_xlabel("Minimum bus voltage (p.u.)")
    ax.set_title("IEEE 9-bus N-1 screening: minimum bus voltage")
    ax.invert_yaxis()
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    for bar, value in zip(bars, voltage["vmin_pu"]):
        ax.text(value + 0.003, bar.get_y() + bar.get_height() / 2, f"{value:.3f}", va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "n1_min_voltage.png", dpi=200)
    plt.close(fig)

    loading = valid.sort_values("max_line_loading_percent", ascending=False).head(7)
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = [
        "#c0392b" if value > 100 else "#e67e22" if value > 90 else "#2e86c1"
        for value in loading["max_line_loading_percent"]
    ]
    bars = ax.barh([label(row) for _, row in loading.iterrows()], loading["max_line_loading_percent"], color=colors)
    ax.axvline(100, color="#c0392b", linestyle="--", linewidth=1.2, label="100% loading limit")
    ax.set_xlim(0, 110)
    ax.set_xlabel("Maximum line loading (%)")
    ax.set_title("IEEE 9-bus N-1 screening: maximum line loading")
    ax.invert_yaxis()
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    for bar, value in zip(bars, loading["max_line_loading_percent"]):
        ax.text(value + 1, bar.get_y() + bar.get_height() / 2, f"{value:.1f}%", va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "n1_max_loading.png", dpi=200)
    plt.close(fig)

    print(f"Wrote figures to: {FIGURES}")


if __name__ == "__main__":
    main()
