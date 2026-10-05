"""Interactively create study plots from aggregated annual summary data.

This script is intended for use in editors that support Python cell markers
such as VS Code, Spyder, or PyCharm. It deliberately reads only the already
aggregated CSV table and writes figures to a separate interactive output
folder, so it does not rerun the data collection pipeline or overwrite the
standard pipeline plots.

author: Fabrizio Musacchio
date:   October 2026
"""

# %% IMPORTS
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".matplotlib"))

import matplotlib.pyplot as plt
import seaborn as sns
# %% PATHS AND MAIN SETTINGS
SUMMARY_CSV = PROJECT_ROOT / "results" / "csv" / "annual_summary.csv"
GITHUB_METRICS_CSV = PROJECT_ROOT / "results" / "csv" / "github_metrics.csv"
SOURCE_RECORDS_CSV = PROJECT_ROOT / "data" / "raw" / "source_records.csv"
OUTPUT_DIR = PROJECT_ROOT / "results" / "interactive_plots"
PNG_DIR = OUTPUT_DIR / "png"
PDF_DIR = OUTPUT_DIR / "pdf"

SAVE_FIGURES = True
SHOW_FIGURES = False
PNG_DPI = 300
DISTILL_PDF_WITH_GHOSTSCRIPT = True
main_font_size = 15
title_font_size = main_font_size
label_font_size = main_font_size
tick_font_size  = main_font_size
legend_font_size = 12
font_family = "Arial"

SOURCE_ORDER = ["joss", "zenodo"]
SOURCE_LABELS = {
    "joss": "JOSS",
    "zenodo": "Zenodo"}
SOURCE_COLORS = {
    "joss": "#2F5F89",
    "zenodo": "#D07429"}
# %% FUNCTIONS AND CLASSES
def cm_to_inches(width_cm: float, height_cm: float) -> tuple[float, float]:
    """Convert a figure size from centimeters to inches.

    Parameters
    ----------
    width_cm:
        Width in centimeters.
    height_cm:
        Height in centimeters.

    Returns
    -------
    tuple[float, float]
        Matplotlib figure size in inches.
    """

    return width_cm / 2.54, height_cm / 2.54

def load_annual_summary(path: Path = SUMMARY_CSV) -> pd.DataFrame:
    """Load the annual summary table used for plotting.

    Parameters
    ----------
    path:
        CSV file produced by ``sseval aggregate``.

    Returns
    -------
    pandas.DataFrame
        Cleaned annual summary table.
    """

    summary = pd.read_csv(path)
    summary["publication_year"] = summary["publication_year"].astype(int)
    summary["source"] = pd.Categorical(
        summary["source"],
        categories=SOURCE_ORDER,
        ordered=True,
    )
    return summary.sort_values(["source", "publication_year"]).reset_index(drop=True)

def load_github_metrics(path: Path = GITHUB_METRICS_CSV) -> pd.DataFrame:
    """Load repository-level GitHub metrics for interactive activity plots.

    Parameters
    ----------
    path:
        CSV file produced by ``sseval collect-github-metrics`` and exported by
        ``sseval aggregate``.

    Returns
    -------
    pandas.DataFrame
        Repository-level metrics with numeric activity columns.
    """

    metrics = pd.read_csv(path)
    metrics["publication_year"] = pd.to_numeric(
        metrics["publication_year"], errors="coerce"
    )
    metrics = metrics.dropna(subset=["publication_year", "repo_key", "source"]).copy()
    metrics["publication_year"] = metrics["publication_year"].astype(int)
    for column in [
        "issues_first_year",
        "pull_requests_first_year",
        "commits_first_year",
    ]:
        metrics[column] = pd.to_numeric(metrics.get(column), errors="coerce").fillna(0)
    return metrics

def load_source_records(path: Path = SOURCE_RECORDS_CSV) -> pd.DataFrame:
    """Load the full source-record table for unsampled growth counts.

    Parameters
    ----------
    path:
        Full source-record CSV produced by ``sseval fetch-sources``.

    Returns
    -------
    pandas.DataFrame
        Source records with valid source, repository key, and cohort year.
    """

    records = pd.read_csv(path)
    records["publication_year"] = pd.to_numeric(
        records["publication_year"], errors="coerce"
    )
    records = records.dropna(subset=["publication_year", "repo_key", "source"]).copy()
    records["publication_year"] = records["publication_year"].astype(int)
    return records

