"""GitHub REST API client for repository sustainability metrics.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import base64
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from .config import GITHUB_API
from .http import build_session
from .utils import parse_date
# %% GITHUB CLIENT CLASS
class GitHubClient:
    """Small GitHub API wrapper used by the evaluation pipeline.

    The class keeps all GitHub-specific details in one place: authentication,
    pagination, search queries, and repository content checks. Only public read
    operations are used.
    """

    def __init__(self, sleep_seconds: float = 0.2) -> None:
        """Initialize an authenticated or anonymous GitHub session.

        Parameters
        ----------
        sleep_seconds:
            Delay after successful API calls to reduce burstiness.
        """

        self.session = build_session("GITHUB_TOKEN")
        self.sleep_seconds = sleep_seconds

    def request_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
        retries: int = 2,
    ) -> tuple[Any, requests.Response]:
        """Request JSON from the GitHub API.

        Parameters
        ----------
        path_or_url:
            API path such as ``/repos/owner/repo`` or a full URL.
        params:
            Query parameters.
        accept:
            Optional Accept header override.
        retries:
            Number of attempts. Rate-limit responses with a reset timestamp are
            retried after waiting until reset.

        Returns
        -------
        tuple[Any, requests.Response]
            Parsed JSON payload and original response.
        """

        url = path_or_url if path_or_url.startswith("http") else f"{GITHUB_API}{path_or_url}"
        headers = {}
        if accept:
            headers["Accept"] = accept
        for attempt in range(1, retries + 1):
            response = self.session.get(url, params=params, headers=headers, timeout=60)
            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining")
                reset = response.headers.get("X-RateLimit-Reset")
                if remaining == "0" and reset and attempt < retries:
                    wait_seconds = max(1, int(reset) - int(time.time()) + 5)
                    print(
                        f"[github] rate limit reached; waiting {wait_seconds}s",
                        flush=True,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(
                    f"GitHub rate limit or access error for {url}: "
                    f"remaining={remaining}, reset={reset}, body={response.text[:200]}"
                )
            break

        if response.status_code == 404:
            return None, response
        response.raise_for_status()
        time.sleep(self.sleep_seconds)
        if not response.text:
            return None, response
        return response.json(), response

    def repo_info(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch public repository metadata.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.

        Returns
        -------
        dict[str, Any]
            Normalized repository metadata and reachability status.
        """

        payload, response = self.request_json(f"/repos/{owner}/{repo}")
        if response.status_code == 404 or payload is None:
            return {"github_reachable": False}
        return {
            "github_reachable": True,
            "repo_full_name": payload.get("full_name"),
            "repo_created_at": payload.get("created_at"),
            "repo_pushed_at": payload.get("pushed_at"),
            "repo_updated_at": payload.get("updated_at"),
            "repo_default_branch": payload.get("default_branch"),
            "repo_archived": payload.get("archived"),
            "repo_disabled": payload.get("disabled"),
            "repo_fork": payload.get("fork"),
            "repo_stars": payload.get("stargazers_count"),
            "repo_forks": payload.get("forks_count"),
            "repo_homepage": payload.get("homepage"),
            "repo_description": payload.get("description"),
            "repo_open_issues_count": payload.get("open_issues_count"),
        }

    def search_count(self, query: str, *, endpoint: str = "issues") -> int | None:
        """Return GitHub search ``total_count`` for a query.

        Parameters
        ----------
        query:
            GitHub search query.
        endpoint:
            Search endpoint. Currently ``issues`` or ``commits``.

        Returns
        -------
        int | None
            Total count if the API returns a result.
        """

        accept = None
        if endpoint == "commits":
            accept = "application/vnd.github.cloak-preview+json"
        payload, response = self.request_json(
            f"/search/{endpoint}",
            params={"q": query, "per_page": 1},
            accept=accept,
        )
        if response.status_code == 404 or payload is None:
            return None
        return int(payload.get("total_count", 0))

    def count_issues_or_prs(
        self,
        owner: str,
        repo: str,
        start: date,
        end: date,
        *,
        is_pr: bool,
    ) -> int | None:
        """Count issues or pull requests created within a date range.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.
        start:
            Inclusive start date.
        end:
            Inclusive end date.
        is_pr:
            If true, count pull requests; otherwise count issues excluding pull
            requests.

        Returns
        -------
        int | None
            GitHub search count, or ``None`` if unavailable.
        """

        kind = "is:pr" if is_pr else "is:issue"
        query = f"repo:{owner}/{repo} {kind} created:{start.isoformat()}..{end.isoformat()}"
        return self.search_count(query, endpoint="issues")

    def count_commits(
        self,
        owner: str,
        repo: str,
        start: date,
        end: date,
        branch: str | None = None,
    ) -> int | None:
        """Count commits on the default branch in a date range.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.
        start:
            Inclusive start date.
        end:
            Inclusive end date.
        branch:
            Optional branch SHA/name. If omitted, GitHub uses the default
            branch.

        Returns
        -------
        int | None
            Commit count based on paginated commit API responses.
        """

        start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        params = {
            "since": start_dt.isoformat().replace("+00:00", "Z"),
            "until": end_dt.isoformat().replace("+00:00", "Z"),
            "per_page": 1,
        }
        if branch:
            params["sha"] = branch
        payload, response = self.request_json(f"/repos/{owner}/{repo}/commits", params=params)
        if response.status_code == 404 or payload is None:
            return None
        if not payload:
            return 0
        link = response.headers.get("Link", "")
        match = re.search(r"[?&]page=(\d+)>; rel=\"last\"", link)
        if match:
            return int(match.group(1))
        return len(payload)

    def root_contents(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Fetch root-level repository contents.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.

        Returns
        -------
        list[dict[str, Any]]
            Root content entries, or an empty list if unavailable.
        """

        payload, response = self.request_json(f"/repos/{owner}/{repo}/contents")
        if response.status_code == 404 or payload is None:
            return []
        return payload if isinstance(payload, list) else []

    def file_text(self, owner: str, repo: str, path: str) -> str | None:
        """Fetch a small text file from a repository.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.
        path:
            Repository-relative path.

        Returns
        -------
        str | None
            Decoded text if available.
        """

        payload, response = self.request_json(f"/repos/{owner}/{repo}/contents/{path}")
        if response.status_code == 404 or payload is None:
            return None
        if payload.get("encoding") != "base64" or payload.get("size", 0) > 500_000:
            return None
        content = payload.get("content", "")
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    def documentation_signals(
        self,
        owner: str,
        repo: str,
        *,
        homepage: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Detect visible documentation infrastructure signals.

        Parameters
        ----------
        owner:
            Repository owner.
        repo:
            Repository name.
        homepage:
            Repository homepage from metadata.
        description:
            Repository description from metadata.

        Returns
        -------
        dict[str, Any]
            Boolean documentation signals and combined flag.
        """

        contents = self.root_contents(owner, repo)
        names = {entry.get("name", "").lower(): entry for entry in contents}
        readme_name = next((name for name in names if name.startswith("readme")), None)
        readme_text = self.file_text(owner, repo, readme_name) if readme_name else ""
        combined_text = " ".join(
            str(value or "") for value in [homepage, description, readme_text]
        ).lower()
        has_docs_dir = "docs" in names and names["docs"].get("type") == "dir"
        has_readthedocs_config = (
            ".readthedocs.yaml" in names or ".readthedocs.yml" in names
        )
        has_mkdocs = "mkdocs.yml" in names or "mkdocs.yaml" in names
        has_sphinx = False
        if has_docs_dir:
            docs_conf, response = self.request_json(
                f"/repos/{owner}/{repo}/contents/docs/conf.py"
            )
            has_sphinx = response.status_code != 404 and docs_conf is not None
        has_readthedocs_link = "readthedocs.io" in combined_text
        has_pages_link = "github.io" in combined_text
        has_documentation_signal = any(
            [
                has_docs_dir,
                has_readthedocs_config,
                has_mkdocs,
                has_sphinx,
                has_readthedocs_link,
                has_pages_link,
            ]
        )
        return {
            "has_docs_dir": has_docs_dir,
            "has_readthedocs_config": has_readthedocs_config,
            "has_readthedocs_link": has_readthedocs_link,
            "has_mkdocs": has_mkdocs,
            "has_sphinx_docs": has_sphinx,
            "has_github_pages_link": has_pages_link,
            "has_documentation_signal": has_documentation_signal,
        }
# %% FIRST YEAR WINDOW FUNCTION
def first_year_window(publication_date: object, fallback_date: object = None) -> tuple[date, date] | tuple[None, None]:
    """Compute the first 12-month activity window for a record.

    Parameters
    ----------
    publication_date:
        Publication or archival date from source metadata.
    fallback_date:
        Repository creation date used only when publication date is missing.

    Returns
    -------
    tuple[date, date] | tuple[None, None]
        Start and end dates for the first-year window.
    """

    start = parse_date(publication_date) or parse_date(fallback_date)
    if not start:
        return None, None
    return start, start + timedelta(days=365)
# %% END