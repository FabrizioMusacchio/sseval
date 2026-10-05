"""Collectors for public records of published or archived software.

This module defines the cohort construction step. It deliberately separates
source records from GitHub activity metrics so that the definition of
"published scientific software" remains inspectable and revisable.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from tqdm import tqdm

from .config import (
    CROSSREF_WORKS_API,
    JOSS_RAW_BASE,
    JOSS_REPO_API_TREE,
    PROCESSED_DIR,
    RAW_DIR,
    ZENODO_RECORDS_API)
from .github_api import GitHubClient
from .http import build_session, get_json
from .utils import (
    extract_github_urls,
    iso_date,
    parse_date,
    publication_year,
    save_csv,
    split_github_url,
    write_json)
# %% FUNCTIONS
def parse_markdown_front_matter(text: str) -> dict[str, Any]:
    """Parse YAML front matter from a Markdown document.

    Parameters
    ----------
    text:
        Markdown text that may begin with a YAML front matter block.

    Returns
    -------
    dict[str, Any]
        Parsed front matter. Returns an empty dictionary if no valid block is
        found.
    """

    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}

def normalize_doi(value: object) -> str | None:
    """Normalize DOI values copied from JOSS/Crossref metadata.

    Parameters
    ----------
    value:
        DOI-like value. This may already be a bare DOI or may be a DOI URL with
        typographic quotes.

    Returns
    -------
    str | None
        Bare lowercase DOI without surrounding punctuation, or ``None``.
    """

    if value is None:
        return None
    text = str(value).strip().strip("\"'“”‘’")
    text = text.removeprefix("https://doi.org/")
    text = text.removeprefix("http://doi.org/")
    text = text.removeprefix("doi:")
    text = text.strip().strip("\"'“”‘’")
    return text.lower() or None

def fetch_crossref_date_and_title(doi: str) -> tuple[str | None, str | None]:
    """Fetch publication date and title from Crossref for a DOI.

    Parameters
    ----------
    doi:
        DOI to query.

    Returns
    -------
    tuple[str | None, str | None]
        Publication date and title if available.
    """

    session = build_session()
    payload = get_json(session, f"{CROSSREF_WORKS_API}/{doi}", retries=2)
    message = payload.get("message", {})
    title = None
    titles = message.get("title") or []
    if titles:
        title = titles[0]
    date_parts = (
        message.get("published-print", {}).get("date-parts")
        or message.get("published-online", {}).get("date-parts")
        or message.get("created", {}).get("date-parts")
    )
    if not date_parts:
        return None, title
    parts = date_parts[0]
    if len(parts) >= 3:
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}", title
    if len(parts) == 2:
        return f"{parts[0]:04d}-{parts[1]:02d}", title
    if len(parts) == 1:
        return f"{parts[0]:04d}", title
    return None, title

def xml_local_name(tag: str) -> str:
    """Return an XML tag name without a namespace prefix.

    Parameters
    ----------
    tag:
        ElementTree tag, possibly including a namespace in braces.

    Returns
    -------
    str
        Local tag name.
    """

    return tag.rsplit("}", 1)[-1]

def first_descendant_text(element: ET.Element, tag_name: str) -> str | None:
    """Return the first non-empty descendant text for a local XML tag name.

    Parameters
    ----------
    element:
        XML element to search below.
    tag_name:
        Namespace-free tag name.

    Returns
    -------
    str | None
        First matching text value, or ``None``.
    """

    for descendant in element.iter():
        if xml_local_name(descendant.tag) == tag_name and descendant.text:
            return descendant.text.strip()
    return None

def parse_crossref_publication_date(article: ET.Element) -> str | None:
    """Extract the publication date from a JOSS Crossref article element.

    Parameters
    ----------
    article:
        ``journal_article`` element from a Crossref XML deposit.

    Returns
    -------
    str | None
        ISO-like date string if year metadata is available.
    """

    publication_date = next(
        (
            child
            for child in article
            if xml_local_name(child.tag) == "publication_date"
        ),
        None,
    )
    if publication_date is None:
        return None
    return parse_publication_date_element(publication_date)

def parse_publication_date_element(publication_date: ET.Element) -> str | None:
    """Extract an ISO-like date from a date-bearing XML element.

    Parameters
    ----------
    publication_date:
        XML element containing ``year``, ``month``, and optionally ``day``.

    Returns
    -------
    str | None
        ISO-like date string if year metadata is available.
    """

    year = first_descendant_text(publication_date, "year")
    month = first_descendant_text(publication_date, "month")
    day = first_descendant_text(publication_date, "day")
    if year and month and day:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if year and month:
        return f"{int(year):04d}-{int(month):02d}"
    return year

def parse_joss_xml_metadata(text: str) -> dict[str, Any]:
    """Parse legacy JOSS XML metadata with direct software repository fields.

    Parameters
    ----------
    text:
        Raw XML document.

    Returns
    -------
    dict[str, Any]
        Parsed title, date, repository URL, and archive DOI when present.
    """

    root = ET.fromstring(text)
    articleinfo = root.find(".//articleinfo")
    return {
        "title": articleinfo.findtext("title") if articleinfo is not None else None,
        "date": articleinfo.findtext("date") if articleinfo is not None else None,
        "repository": articleinfo.findtext("software_repository")
        if articleinfo is not None
        else None,
        "archive_doi": articleinfo.findtext("software_archive")
        if articleinfo is not None
        else None,
    }

def parse_joss_crossref_metadata(text: str) -> dict[str, Any]:
    """Parse JOSS Crossref XML deposits.

    Recent JOSS paper files no longer expose ``software_repository`` directly.
    Their Crossref deposits usually contain a ``Software archive`` relation,
    which can be resolved through Zenodo to recover the GitHub repository.

    Parameters
    ----------
    text:
        Raw Crossref XML document.

    Returns
    -------
    dict[str, Any]
        Parsed DOI, title, publication date, software archive DOI, and review
        issue URL when present.
    """

    root = ET.fromstring(text)
    article = next(
        (
            element
            for element in root.iter()
            if xml_local_name(element.tag) == "journal_article"
        ),
        None,
    )
    if article is None:
        return {}

    metadata: dict[str, Any] = {
        "title": first_descendant_text(article, "title"),
        "date": parse_crossref_publication_date(article),
        "doi": None,
        "archive_doi": None,
        "review_url": None,
    }
    for identifier in article.iter():
        if xml_local_name(identifier.tag) == "identifier" and identifier.get("id_type") == "doi":
            metadata["doi"] = (identifier.text or "").strip() or None
            break
    for related_item in article.iter():
        if xml_local_name(related_item.tag) != "related_item":
            continue
        description = first_descendant_text(related_item, "description")
        relation = next(
            (
                child
                for child in related_item.iter()
                if xml_local_name(child.tag) == "inter_work_relation"
            ),
            None,
        )
        if relation is None:
            continue
        relation_value = (relation.text or "").strip()
        if description == "Software archive":
            metadata["archive_doi"] = relation_value
        elif description == "GitHub review issue":
            metadata["review_url"] = relation_value
    return metadata

def parse_joss_jats_metadata(text: str) -> dict[str, Any]:
    """Parse basic metadata from JOSS JATS XML.

    Parameters
    ----------
    text:
        Raw JATS XML document.

    Returns
    -------
    dict[str, Any]
        Parsed DOI, title, and publication date when present.
    """

    root = ET.fromstring(text)
    metadata: dict[str, Any] = {
        "title": first_descendant_text(root, "article-title"),
        "date": None,
        "doi": None,
    }
    for article_id in root.iter():
        if (
            xml_local_name(article_id.tag) == "article-id"
            and article_id.get("pub-id-type") == "doi"
        ):
            metadata["doi"] = (article_id.text or "").strip() or None
            break
    for pub_date in root.iter():
        if xml_local_name(pub_date.tag) != "pub-date":
            continue
        metadata["date"] = pub_date.get("iso-8601-date") or parse_publication_date_element(
            pub_date
        )
        break
    return metadata

def fetch_zenodo_record_for_doi(
    doi: str,
    *,
    session: Any | None = None,
) -> dict[str, Any] | None:
    """Fetch a Zenodo record by DOI.

    Parameters
    ----------
    doi:
        Zenodo DOI from a JOSS software archive relation.
    session:
        Optional HTTP session. When omitted, a new unauthenticated session is
        built.

    Returns
    -------
    dict[str, Any] | None
        First matching Zenodo record, or ``None``.
    """

    doi = normalize_doi(doi)
    if not doi:
        return None
    zenodo_session = session or build_session()
    payload = get_json(
        zenodo_session,
        ZENODO_RECORDS_API,
        params={"q": f'doi:"{doi}"', "size": 1},
        retries=8,
        sleep_seconds=5.0,
    )
    hits = payload.get("hits", {}).get("hits", [])
    return hits[0] if hits else None

def github_urls_from_joss_review(review_url: object, client: GitHubClient) -> list[str]:
    """Extract candidate repository URLs from a JOSS review issue.

    Parameters
    ----------
    review_url:
        URL to a GitHub issue in ``openjournals/joss-reviews``.
    client:
        GitHub client used to fetch the issue body.

    Returns
    -------
    list[str]
        GitHub repository URLs excluding Open Journals infrastructure links.
    """

    owner, repo = split_github_url(str(review_url or ""))
    if owner != "openjournals" or repo != "joss-reviews":
        return []
    issue_number = str(review_url).rstrip("/").split("/")[-1]
    if not issue_number.isdigit():
        return []
    payload, response = client.request_json(
        f"/repos/openjournals/joss-reviews/issues/{issue_number}"
    )
    if response.status_code == 404 or not payload:
        return []
    urls = extract_github_urls(payload.get("body"))
    return [
        url
        for url in urls
        if not url.lower().startswith("https://github.com/openjournals/")
    ]

def fetch_joss_records(
    *,
    max_records: int | None = None,
    use_crossref: bool = True,
    sleep_seconds: float = 0.1,
    progress_every: int = 10,
) -> pd.DataFrame:
    """Fetch JOSS paper records and extract GitHub repositories.

    Parameters
    ----------
    max_records:
        Optional cap for test runs.
    use_crossref:
        Whether to query Crossref for publication dates and titles.
    sleep_seconds:
        Delay between remote metadata requests.
    progress_every:
        Emit a flushed terminal progress line every N records. This supplements
        tqdm because some terminal wrappers buffer dynamic progress bars.

    Returns
    -------
    pandas.DataFrame
        One row per JOSS paper GitHub repository link.
    """

    session = build_session("GITHUB_TOKEN")
    zenodo_session = build_session()
    github_client = GitHubClient()
    tree = get_json(session, JOSS_REPO_API_TREE, params={"recursive": "1"})
    paper_paths_by_id: dict[str, dict[str, str]] = {}
    for item in tree.get("tree", []):
        path = item.get("path", "")
        paper_id = path.split("/")[0]
        if not paper_id.startswith("joss."):
            continue
        paths = paper_paths_by_id.setdefault(paper_id, {})
        if path.endswith(".crossref.xml"):
            paths["crossref"] = path
        elif path.endswith(".jats") and "/" in path:
            paths["jats"] = path
        elif path.endswith(".xml"):
            paths["legacy_xml"] = path

    paper_paths = sorted(
        paper_paths_by_id,
        key=lambda paper_id: int(paper_id.split(".")[1]),
    )
    if max_records is not None:
        paper_paths = paper_paths[:max_records]

    records: list[dict[str, Any]] = []
    completed_paper_ids: set[str] = set()
    cache_path = RAW_DIR / "joss_records.csv"
    if max_records is None and cache_path.exists():
        cached = pd.read_csv(cache_path)
        if not cached.empty and "source_record_id" in cached.columns:
            records = cached.to_dict("records")
            completed_paper_ids = set(cached["source_record_id"].astype(str))
            print(
                f"[fetch:joss] resumed {len(completed_paper_ids)} papers from cache",
                flush=True,
            )

    for index, paper_id in enumerate(tqdm(paper_paths, desc="Fetching JOSS records"), start=1):
        if paper_id in completed_paper_ids:
            continue
        paths = paper_paths_by_id[paper_id]
        path = paths.get("legacy_xml") or paths.get("crossref") or paths.get("jats")
        if progress_every and (index == 1 or index % progress_every == 0):
            print(f"[fetch:joss] {index}/{len(paper_paths)} {path}", flush=True)
        doi = f"10.21105/{paper_id}"
        metadata: dict[str, Any] = {}

        if paths.get("legacy_xml"):
            raw_url = f"{JOSS_RAW_BASE}/{paths['legacy_xml']}"
            response = session.get(raw_url, timeout=60)
            response.raise_for_status()
            metadata.update(parse_markdown_front_matter(response.text))
            if not metadata:
                try:
                    metadata.update(parse_joss_xml_metadata(response.text))
                except ET.ParseError:
                    pass

        if paths.get("crossref"):
            raw_url = f"{JOSS_RAW_BASE}/{paths['crossref']}"
            response = session.get(raw_url, timeout=60)
            response.raise_for_status()
            try:
                crossref_metadata = parse_joss_crossref_metadata(response.text)
                for key, value in crossref_metadata.items():
                    metadata[key] = metadata.get(key) or value
            except ET.ParseError:
                pass

        if paths.get("jats") and (not metadata.get("title") or not metadata.get("date")):
            raw_url = f"{JOSS_RAW_BASE}/{paths['jats']}"
            response = session.get(raw_url, timeout=60)
            response.raise_for_status()
            try:
                jats_metadata = parse_joss_jats_metadata(response.text)
                for key, value in jats_metadata.items():
                    metadata[key] = metadata.get(key) or value
            except ET.ParseError:
                pass

        publication_date = metadata.get("date") or metadata.get("published")
        title = metadata.get("title")
        if use_crossref and (not publication_date or not title):
            try:
                crossref_date, crossref_title = fetch_crossref_date_and_title(doi)
                publication_date = publication_date or crossref_date
                title = title or crossref_title
                time.sleep(sleep_seconds)
            except Exception:
                pass

        github_urls = extract_github_urls(
            metadata.get("repository"),
            metadata.get("archive_doi"),
            metadata.get("url"),
        )
        archive_doi = metadata.get("archive_doi")
        if archive_doi and not github_urls:
            try:
                zenodo_record = fetch_zenodo_record_for_doi(
                    str(archive_doi),
                    session=zenodo_session,
                )
                if zenodo_record:
                    github_urls = extract_github_urls(
                        *zenodo_record_text_fields(zenodo_record),
                    )
            except Exception:
                pass
        if metadata.get("review_url") and not github_urls:
            try:
                github_urls = github_urls_from_joss_review(
                    metadata.get("review_url"),
                    github_client,
                )
            except Exception:
                pass

        for github_url in github_urls:
            owner, repo = split_github_url(github_url)
            records.append(
                {
                    "source": "joss",
                    "source_record_id": paper_id,
                    "source_url": f"https://joss.theoj.org/papers/{doi}",
                    "title": title,
                    "doi": metadata.get("doi") or doi,
                    "publication_date": iso_date(parse_date(publication_date)),
                    "publication_year": publication_year(publication_date),
                    "github_url": github_url,
                    "owner": owner,
                    "repo": repo,
                }
            )
        if records:
            save_csv(pd.DataFrame.from_records(records), cache_path)

    return pd.DataFrame.from_records(records)

def zenodo_record_text_fields(record: dict[str, Any]) -> list[object]:
    """Collect Zenodo fields that may contain GitHub repository URLs.

    Parameters
    ----------
    record:
        Zenodo API record.

    Returns
    -------
    list[object]
        Candidate text fields for GitHub URL extraction.
    """

    metadata = record.get("metadata", {})
    fields: list[object] = [
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("notes"),
        metadata.get("custom"),
        record.get("doi_url"),
        record.get("links", {}),
    ]
    for identifier in metadata.get("related_identifiers", []) or []:
        fields.append(identifier.get("identifier"))
        fields.append(identifier.get("resource_type"))
    for reference in metadata.get("references", []) or []:
        fields.append(reference)
    for keyword in metadata.get("keywords", []) or []:
        fields.append(keyword)
    return fields

def fetch_zenodo_records(
    *,
    max_records: int | None = 500,
    year: int | None = None,
    page_size: int = 25,
    sleep_seconds: float = 1.0,
    progress_every: int = 10,
) -> pd.DataFrame:
    """Fetch Zenodo software records with GitHub links.

    Parameters
    ----------
    max_records:
        Maximum number of Zenodo records to inspect. Use ``None`` for all
        available pages, subject to API limits.
    year:
        Optional publication year. When provided, Zenodo is queried for this
        year only.
    page_size:
        Number of records requested per API page. Zenodo currently caps
        unauthenticated requests at 25 records per page, so the default stays
        at 25 to avoid requiring a Zenodo token.
    sleep_seconds:
        Delay between API pages.
    progress_every:
        Emit a flushed terminal progress line every N inspected records.

    Returns
    -------
    pandas.DataFrame
        One row per Zenodo record GitHub repository link.
    """

    session = build_session()
    records: list[dict[str, Any]] = []
    inspected = 0
    page = 1
    query = "resource_type.type:software"
    if year is not None:
        query += f" AND publication_date:[{year}-01-01 TO {year}-12-31]"
    while True:
        if max_records is not None and inspected >= max_records:
            break
        remaining = None if max_records is None else max_records - inspected
        size = page_size if remaining is None else min(page_size, remaining)
        size = min(size, 25)
        payload = get_json(
            session,
            ZENODO_RECORDS_API,
            params={
                "q": query,
                "sort": "oldest",
                "page": page,
                "size": size,
            },
            retries=8,
            sleep_seconds=5.0,
        )
        hits = payload.get("hits", {}).get("hits", [])
        if not hits:
            break
        for record in hits:
            inspected += 1
            if progress_every and (inspected == 1 or inspected % progress_every == 0):
                print(
                    f"[fetch:zenodo"
                    + (f":{year}" if year is not None else "")
                    + f"] inspected {inspected}"
                    + (f"/{max_records}" if max_records is not None else ""),
                    flush=True,
                )
            metadata = record.get("metadata", {})
            github_urls = extract_github_urls(*zenodo_record_text_fields(record))
            for github_url in github_urls:
                owner, repo = split_github_url(github_url)
                publication_date = metadata.get("publication_date") or record.get(
                    "created"
                )
                records.append(
                    {
                        "source": "zenodo",
                        "source_record_id": str(record.get("id")),
                        "source_url": record.get("links", {}).get("html"),
                        "title": metadata.get("title"),
                        "doi": record.get("doi"),
                        "publication_date": iso_date(parse_date(publication_date)),
                        "publication_year": publication_year(publication_date),
                        "github_url": github_url,
                        "owner": owner,
                        "repo": repo,
                    }
                )
        page += 1
        time.sleep(sleep_seconds)
    return pd.DataFrame.from_records(records)

def fetch_zenodo_records_by_year(
    *,
    start_year: int,
    end_year: int,
    max_records_per_year: int | None = 500,
    progress_every: int = 10,
) -> pd.DataFrame:
    """Fetch Zenodo software records year by year.

    Parameters
    ----------
    start_year:
        First publication year to query, inclusive.
    end_year:
        Last publication year to query, inclusive.
    max_records_per_year:
        Maximum number of Zenodo records to inspect per year. Use ``None`` for
        all records per year, subject to API limits.
    progress_every:
        Emit flushed progress lines every N inspected records.

    Returns
    -------
    pandas.DataFrame
        Combined Zenodo source records.
    """

    cache_path = RAW_DIR / "zenodo_records_by_year.csv"
    frames: list[pd.DataFrame] = []
    completed_years: set[int] = set()
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        if not cached.empty and "publication_year" in cached.columns:
            cached["publication_year"] = pd.to_numeric(
                cached["publication_year"],
                errors="coerce",
            )
            cached = cached[
                (cached["publication_year"] >= start_year)
                & (cached["publication_year"] <= end_year)
            ].copy()
            if not cached.empty:
                completed_years = set(cached["publication_year"].dropna().astype(int))
                frames.append(cached)
                print(
                    "[fetch:zenodo] resumed completed years from cache: "
                    + ", ".join(str(year) for year in sorted(completed_years)),
                    flush=True,
                )

    for year in range(start_year, end_year + 1):
        if year in completed_years:
            print(f"[fetch:zenodo] skipping cached year {year}", flush=True)
            continue
        print(
            f"[fetch:zenodo] starting year {year}"
            + (
                f" with max {max_records_per_year} records"
                if max_records_per_year is not None
                else ""
            ),
            flush=True,
        )
        frame = fetch_zenodo_records(
            max_records=max_records_per_year,
            year=year,
            progress_every=progress_every,
        )
        print(
            f"[fetch:zenodo] finished year {year}: {len(frame)} GitHub-linked records",
            flush=True,
        )
        frames.append(frame)
        if frames:
            combined = (
                pd.concat([f for f in frames if not f.empty], ignore_index=True)
                if any(not f.empty for f in frames)
                else pd.DataFrame()
            )
            save_csv(combined, cache_path)
            save_csv(combined, RAW_DIR / "zenodo_records.csv")
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def merge_source_records(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge source tables and deduplicate source-repository pairs.

    Parameters
    ----------
    frames:
        Source-specific record tables.

    Returns
    -------
    pandas.DataFrame
        Merged table sorted by publication date and source.
    """

    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["owner", "repo"])
    merged["repo_key"] = (
        merged["owner"].str.lower().fillna("")
        + "/"
        + merged["repo"].str.lower().fillna("")
    )
    merged = merged.drop_duplicates(
        subset=["source", "source_record_id", "repo_key"], keep="first"
    )
    merged = merged.sort_values(
        by=["publication_year", "publication_date", "source", "repo_key"],
        na_position="last",
    ).reset_index(drop=True)
    return merged