def deduplicate_by_source_repository(records: pd.DataFrame) -> pd.DataFrame:
    """Collapse records to the first observed year for each source/repository pair.

    This is useful for growth plots because Zenodo can contain multiple releases
    or records that point to the same GitHub repository. Counting every record
    would overstate the number of distinct projects.

    Parameters
    ----------
    records:
        Source or metric table containing ``source``, ``repo_key``,
        ``publication_year``, and preferably ``publication_date``.

    Returns
    -------
    pandas.DataFrame
        One row per source and normalized repository key.
    """

    if records.empty:
        return records
    table = records.copy()
    sort_columns = ["source", "repo_key", "publication_year"]
    if "publication_date" in table.columns:
        sort_columns.append("publication_date")
    table = table.sort_values(sort_columns, na_position="last")
    return table.drop_duplicates(subset=["source", "repo_key"], keep="first")

def build_full_growth_summary(records: pd.DataFrame) -> pd.DataFrame:
    """Build annual growth counts from the full unsampled source table.

    Parameters
    ----------
    records:
        Full source-record table from ``data/raw/source_records.csv``.

    Returns
    -------
    pandas.DataFrame
        Summary table with ``project_count`` and ``cumulative_project_count``.
    """

    deduplicated = deduplicate_by_source_repository(records)
    summary = (
        deduplicated.groupby(["source", "publication_year"], observed=True)
        .size()
        .reset_index(name="project_count")
        .sort_values(["source", "publication_year"])
    )
    summary["source"] = pd.Categorical(
        summary["source"], categories=SOURCE_ORDER, ordered=True
    )
    summary["cumulative_project_count"] = summary.groupby("source", observed=True)[
        "project_count"
    ].cumsum()
    return summary.sort_values(["source", "publication_year"]).reset_index(drop=True)

def build_activity_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    """Build annual activity summaries with mean, median, std, and SEM.

    Parameters
    ----------
    metrics:
        Repository-level GitHub metric table.

    Returns
    -------
    pandas.DataFrame
        Annual activity summary for issue, pull-request, and commit counts.
    """

    deduplicated = deduplicate_by_source_repository(metrics)
    activity_columns = {
        "issues": "issues_first_year",
        "pull_requests": "pull_requests_first_year",
        "commits": "commits_first_year",
    }
    rows: list[dict[str, Any]] = []
    for (source, year), group in deduplicated.groupby(
        ["source", "publication_year"], observed=True
    ):
        row: dict[str, Any] = {
            "source": source,
            "publication_year": int(year),
            "project_count": int(len(group)),
        }
        for metric_name, column in activity_columns.items():
            values = pd.to_numeric(group[column], errors="coerce").fillna(0)
            row[f"{metric_name}_mean"] = values.mean()
            row[f"{metric_name}_median"] = values.median()
            row[f"{metric_name}_std"] = values.std(ddof=1)
            row[f"{metric_name}_sem"] = values.sem(ddof=1)
        rows.append(row)
    summary = pd.DataFrame.from_records(rows)
    summary["source"] = pd.Categorical(
        summary["source"], categories=SOURCE_ORDER, ordered=True
    )
    return summary.sort_values(["source", "publication_year"]).reset_index(drop=True)

def source_label(source: str) -> str:
    """Return a display label for a source name."""

    return SOURCE_LABELS.get(str(source), str(source))

def apply_axes_config(ax: plt.Axes, config: dict[str, Any]) -> None:
    """Apply common axis settings from a plot configuration dictionary.

    Parameters
    ----------
    ax:
        Matplotlib axes to configure.
    config:
        Plot configuration dictionary.
    """

    ax.set_title(
        config.get("title", ""),
        pad=10,
        fontsize=config.get("title_font_size", title_font_size),
    )
    ax.set_xlabel(
        config.get("xlabel", ""),
        fontsize=config.get("label_font_size", label_font_size),
    )
    ax.set_ylabel(
        config.get("ylabel", ""),
        fontsize=config.get("label_font_size", label_font_size),
    )
    ax.tick_params(
        axis="both",
        labelsize=config.get("tick_font_size", tick_font_size),
    )
    if config.get("xlim") is not None:
        ax.set_xlim(config["xlim"])
    if config.get("ylim") is not None:
        ax.set_ylim(config["ylim"])
    if config.get("xtick_rotation") is not None:
        ax.tick_params(axis="x", rotation=config["xtick_rotation"])
    if not config.get("show_legend", True):
        legend = ax.get_legend()
        if legend:
            legend.remove()
    else:
        handles, labels = ax.get_legend_handles_labels()
        if handles and labels:
            ax.legend(
                loc=config.get("legend_location", "best"),
                fontsize=config.get("legend_font_size", legend_font_size),
            )

