"""Metric collection and aggregation for GitHub-linked source records.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
from tqdm import tqdm

from .config import CSV_DIR, PROCESSED_DIR, RAW_DIR
from .github_api import GitHubClient, first_year_window
from .utils import save_csv
# %% CONSTANTS
METRICS_CACHE_PATH = PROCESSED_DIR / "github_metrics_partial.csv"
# %% FUNCTIONS
def collect_metrics_for_record(
    client: GitHubClient,
    record: pd.Series,
) -> dict[str, Any]:
    """Collect GitHub repository metrics for one source record.

    Parameters
    ----------
    client:
        GitHub API client.
    record:
        One row from the source records table.

    Returns
    -------
    dict[str, Any]
        Source identifiers, repository metadata, documentation signals, and
        first-year activity counts.
    """

    owner = str(record["owner"])
    repo = str(record["repo"])
    base: dict[str, Any] = {
        "source": record.get("source"),
        "source_record_id": record.get("source_record_id"),
        "source_url": record.get("source_url"),
        "title": record.get("title"),
        "doi": record.get("doi"),
        "publication_date": record.get("publication_date"),
        "publication_year": record.get("publication_year"),
        "github_url": record.get("github_url"),
        "owner": owner,
        "repo": repo,
        "repo_key": f"{owner.lower()}/{repo.lower()}",
    }
    try:
        repo_info = client.repo_info(owner, repo)
        base.update(repo_info)
        if not repo_info.get("github_reachable"):
            return base
        docs = client.documentation_signals(
            owner,
            repo,
            homepage=repo_info.get("repo_homepage"),
            description=repo_info.get("repo_description"),
        )
        base.update(docs)
        window_start, window_end = first_year_window(
            record.get("publication_date"),
            repo_info.get("repo_created_at"),
        )
        base["activity_window_start"] = window_start.isoformat() if window_start else None
        base["activity_window_end"] = window_end.isoformat() if window_end else None
        if window_start and window_end:
            branch = repo_info.get("repo_default_branch")
            metric_owner = owner
            metric_repo = repo
            if repo_info.get("repo_full_name") and "/" in repo_info["repo_full_name"]:
                metric_owner, metric_repo = repo_info["repo_full_name"].split("/", 1)
            issues = client.count_issues_or_prs(
                metric_owner, metric_repo, window_start, window_end, is_pr=False
            )
            prs = client.count_issues_or_prs(
                metric_owner, metric_repo, window_start, window_end, is_pr=True
            )
            commits = client.count_commits(
                metric_owner, metric_repo, window_start, window_end, branch
            )
            base["issues_first_year"] = issues
            base["pull_requests_first_year"] = prs
            base["commits_first_year"] = commits
            base["has_issue_first_year"] = bool(issues and issues > 0)
            base["has_pull_request_first_year"] = bool(prs and prs > 0)
            base["has_commit_first_year"] = bool(commits and commits > 0)
    except Exception as exc:
        base["metric_error"] = str(exc)
    return base

def metric_cache_key(record: pd.Series | dict[str, Any]) -> str:
    """Build a stable cache key for one source-repository record.

    Parameters
    ----------
    record:
        Source or metric row.

    Returns
    -------
    str
        Stable key combining source, source record identifier, and repository.
    """

    get_value = record.get
    source = str(get_value("source", ""))
    source_record_id = str(get_value("source_record_id", ""))
    repo_key = get_value("repo_key", None)
    if repo_key is None or pd.isna(repo_key):
        owner = str(get_value("owner", "")).lower()
        repo = str(get_value("repo", "")).lower()
        repo_key = f"{owner}/{repo}"
    return f"{source}||{source_record_id}||{str(repo_key).lower()}"

def load_metrics_cache(source_records: pd.DataFrame) -> list[dict[str, Any]]:
    """Load reusable cached metric rows for the current source cohort.

    Parameters
    ----------
    source_records:
        Source records defining the current cohort.

    Returns
    -------
    list[dict[str, Any]]
        Cached metric records matching the current source rows.
    """

    cache_path = METRICS_CACHE_PATH
    if not cache_path.exists() and (PROCESSED_DIR / "github_metrics.csv").exists():
        cache_path = PROCESSED_DIR / "github_metrics.csv"
    if not cache_path.exists():
        return []

    cache = pd.read_csv(cache_path)
    wanted_keys = {metric_cache_key(row) for _, row in source_records.iterrows()}
    cache["_metric_cache_key"] = [metric_cache_key(row) for _, row in cache.iterrows()]
    cache = cache[cache["_metric_cache_key"].isin(wanted_keys)]
    cache = cache.drop_duplicates(subset=["_metric_cache_key"], keep="last")
    return cache.drop(columns=["_metric_cache_key"]).to_dict("records")

def save_metrics_cache(records: list[dict[str, Any]]) -> None:
    """Persist partial GitHub metric records for resumable runs.

    Parameters
    ----------
    records:
        Metric records collected so far.
    """

    if records:
        save_csv(pd.DataFrame.from_records(records), METRICS_CACHE_PATH)

def sort_metrics_like_sources(
    metrics: pd.DataFrame,
    source_records: pd.DataFrame,
) -> pd.DataFrame:
    """Sort metric rows to match the source-record order.

    Parameters
    ----------
    metrics:
        Metric table.
    source_records:
        Source table whose order should be preserved.

    Returns
    -------
    pandas.DataFrame
        Ordered metric table.
    """

    if metrics.empty:
        return metrics
    order = {
        metric_cache_key(row): index
        for index, (_, row) in enumerate(source_records.iterrows())
    }
    ordered = metrics.copy()
    ordered["_metric_order"] = [
        order.get(metric_cache_key(row), len(order)) for _, row in ordered.iterrows()
    ]
    return ordered.sort_values("_metric_order").drop(columns=["_metric_order"])

def collect_github_metrics(
    source_records: pd.DataFrame | None = None,
    *,
    n_jobs: int = 1,
    progress_every: int = 10,
) -> pd.DataFrame:
    """Collect GitHub metrics for all source records.

    Parameters
    ----------
    source_records:
        Optional source records table. If omitted, the table is loaded from
        ``data/raw/source_records.csv``.
    n_jobs:
        Number of worker threads for GitHub metric collection. Values above 1
        can speed up metadata collection but may hit GitHub search-rate limits.
    progress_every:
        Emit a flushed terminal progress line every N records.

    Returns
    -------
    pandas.DataFrame
        Repository-level metric table.
    """

    if source_records is None:
        source_records = pd.read_csv(RAW_DIR / "source_records.csv")
    if source_records.empty:
        metrics = pd.DataFrame()
        save_csv(metrics, PROCESSED_DIR / "github_metrics.csv")
        return metrics
    n_jobs = max(1, int(n_jobs))
    total = len(source_records)
    cached_records = load_metrics_cache(source_records)
    completed_keys = {metric_cache_key(record) for record in cached_records}
    pending_rows = [
        row
        for _, row in source_records.iterrows()
        if metric_cache_key(row) not in completed_keys
    ]
    records = list(cached_records)
    if cached_records:
        print(
            f"[github] resumed {len(cached_records)}/{total} records from cache",
            flush=True,
        )
    if not pending_rows:
        metrics = sort_metrics_like_sources(pd.DataFrame.from_records(records), source_records)
        save_metrics_cache(records)
        save_csv(metrics, PROCESSED_DIR / "github_metrics.csv")
        save_csv(metrics, CSV_DIR / "github_metrics.csv")
        return metrics

    if n_jobs == 1:
        client = GitHubClient()
        iterator = tqdm(
            pending_rows,
            total=len(pending_rows),
            desc="Collecting GitHub metrics",
        )
        for pending_index, row in enumerate(iterator, start=1):
            current_index = len(records) + 1
            if progress_every and (current_index == 1 or current_index % progress_every == 0):
                print(
                    f"[github] {current_index}/{total} {row.get('source')} {row.get('owner')}/{row.get('repo')}",
                    flush=True,
                )
            records.append(collect_metrics_for_record(client, row))
            save_metrics_cache(records)
    else:
        with ThreadPoolExecutor(max_workers=n_jobs) as executor:
            futures = [
                executor.submit(collect_metrics_for_record, GitHubClient(), row)
                for row in pending_rows
            ]
            for pending_index, future in enumerate(
                tqdm(
                    as_completed(futures),
                    total=len(pending_rows),
                    desc=f"Collecting GitHub metrics ({n_jobs} jobs)",
                ),
                start=1,
            ):
                record = future.result()
                records.append(record)
                current_index = len(records)
                if progress_every and (current_index == 1 or current_index % progress_every == 0):
                    print(
                        f"[github] {current_index}/{total} {record.get('source')} {record.get('repo_key')}",
                        flush=True,
                    )
                save_metrics_cache(records)
    metrics = sort_metrics_like_sources(pd.DataFrame.from_records(records), source_records)
    save_metrics_cache(records)
    save_csv(metrics, PROCESSED_DIR / "github_metrics.csv")
    save_csv(metrics, CSV_DIR / "github_metrics.csv")
    return metrics

def deduplicate_for_cohort(metrics: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate records to one row per source/repository pair.

    Parameters
    ----------
    metrics:
        GitHub metric table.

    Returns
    -------
    pandas.DataFrame
        Deduplicated table. JOSS and Zenodo are kept as separate cohorts, but
        duplicate records within a source and repository are collapsed.
    """

    if metrics.empty:
        return metrics
    table = metrics.copy()
    table["publication_year"] = pd.to_numeric(table["publication_year"], errors="coerce")
    table = table.dropna(subset=["publication_year"])
    table["publication_year"] = table["publication_year"].astype(int)
    table = table.sort_values(
        by=["source", "repo_key", "publication_date"],
        na_position="last",
    )
    return table.drop_duplicates(subset=["source", "repo_key"], keep="first")

