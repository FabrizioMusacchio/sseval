# GitHub-linked published and archived scientific software records with repository activity metrics, 2016-2026

## Data availability

The data files described here are not distributed as part of the GitHub repository. To use the published dataset, download the associated Zenodo archive:

```text
https://doi.org/10.5281/zenodo.23151326
```

Alternatively, the data can be regenerated with the `sseval` pipeline as described below.

This dataset was created for an exploratory analysis of published or archived scientific software projects that link to public GitHub repositories. It combines source records from the Journal of Open Source Software (JOSS) and Zenodo software records with GitHub-derived repository metadata and first-year activity metrics.

The dataset supports a descriptive analysis of how GitHub-linked scientific software records have grown over time and how often these repositories show visible development and sustainability signals, including documentation infrastructure, issues, pull requests, and commits.

The associated analysis pipeline is available at:

```text
https://github.com/FabrizioMusacchio/sseval
```

## Scope
The source records cover publication or archival years 2016-2026. The year 2026 is included in the source data because the dataset was collected during 2026, but users should treat 2026 as incomplete for time-series interpretation. The preprint figure based on this dataset uses 2016-2025 to avoid an artificial end-of-series decrease caused by the incomplete 2026 cohort.

This dataset is not intended to be a complete census of all scientific software on GitHub. It represents observable cohorts of software that have either been published in JOSS or archived as Zenodo software records and that contain resolvable GitHub repository links.

## Data sources

### Journal of Open Source Software (JOSS)
JOSS records were collected from accepted JOSS paper metadata. JOSS is used as a curated research-software publication cohort. For each record, the pipeline extracted publication metadata and resolved the associated GitHub repository when available.

Source used by the pipeline:

```text
https://github.com/openjournals/joss-papers
```

### Zenodo
Zenodo records were collected from the public Zenodo API using the software resource-type filter:

```text
resource_type.type:software
```

Only records with a detected GitHub repository link were retained. GitHub links were extracted from metadata fields, related identifiers, descriptions, and external links where available.

Source used by the pipeline:

```text
https://zenodo.org/api/records
```

## Pipeline overview
The dataset was generated with the `sseval` pipeline. In brief, the workflow was:

1. Fetch JOSS and Zenodo source records for 2016-2026.
2. Extract and normalize GitHub repository links.
3. Merge source records into a unified source table.
4. Build a practical analysis cohort containing all JOSS records and a reproducible Zenodo subcohort.
5. Collect public GitHub repository metadata and first-year activity metrics for the analysis cohort.
6. Aggregate repository-level metrics by source and publication or archival year.

The recommended pipeline commands corresponding to this dataset were:

```bash
sseval fetch-sources --joss --zenodo --zenodo-by-year --zenodo-max-records 10000 --start-year 2016 --end-year 2026 --skip-crossref --progress-every 100
sseval sample-sources --zenodo-per-year 1000 --seed 42
sseval collect-github-metrics --source-records data/processed/source_records_sampled.csv --n-jobs 1 --progress-every 10
sseval aggregate
```

## Sampling strategy
The full source table contains 82,307 source records and 75,421 distinct GitHub repositories after source-level normalization. Collecting detailed GitHub metrics for every source record is slow because GitHub search endpoints for issues and pull requests are rate-limited.

For the repository-activity analysis, the processed analysis cohort therefore keeps:

- all JOSS records
- a reproducible Zenodo subcohort of up to 1,000 deduplicated Zenodo-linked repositories per year

The Zenodo sampling seed was:

```text
42
```

The sampled analysis cohort contains 14,693 rows:

- JOSS: 3,693 rows
- Zenodo: 11,000 rows

## Activity window
Repository activity was counted in the first 365 days after the source publication or archival date. This window was used to make projects from different cohort years more comparable.

For each repository, the pipeline counted:

- issues created in the first year
- pull requests created in the first year
- commits on the default branch in the first year

The dataset also includes binary indicators for whether at least one issue, pull request, or commit was detected during that first-year window.

## Documentation signal
The documentation signal is a heuristic infrastructure signal, not a documentation-quality score. A repository was marked as having a documentation signal if the pipeline detected at least one of the following:

- `docs/` directory
- Read the Docs configuration file
- Read the Docs link in repository metadata or README
- `mkdocs.yml`
- Sphinx-style documentation files such as `docs/conf.py`
- GitHub Pages or project documentation links in repository metadata or README

## Included files