def save_or_show(fig: plt.Figure, name: str) -> None:
    """Save and optionally display a figure.

    Parameters
    ----------
    fig:
        Matplotlib figure.
    name:
        Base filename without extension.
    """

    if SAVE_FIGURES:
        PNG_DIR.mkdir(parents=True, exist_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        fig.savefig(PNG_DIR / f"{name}.png", dpi=PNG_DPI, bbox_inches="tight")
        pdf_path = PDF_DIR / f"{name}.pdf"
        if DISTILL_PDF_WITH_GHOSTSCRIPT and shutil.which("gs"):
            temporary_pdf_path = PDF_DIR / f"{name}.matplotlib.pdf"
            fig.savefig(temporary_pdf_path, bbox_inches="tight", transparent=True)
            subprocess.run(
                [
                    "gs",
                    "-dSAFER",
                    "-dBATCH",
                    "-dNOPAUSE",
                    "-dCompatibilityLevel=1.4",
                    "-sDEVICE=pdfwrite",
                    "-dPDFSETTINGS=/prepress",
                    "-dDetectDuplicateImages=true",
                    "-dCompressFonts=true",
                    "-dSubsetFonts=true",
                    f"-sOutputFile={pdf_path}",
                    str(temporary_pdf_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            temporary_pdf_path.unlink(missing_ok=True)
        else:
            fig.savefig(pdf_path, bbox_inches="tight")
    if SHOW_FIGURES:
        plt.show()
    else:
        plt.close(fig)

def plot_growth(summary: pd.DataFrame, config: dict[str, Any]) -> plt.Figure:
    """Plot annual and cumulative source records by cohort year."""

    fig, ax1 = plt.subplots(figsize=cm_to_inches(*config["figsize_cm"]))
    sns.barplot(
        data=summary,
        x="publication_year",
        y="project_count",
        hue="source",
        hue_order=SOURCE_ORDER,
        palette=SOURCE_COLORS,
        ax=ax1,
    )
    ax2 = ax1.twinx()
    for source, group in summary.groupby("source", observed=True):
        if group.empty:
            continue
        ax2.plot(
            group["publication_year"].astype(str),
            group["cumulative_project_count"],
            marker="o",
            linewidth=2,
            color=SOURCE_COLORS.get(str(source)),
            label=f"{source_label(str(source))} cumulative",
        )
    apply_axes_config(ax1, config)
    ax2.set_ylabel(
        config.get("secondary_ylabel", "Cumulative records"),
        fontsize=config.get("label_font_size", label_font_size),
    )
    ax2.tick_params(
        axis="both",
        labelsize=config.get("tick_font_size", tick_font_size),
    )
    if config.get("secondary_ylim") is not None:
        ax2.set_ylim(config["secondary_ylim"])
    if config.get("show_legend", True):
        ax1.legend(
            loc=config.get("legend_location", "upper left"),
            fontsize=config.get("legend_font_size", legend_font_size),
        )
        ax2.legend(
            loc=config.get("secondary_legend_location", "upper right"),
            fontsize=config.get("legend_font_size", legend_font_size),
        )
    else:
        if ax1.get_legend():
            ax1.get_legend().remove()
    fig.tight_layout()
    return fig

def plot_percent(summary: pd.DataFrame, config: dict[str, Any]) -> plt.Figure:
    """Plot a percentage metric by source and cohort year."""

    fig, ax = plt.subplots(figsize=cm_to_inches(*config["figsize_cm"]))
    sns.lineplot(
        data=summary,
        x="publication_year",
        y=config["y"],
        hue="source",
        hue_order=SOURCE_ORDER,
        palette=SOURCE_COLORS,
        marker="o",
        linewidth=2,
        ax=ax,
    )
    apply_axes_config(ax, config)
    fig.tight_layout()
    return fig

def normalize_statistics(statistics: str | list[str] | tuple[str, ...]) -> list[str]:
    """Normalize a statistic-selection setting to a list.

    Parameters
    ----------
    statistics:
        Either ``"mean"``, ``"median"``, or an iterable containing those values.

    Returns
    -------
    list[str]
        Ordered list of statistics to draw.
    """

    if isinstance(statistics, str):
        statistics = [statistics]
    allowed = {"mean", "median"}
    normalized = [str(item).lower() for item in statistics]
    unknown = sorted(set(normalized).difference(allowed))
    if unknown:
        raise ValueError(f"Unknown statistics requested: {unknown}")
    return normalized

def error_column_for(config: dict[str, Any]) -> str | None:
    """Return the configured uncertainty-column name for an activity metric."""

    show_error = config.get("show_error")
    if show_error is None or show_error is False:
        return None
    normalized = str(show_error).lower()
    if normalized not in {"std", "sem"}:
        raise ValueError("show_error must be one of None, 'std', or 'SEM'.")
    return f"{config['metric_prefix']}_{normalized}"

def plot_average_and_median(summary: pd.DataFrame, config: dict[str, Any]) -> plt.Figure:
    """Plot selected activity statistics by source and cohort year.

    The shaded uncertainty band is drawn around mean lines by default because
    standard deviation and SEM describe variability around the mean. Set
    ``shade_median=True`` in a plot config to also draw the same band around
    median lines as a visual guide.
    """

    fig, ax = plt.subplots(figsize=cm_to_inches(*config["figsize_cm"]))
    statistics = normalize_statistics(config.get("statistics", ["mean", "median"]))
    error_col = error_column_for(config)
    error_label = str(config.get("show_error", "")).upper()
    for source, group in summary.groupby("source", observed=True):
        if group.empty:
            continue
        group = group.sort_values("publication_year")
        x_values = group["publication_year"].astype(float)
        color = SOURCE_COLORS.get(str(source))
        label = source_label(str(source))
        if "mean" in statistics:
            y_values = pd.to_numeric(group[config["mean_y"]], errors="coerce")
            ax.plot(
                x_values,
                y_values,
                marker="o",
                linewidth=2,
                color=color,
                label=f"{label} mean ± {error_label}" if error_col else f"{label} mean",
            )
            if error_col:
                error_values = pd.to_numeric(group[error_col], errors="coerce").fillna(0)
                ax.fill_between(
                    x_values,
                    (y_values - error_values).clip(lower=0),
                    y_values + error_values,
                    color=color,
                    alpha=config.get("error_alpha", 0.16),
                    linewidth=0,
                    label="_nolegend_",
                )
        if "median" in statistics:
            y_values = pd.to_numeric(group[config["median_y"]], errors="coerce")
            has_median_error = bool(error_col and config.get("shade_median", False))
            ax.plot(
                x_values,
                y_values,
                marker="s",
                linestyle="--",
                linewidth=1.5,
                color=color,
                alpha=0.75,
                label=(
                    f"{label} median ± {error_label}"
                    if has_median_error
                    else f"{label} median"
                ),
            )
            if has_median_error:
                error_values = pd.to_numeric(group[error_col], errors="coerce").fillna(0)
                ax.fill_between(
                    x_values,
                    (y_values - error_values).clip(lower=0),
                    y_values + error_values,
                    color=color,
                    alpha=config.get("error_alpha", 0.10),
                    linewidth=0,
                    label="_nolegend_",
                )
    apply_axes_config(ax, config)
    fig.tight_layout()
    return fig

# %% PLOT CONFIGS
PLOT_CONFIGS: dict[str, dict[str, Any]] = {
    "software_growth_by_year": {
        "kind": "growth",
        # Use "full_source_records" to avoid the artificial 1000/year Zenodo
        # sampling cap in growth plots. Use "annual_summary" to reproduce the
        # exact standard pipeline plot from ``sseval plot``.
        "data_source": "full_source_records",
        "title": "Growth of GitHub-linked published or archived scientific software",
        "figsize_cm": (18.0, 10.5),
        "ylim": None,
        "secondary_ylim": None,
        "xlim": None,
        "show_legend": True,
        "legend_location": "upper left",
        "secondary_legend_location": "center left",
        "ylabel": "New software records",
        "secondary_ylabel": "Cumulative records",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "documentation_signals_percent_by_year": {
        "kind": "percent",
        "y": "documentation_percent",
        "title": "Dedicated documentation signals by cohort year",
        "figsize_cm": (16.0, 9.0),
        "ylim": (0, 100),
        "xlim": None,
        "show_legend": True,
        "legend_location": "best",
        "ylabel": "Projects with documentation signal (%)",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "issues_presence_percent_by_year": {
        "kind": "percent",
        "y": "issue_project_percent",
        "title": "Repositories with at least one issue in the first year",
        "figsize_cm": (16.0, 9.0),
        "ylim": (0, 100),
        "xlim": None,
        "show_legend": True,
        "legend_location": "best",
        "ylabel": "Projects with issues (%)",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "issues_average_median_by_year": {
        "kind": "mean_median",
        "metric_prefix": "issues",
        "statistics": ["mean"], # ["mean", "median"]
        "show_error": "SEM",
        "shade_median": False,
        "error_alpha": 0.16,
        "mean_y": "issues_mean",
        "median_y": "issues_median",
        "title": "Issue activity in the first year after publication",
        "figsize_cm": (18.0, 10.5),
        "ylim": None,
        "xlim": None,
        "show_legend": True,
        "legend_location": "upper left",
        "ylabel": "Issues per project",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "pull_requests_presence_percent_by_year": {
        "kind": "percent",
        "y": "pull_request_project_percent",
        "title": "Repositories with at least one pull request in the first year",
        "figsize_cm": (16.0, 9.0),
        "ylim": (0, 100),
        "xlim": None,
        "show_legend": True,
        "legend_location": "center right",
        "ylabel": "Projects with pull requests (%)",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "pull_requests_average_median_by_year": {
        "kind": "mean_median",
        "metric_prefix": "pull_requests",
        "statistics": ["mean"], # ["mean", "median"]
        "show_error": "SEM",
        "shade_median": False,
        "error_alpha": 0.16,
        "mean_y": "pull_requests_mean",
        "median_y": "pull_requests_median",
        "title": "Pull-request activity in the first year after publication",
        "figsize_cm": (18.0, 10.5),
        "ylim": None,
        "xlim": None,
        "show_legend": True,
        "legend_location": "upper left",
        "ylabel": "Pull requests per project",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "commits_presence_percent_by_year": {
        "kind": "percent",
        "y": "commit_project_percent",
        "title": "Repositories with at least one commit in the first year",
        "figsize_cm": (16.0, 9.0),
        "ylim": (0, 100),
        "xlim": None,
        "show_legend": True,
        "legend_location": "best",
        "ylabel": "Projects with commits (%)",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
    "commits_average_median_by_year": {
        "kind": "mean_median",
        "metric_prefix": "commits",
        "statistics": ["mean"], # ["mean", "median"]
        "show_error": "SEM",
        "shade_median": False,
        "error_alpha": 0.16,
        "mean_y": "commits_mean",
        "median_y": "commits_median",
        "title": "Commit activity in the first year after publication",
        "figsize_cm": (18.0, 10.5),
        "ylim": None,
        "xlim": None,
        "show_legend": True,
        "legend_location": "upper left",
        "ylabel": "Commits per project",
        "xlabel": "Publication or archival year",
        "xtick_rotation": 45,
    },
}
# %% LOAD DATA
annual_summary = load_annual_summary()
github_metrics = load_github_metrics()
source_records = load_source_records()

full_growth_summary = build_full_growth_summary(source_records)
activity_summary = build_activity_summary(github_metrics)
# %% PLOT STYLE
sns.set_theme(style="whitegrid", context="paper", font=font_family)
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [font_family, "DejaVu Sans"],
        "font.size": main_font_size,
        "axes.titlesize":  title_font_size,
        "axes.labelsize":  label_font_size,
        "xtick.labelsize": tick_font_size,
        "ytick.labelsize": tick_font_size,
        "legend.fontsize": legend_font_size,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 120,
        "savefig.dpi": PNG_DPI,
    })
# %% CREATE SELECTED PLOTS
plots_to_create = list(PLOT_CONFIGS)

for plot_name in plots_to_create:
    config = PLOT_CONFIGS[plot_name]
    if config["kind"] == "growth":
        growth_data_source = config.get("data_source", "annual_summary")
        if growth_data_source == "full_source_records":
            figure = plot_growth(full_growth_summary, config)
        elif growth_data_source == "annual_summary":
            figure = plot_growth(annual_summary, config)
        else:
            raise ValueError(f"Unknown growth data source: {growth_data_source}")
    elif config["kind"] == "percent":
        figure = plot_percent(annual_summary, config)
    elif config["kind"] == "mean_median":
        figure = plot_average_and_median(activity_summary, config)
    else:
        raise ValueError(f"Unknown plot kind: {config['kind']}")
    save_or_show(figure, plot_name)
# %% QUICK TABLE INSPECTION
annual_summary
# %%
full_growth_summary
# %%
activity_summary
# %% END