def aggregate_by_year(metrics: pd.DataFrame | None = None) -> pd.DataFrame:
    """Aggregate repository metrics by source and cohort year.

    Parameters
    ----------
    metrics:
        Optional metric table. If omitted, the table is loaded from
        ``data/processed/github_metrics.csv``.

    Returns
    -------
    pandas.DataFrame
        Annual cohort summary table used by plotting functions.
    """

    if metrics is None:
        metrics = pd.read_csv(PROCESSED_DIR / "github_metrics.csv")
    metrics = deduplicate_for_cohort(metrics)
    if metrics.empty:
        summary = pd.DataFrame()
        save_csv(summary, CSV_DIR / "annual_summary.csv")
        return summary

    count_cols = [
        "issues_first_year",
        "pull_requests_first_year",
        "commits_first_year",
    ]
    bool_cols = [
        "has_documentation_signal",
        "has_issue_first_year",
        "has_pull_request_first_year",
        "has_commit_first_year",
    ]
    for col in count_cols:
        metrics[col] = pd.to_numeric(metrics.get(col), errors="coerce").fillna(0)
    for col in bool_cols:
        metrics[col] = metrics.get(col, False).fillna(False).astype(bool)

    rows: list[dict[str, Any]] = []
    for (source, year), group in metrics.groupby(["source", "publication_year"]):
        project_count = len(group)
        row: dict[str, Any] = {
            "source": source,
            "publication_year": int(year),
            "project_count": project_count,
            "documentation_count": int(group["has_documentation_signal"].sum()),
            "documentation_percent": 100 * group["has_documentation_signal"].mean(),
            "issue_project_count": int(group["has_issue_first_year"].sum()),
            "issue_project_percent": 100 * group["has_issue_first_year"].mean(),
            "pull_request_project_count": int(
                group["has_pull_request_first_year"].sum()
            ),
            "pull_request_project_percent": 100
            * group["has_pull_request_first_year"].mean(),
            "commit_project_count": int(group["has_commit_first_year"].sum()),
            "commit_project_percent": 100 * group["has_commit_first_year"].mean(),
            "issues_mean": group["issues_first_year"].mean(),
            "issues_median": group["issues_first_year"].median(),
            "pull_requests_mean": group["pull_requests_first_year"].mean(),
            "pull_requests_median": group["pull_requests_first_year"].median(),
            "commits_mean": group["commits_first_year"].mean(),
            "commits_median": group["commits_first_year"].median(),
        }
        rows.append(row)

    summary = pd.DataFrame.from_records(rows).sort_values(
        by=["source", "publication_year"]
    )
    summary["cumulative_project_count"] = summary.groupby("source")[
        "project_count"
    ].cumsum()
    save_csv(summary, CSV_DIR / "annual_summary.csv")
    return summary
# %% END