### `raw/`

- `joss_records.csv`: JOSS source records with detected GitHub repositories.
- `zenodo_records.csv`: Zenodo software records with detected GitHub repositories.
- `zenodo_records_by_year.csv`: Zenodo records collected through year-wise API queries.
- `source_records.csv`: Unified source table containing JOSS and Zenodo records.
- `source_summary.json`: Summary of the unified source table.

### `processed/`

- `source_records_sampled.csv`: Analysis cohort containing all JOSS records and the sampled Zenodo comparison cohort.
- `source_records_sampled.summary.json`: Sampling metadata.
- `github_metrics.csv`: Repository-level GitHub metadata and first-year activity metrics for the sampled analysis cohort.

### `results/csv/`

- `annual_summary.csv`: Aggregated annual summary by source and publication or archival year.
- `github_metrics.csv`: Copy of the repository-level GitHub metrics used by the aggregation step.

The ZIP archive intentionally excludes `github_metrics_partial.csv`, which is an intermediate resume cache produced during long GitHub metric collection runs.

## Main columns
Common source-record columns:

- `source`: Data source (`joss` or `zenodo`).
- `source_record_id`: Source-specific record identifier.
- `source_url`: URL of the source record.
- `title`: Source-record title.
- `doi`: DOI where available.
- `publication_date`: Publication or archival date.
- `publication_year`: Year derived from `publication_date`.
- `github_url`: Detected GitHub repository URL.
- `owner`: GitHub repository owner.
- `repo`: GitHub repository name.
- `repo_key`: Normalized `owner/repo` key.

Additional repository-metric columns:

- `github_reachable`: Whether the GitHub repository was reachable through the API.
- `repo_full_name`: GitHub repository full name.
- `repo_created_at`, `repo_pushed_at`, `repo_updated_at`: GitHub timestamp metadata.
- `repo_default_branch`: Default branch reported by GitHub.
- `repo_archived`, `repo_disabled`, `repo_fork`: Repository status flags.
- `repo_stars`, `repo_forks`, `repo_open_issues_count`: GitHub repository counters.
- `has_documentation_signal`: Combined documentation-infrastructure signal.
- `activity_window_start`, `activity_window_end`: First-year activity window.
- `issues_first_year`: Number of issues created in the first-year window.
- `pull_requests_first_year`: Number of pull requests created in the first-year window.
- `commits_first_year`: Number of commits detected on the default branch in the first-year window.
- `has_issue_first_year`, `has_pull_request_first_year`, `has_commit_first_year`: Binary first-year activity indicators.
- `metric_error`: Error message if metric collection failed for a repository.

Aggregated annual-summary columns:

- `project_count`: Number of source records in the cohort.
- `documentation_count`, `documentation_percent`: Documentation-signal counts and percentages.
- `issue_project_count`, `issue_project_percent`: Projects with at least one first-year issue.
- `pull_request_project_count`, `pull_request_project_percent`: Projects with at least one first-year pull request.
- `commit_project_count`, `commit_project_percent`: Projects with at least one first-year commit.
- `issues_mean`, `issues_median`: Mean and median first-year issues.
- `pull_requests_mean`, `pull_requests_median`: Mean and median first-year pull requests.
- `commits_mean`, `commits_median`: Mean and median first-year commits.
- `cumulative_project_count`: Cumulative project count by source.

## Limitations
This dataset is exploratory and should be interpreted with care.

- JOSS is curated and peer-reviewed, but selective and community-specific.
- Zenodo software records are broad and heterogeneous, and are not necessarily peer-reviewed.
- Software without explicit GitHub links is not included.
- Software hosted outside GitHub is not included in the repository-metric analysis.
- Repository renames, transfers, deletions, private repositories, or archived states may affect metric collection.
- Documentation detection is heuristic and may miss documentation hosted elsewhere.
- Issue and pull-request counts depend on GitHub search indexing and API availability.
- Commit counts are based on the API-visible history of the default branch, not all branches.
- 2026 is incomplete and should not be used for final trend interpretation unless explicitly treated as a partial year.

## Suggested citation
If you use these data for scientific purposes, please cite the associated Zenodo archive:

```text
Musacchio, F. (2026). GitHub-linked published and archived scientific software records with repository activity metrics, 2016-2026 [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.23151326
```

Please also cite or link the associated analysis code repository where appropriate:

```text
https://github.com/FabrizioMusacchio/sseval
```
