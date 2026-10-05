"""Small reusable helpers for files, dates, URLs, and tables.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from dateutil import parser as date_parser
# %% REGEX PATTERNS
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")

# %% FUNCTIONS
def ensure_directories(paths: Iterable[Path]) -> None:
    """Create output directories if they do not already exist.

    Parameters
    ----------
    paths:
        Directory paths that should exist before reading or writing files.
    """

    for path in paths:
        path.mkdir(parents=True, exist_ok=True)

def write_json(path: Path, payload: object) -> None:
    """Write JSON with stable indentation for later inspection.

    Parameters
    ----------
    path:
        Destination file.
    payload:
        JSON-serializable object to write.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    """Write newline-delimited JSON records.

    Parameters
    ----------
    path:
        Destination file.
    records:
        Iterable of dictionaries, one per output line.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

def read_jsonl(path: Path) -> list[dict]:
    """Read newline-delimited JSON records from disk.

    Parameters
    ----------
    path:
        File containing one JSON object per line.

    Returns
    -------
    list[dict]
        Parsed records. Empty lines are ignored.
    """

    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Save a table as CSV after creating the parent directory.

    Parameters
    ----------
    df:
        Table to write.
    path:
        Destination CSV path.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def parse_date(value: object) -> date | None:
    """Parse a publication date into a date object.

    Parameters
    ----------
    value:
        Date-like value from API metadata.

    Returns
    -------
    date | None
        Parsed date, or ``None`` when parsing fails.
    """

    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None

def iso_date(value: date | datetime | None) -> str | None:
    """Return an ISO date string or ``None``.

    Parameters
    ----------
    value:
        Date-like object.

    Returns
    -------
    str | None
        ISO date string if available.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()

def now_utc() -> datetime:
    """Return the current UTC timestamp.

    Returns
    -------
    datetime
        Timezone-aware UTC timestamp.
    """

    return datetime.now(timezone.utc)

def extract_github_urls(*texts: object) -> list[str]:
    """Extract normalized GitHub repository URLs from arbitrary text fields.

    Parameters
    ----------
    *texts:
        Text-like values that may contain GitHub URLs.

    Returns
    -------
    list[str]
        Unique normalized repository URLs in first-seen order.
    """

    urls: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if text is None:
            continue
        for match in GITHUB_RE.finditer(str(text)):
            owner, repo = match.groups()
            repo = repo.removesuffix(".git")
            repo = repo.split("/")[0]
            normalized = f"https://github.com/{owner}/{repo}"
            key = normalized.lower()
            if key not in seen:
                urls.append(normalized)
                seen.add(key)
    return urls

def split_github_url(url: str) -> tuple[str, str] | tuple[None, None]:
    """Split a normalized GitHub URL into owner and repository name.

    Parameters
    ----------
    url:
        GitHub repository URL.

    Returns
    -------
    tuple[str, str] | tuple[None, None]
        Owner and repository name when parsing succeeds.
    """

    match = GITHUB_RE.search(url or "")
    if not match:
        return None, None
    owner, repo = match.groups()
    return owner, repo.removesuffix(".git")

def publication_year(value: object) -> int | None:
    """Extract a year from a publication date-like value.

    Parameters
    ----------
    value:
        Date-like value.

    Returns
    -------
    int | None
        Four-digit year when available.
    """

    parsed = parse_date(value)
    return parsed.year if parsed else None
# %% END