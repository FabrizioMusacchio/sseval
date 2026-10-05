"""Plot annual scientific software publication and activity summaries.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .config import CSV_DIR, PDF_DIR, PNG_DIR
# %% FUNCTIONS
def save_current_figure(name: str) -> None:
    """Save the active matplotlib figure as PNG and PDF.

    Parameters
    ----------
    name:
        Base filename without extension.
    """

    PNG_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(PNG_DIR / f"{name}.png", dpi=300, bbox_inches="tight")
    plt.savefig(PDF_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close()

def plot_growth(summary: pd.DataFrame) -> None:
    """Plot annual and cumulative repository counts.

    Parameters
    ----------
    summary:
        Annual cohort summary table.
    """

    fig, ax1 = plt.subplots(figsize=(10, 6))
    sns.barplot(
        data=summary,
        x="publication_year",
        y="project_count",
        hue="source",
        ax=ax1,
    )
    ax1.set_xlabel("Publication or archival year")
    ax1.set_ylabel("New GitHub-linked software records")
    ax1.tick_params(axis="x", rotation=45, labelsize=9)

    ax2 = ax1.twinx()
    for source, group in summary.groupby("source"):
        ax2.plot(
            group["publication_year"].astype(str),
            group["cumulative_project_count"],
            marker="o",
            linewidth=2,
            label=f"{source} cumulative",
        )
    ax2.set_ylabel("Cumulative records")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")
    ax1.set_title(
        "Growth of published or archived GitHub-linked scientific software",
        fontsize=13,
        pad=12,
    )
    fig.tight_layout()
    save_current_figure("software_growth_by_year")

def plot_percent(summary: pd.DataFrame, column: str, title: str, name: str) -> None:
    """Plot percentage metric by source and cohort year.

    Parameters
    ----------
    summary:
        Annual cohort summary table.
    column:
        Percent column to plot.
    title:
        Figure title.
    name:
        Output basename.
    """

    plt.figure(figsize=(10, 6))
    sns.lineplot(
        data=summary,
        x="publication_year",
        y=column,
        hue="source",
        marker="o",
    )
    plt.ylim(0, 100)
    plt.xlabel("Publication or archival year")
    plt.ylabel("Projects (%)")
    plt.title(title, fontsize=13, pad=12)
    plt.xticks(rotation=45, fontsize=9)
    plt.tight_layout()
    save_current_figure(name)

def plot_average_and_median(
    summary: pd.DataFrame,
    mean_col: str,
    median_col: str,
    ylabel: str,
    title: str,
    name: str,
) -> None:
    """Plot mean and median activity counts by source and cohort year.

    Parameters
    ----------
    summary:
        Annual cohort summary table.
    mean_col:
        Column containing mean values.
    median_col:
        Column containing median values.
    ylabel:
        Y-axis label.
    title:
        Figure title.
    name:
        Output basename.
    """

    plt.figure(figsize=(10, 6))
    for source, group in summary.groupby("source"):
        plt.plot(
            group["publication_year"],
            group[mean_col],
            marker="o",
            linewidth=2,
            label=f"{source} mean",
        )
        plt.plot(
            group["publication_year"],
            group[median_col],
            marker="s",
            linestyle="--",
            linewidth=1.5,
            label=f"{source} median",
        )
    plt.xlabel("Publication or archival year")
    plt.ylabel(ylabel)
    plt.title(title, fontsize=13, pad=12)
    plt.xticks(rotation=45, fontsize=9)
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=9)
    plt.tight_layout()
    save_current_figure(name)

def create_all_plots(summary: pd.DataFrame | None = None) -> None:
    """Create all planned plots from the annual summary table.

    Parameters
    ----------
    summary:
        Optional summary table. If omitted, ``results/csv/annual_summary.csv`` is
        loaded.
    """

    if summary is None:
        summary = pd.read_csv(CSV_DIR / "annual_summary.csv")
    if summary.empty:
        return
    sns.set_theme(style="whitegrid", context="paper", font_scale=1.1)
    plot_growth(summary)
    plot_percent(
        summary,
        "documentation_percent",
        "Dedicated documentation signals by cohort year",
        "documentation_signals_percent_by_year",
    )
    plot_percent(
        summary,
        "issue_project_percent",
        "Repositories with at least one issue in the first year",
        "issues_presence_percent_by_year",
    )
    plot_average_and_median(
        summary,
        "issues_mean",
        "issues_median",
        "Issues per project in the first year",
        "Issue activity in the first year after publication",
        "issues_average_median_by_year",
    )
    plot_percent(
        summary,
        "pull_request_project_percent",
        "Repositories with at least one pull request in the first year",
        "pull_requests_presence_percent_by_year",
    )
    plot_average_and_median(
        summary,
        "pull_requests_mean",
        "pull_requests_median",
        "Pull requests per project in the first year",
        "Pull-request activity in the first year after publication",
        "pull_requests_average_median_by_year",
    )
    plot_percent(
        summary,
        "commit_project_percent",
        "Repositories with at least one commit in the first year",
        "commits_presence_percent_by_year",
    )
    plot_average_and_median(
        summary,
        "commits_mean",
        "commits_median",
        "Commits per project in the first year",
        "Commit activity in the first year after publication",
        "commits_average_median_by_year",
    )
# %% END