def filter_records_by_year(
    records: pd.DataFrame,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
) -> pd.DataFrame:
    """Filter records by source publication or archival year.

    Parameters
    ----------
    records:
        Source records to filter.
    start_year:
        Earliest publication year to keep, inclusive.
    end_year:
        Latest publication year to keep, inclusive.

    Returns
    -------
    pandas.DataFrame
        Filtered records.
    """

    if records.empty or (start_year is None and end_year is None):
        return records
    filtered = records.copy()
    filtered["publication_year"] = pd.to_numeric(
        filtered["publication_year"], errors="coerce"
    )
    if start_year is not None:
        filtered = filtered[filtered["publication_year"] >= start_year]
    if end_year is not None:
        filtered = filtered[filtered["publication_year"] <= end_year]
    return filtered.reset_index(drop=True)

def fetch_sources(
    *,
    include_joss: bool,
    include_zenodo: bool,
    joss_max_records: int | None,
    zenodo_max_records: int | None,
    skip_crossref: bool,
    start_year: int | None = None,
    end_year: int | None = None,
    zenodo_by_year: bool = False,
    progress_every: int = 10,
) -> pd.DataFrame:
    """Fetch selected source cohorts and write raw and processed outputs.

    Parameters
    ----------
    include_joss:
        Whether to fetch JOSS records.
    include_zenodo:
        Whether to fetch Zenodo software records.
    joss_max_records:
        Optional JOSS test-run cap.
    zenodo_max_records:
        Optional Zenodo test-run cap.
    skip_crossref:
        Whether to skip Crossref DOI lookups for JOSS publication dates.
    start_year:
        Earliest source publication or archival year to keep, inclusive.
    end_year:
        Latest source publication or archival year to keep, inclusive.
    zenodo_by_year:
        Whether to query Zenodo separately for every source year. In this mode,
        ``zenodo_max_records`` is interpreted as a per-year cap.
    progress_every:
        Emit flushed terminal progress lines every N records.

    Returns
    -------
    pandas.DataFrame
        Merged source records.
    """

    frames: list[pd.DataFrame] = []
    if include_joss:
        joss = fetch_joss_records(
            max_records=joss_max_records,
            use_crossref=not skip_crossref,
            progress_every=progress_every,
        )
        save_csv(joss, RAW_DIR / "joss_records.csv")
        frames.append(joss)
    if include_zenodo:
        if zenodo_by_year:
            if start_year is None or end_year is None:
                raise ValueError("--zenodo-by-year requires --start-year and --end-year.")
            zenodo = fetch_zenodo_records_by_year(
                start_year=start_year,
                end_year=end_year,
                max_records_per_year=zenodo_max_records,
                progress_every=progress_every,
            )
        else:
            zenodo = fetch_zenodo_records(
                max_records=zenodo_max_records,
                progress_every=progress_every,
            )
        save_csv(zenodo, RAW_DIR / "zenodo_records.csv")
        frames.append(zenodo)
    merged = merge_source_records(frames)
    merged = filter_records_by_year(
        merged,
        start_year=start_year,
        end_year=end_year,
    )
    save_csv(merged, RAW_DIR / "source_records.csv")
    write_json(
        RAW_DIR / "source_summary.json",
        {
            "rows": int(len(merged)),
            "sources": sorted(merged["source"].unique().tolist())
            if not merged.empty
            else [],
            "github_repositories": int(merged["repo_key"].nunique())
            if "repo_key" in merged
            else 0,
        },
    )
    return merged

