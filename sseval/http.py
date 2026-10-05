"""HTTP helpers with shared headers, token support, and polite retries.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

from .config import DEFAULT_USER_AGENT, PROJECT_ROOT
# %% FUNCTIONS
def load_project_env(path: Path | None = None) -> None:
    """Load simple KEY=VALUE lines from project-local environment files.

    Parameters
    ----------
    path:
        Optional environment file path. When omitted, `.env` and
        `github_token.env` are checked in that order. Existing process
        environment variables are not overwritten.
    """

    paths = [path] if path else [PROJECT_ROOT / ".env", PROJECT_ROOT / "github_token.env"]
    for env_path in paths:
        if env_path is None or not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def build_session(token_env: str | None = None) -> requests.Session:
    """Build a requests session with a user agent and optional bearer token.

    Parameters
    ----------
    token_env:
        Name of an environment variable containing an API token. When omitted
        or unset, the session remains unauthenticated.

    Returns
    -------
    requests.Session
        Configured HTTP session.
    """

    load_project_env()
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    if token_env:
        token = os.environ.get(token_env)
        if token:
            session.headers.update({"Authorization": f"Bearer {token}"})
    return session

def get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = 3,
    sleep_seconds: float = 1.0,
) -> Any:
    """Fetch JSON with basic retry handling for transient failures.

    Parameters
    ----------
    session:
        Configured HTTP session.
    url:
        URL to fetch.
    params:
        Optional query parameters.
    retries:
        Number of attempts before raising the last error.
    sleep_seconds:
        Base delay between retries.

    Returns
    -------
    Any
        Parsed JSON response.
    """

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_error = exc
            wait_seconds = max(5.0, sleep_seconds * attempt)
            print(
                f"[http] request failed ({exc.__class__.__name__}); "
                f"waiting {wait_seconds:.0f}s before retry {attempt}/{retries}",
                flush=True,
            )
            if attempt == retries:
                raise
            time.sleep(wait_seconds)
            continue
        if response.status_code == 403 and "X-RateLimit-Remaining" in response.headers:
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            raise RuntimeError(
                f"GitHub rate limit reached: remaining={remaining}, reset={reset}."
            )
        if response.status_code == 429:
            fallback_seconds = max(30.0, sleep_seconds * attempt * 10)
            wait_seconds = max(
                fallback_seconds,
                retry_after_seconds(response, fallback_seconds=fallback_seconds),
            )
            print(
                f"[http] 429 rate limit from {response.url}; waiting {wait_seconds:.0f}s",
                flush=True,
            )
            time.sleep(wait_seconds)
            continue
        try:
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            last_error = exc
            if attempt == retries:
                raise
            time.sleep(sleep_seconds * attempt)
    if last_error:
        raise last_error
    raise RuntimeError(f"Could not fetch JSON from {url}")

def retry_after_seconds(response: requests.Response, fallback_seconds: float) -> float:
    """Return a polite wait time for a rate-limited HTTP response.

    Parameters
    ----------
    response:
        HTTP response, usually with status code 429.
    fallback_seconds:
        Delay to use when the server does not provide a usable Retry-After
        header.

    Returns
    -------
    float
        Number of seconds to wait before retrying.
    """

    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return fallback_seconds
    try:
        return max(1.0, float(retry_after))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(retry_after)
        return max(1.0, retry_at.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return fallback_seconds
# %% END