def load_source_records(path: Path = RAW_DIR / "source_records.csv") -> pd.DataFrame:
    """Load previously fetched source records.

    Parameters
    ----------
    path:
        CSV path written by :func:`fetch_sources`.

    Returns
    -------
    pandas.DataFrame
        Source records.
    """

    return pd.read_csv(path)

def sample_source_records(
    *,
    input_path: Path = RAW_DIR / "source_records.csv",
    output_path: Path = PROCESSED_DIR / "source_records_sampled.csv",
    include_all_joss: bool = True,
    zenodo_per_year: int = 1000,
    seed: int = 42,
    deduplicate_zenodo_repositories: bool = True,
) -> pd.DataFrame:
    """Create a practical analysis cohort from full source records.

    The full source table can be very large, especially for Zenodo. This helper
    keeps all JOSS records as the strict software-publication cohort and samples
    a reproducible Zenodo comparison cohort per publication year.

    Parameters
    ----------
    input_path:
        Full source records CSV.
    output_path:
        Destination CSV for the sampled analysis cohort.
    include_all_joss:
        Whether to keep all JOSS records.
    zenodo_per_year:
        Maximum number of Zenodo records to sample per publication year.
    seed:
        Random seed for reproducible sampling.
    deduplicate_zenodo_repositories:
        Whether to collapse Zenodo records to one row per repository and year
        before sampling. This reduces release-density bias.

    Returns
    -------
    pandas.DataFrame
        Sampled analysis cohort.
    """

    records = pd.read_csv(input_path)
    if records.empty:
        save_csv(records, output_path)
        return records
    records["publication_year"] = pd.to_numeric(
        records["publication_year"],
        errors="coerce",
    )

    frames: list[pd.DataFrame] = []
    if include_all_joss:
        frames.append(records[records["source"] == "joss"].copy())

    zenodo = records[records["source"] == "zenodo"].copy()
    if not zenodo.empty:
        zenodo = zenodo.sort_values(
            ["publication_year", "repo_key", "publication_date", "source_record_id"],
            na_position="last",
        )
        if deduplicate_zenodo_repositories:
            zenodo = zenodo.drop_duplicates(
                subset=["publication_year", "repo_key"],
                keep="first",
            )
        sampled_years: list[pd.DataFrame] = []
        for _, group in zenodo.groupby("publication_year", dropna=True):
            if len(group) > zenodo_per_year:
                sampled_years.append(
                    group.sample(n=zenodo_per_year, random_state=seed)
                )
            else:
                sampled_years.append(group)
        if sampled_years:
            frames.append(pd.concat(sampled_years, ignore_index=True))

    sampled = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=records.columns)
    )
    sampled = sampled.sort_values(
        ["source", "publication_year", "repo_key", "source_record_id"],
        na_position="last",
    ).reset_index(drop=True)
    save_csv(sampled, output_path)
    write_json(
        output_path.with_suffix(".summary.json"),
        {
            "input_rows": int(len(records)),
            "sampled_rows": int(len(sampled)),
            "include_all_joss": include_all_joss,
            "zenodo_per_year": int(zenodo_per_year),
            "seed": int(seed),
            "deduplicate_zenodo_repositories": bool(deduplicate_zenodo_repositories),
            "rows_by_source": sampled["source"].value_counts().to_dict()
            if "source" in sampled
            else {},
        },
    )
    return sampled
# %% END