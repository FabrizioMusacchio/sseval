# Scripts for evaluating sustainability signals in published scientific software

This project, `sseval`, builds an exploratory dataset of formally published or archived scientific software projects that link to public GitHub repositories. The goal is to support the poster and manuscript idea that publishing software is not the same as making it sustainable, reusable, documented, maintained, and community-ready.

The analysis intentionally avoids claiming to measure "all scientific software on GitHub". Instead, it defines observable cohorts from public sources that already imply some publication or archival step.

## Research question
How has the number of published scientific software projects linked to GitHub changed over time, and how often do these projects show visible sustainability signals such as dedicated documentation, issues, pull requests, and ongoing commit activity?

## Data sources

### Strict cohort: JOSS
The strict cohort is based on accepted papers from the Journal of Open Source Software (JOSS). JOSS is useful here because it is explicitly a journal for research software, and accepted papers are expected to reference public software repositories.

The collector reads accepted JOSS paper metadata from:

```text
https://github.com/openjournals/joss-papers
```

For each paper, the pipeline resolves publication metadata from the JOSS repository. Older JOSS papers expose the software repository directly in legacy XML metadata. Newer JOSS papers are stored as JATS and Crossref XML; for these records, the pipeline reads the Crossref `Software archive` relation, resolves the archive DOI through Zenodo, and extracts the GitHub repository link from the Zenodo software metadata. This keeps the repository link traceable instead of guessing from paper references.

### Broad cohort: Zenodo software records
The broad cohort is based on public Zenodo records with `resource_type.type:software` and at least one GitHub repository link in record metadata, related identifiers, descriptions, or external links.

The collector reads public records from:

```text
https://zenodo.org/api/records
```

Zenodo does not require an API token for public records, but it may rate-limit high-volume requests.

### Optional comparison cohort: Papers with Code
The code is structured so that a Papers with Code collector can be added later. This would be useful as a machine-learning-heavy comparison cohort, but it is not the default because it is not representative of all computational science.

## GitHub metrics
For each repository, the pipeline collects public GitHub metadata and computes metrics in a first-year window after publication or archival:

- whether the repository is reachable
- repository creation date, default branch, stars, forks, archived status
- documentation signals
- issues created in the first 12 months after publication
- pull requests created in the first 12 months after publication
- commits on the default branch in the first 12 months after publication

The first-year window is used because older projects have had more time to accumulate activity. Cohort-year plots therefore compare projects more fairly than all-time totals.

All-time totals can be added later, but they should be interpreted separately.

## Documentation signals
The current documentation signal is intentionally broad and transparent. A repository is marked as having dedicated documentation infrastructure if at least one of the following is detected:

- `.readthedocs.yaml` or `.readthedocs.yml`
- a `readthedocs.io` link in the repository homepage, description, or README
- a `docs/` directory
- `mkdocs.yml`
- Sphinx-style files such as `docs/conf.py`
- GitHub Pages or project documentation links in repository metadata or README

This is not a perfect documentation-quality score. It is a visible infrastructure signal.

## API tokens
Zenodo does not require a token for public records.

GitHub does not strictly require a token for public repositories, but a token is strongly recommended. Without one, rate limits are too low for a meaningful full scan.

Create a fine-grained or classic GitHub token with public repository read access and set:

```bash
export GITHUB_TOKEN="ghp_..."
```

Alternatively, create a project-local `.env` or `github_token.env` file:

```text
GITHUB_TOKEN=ghp_...
```

Both `.env` and `github_token.env` are ignored by `.gitignore`.

No write permissions are required.

## Conda environment
Recommended environment:

```bash
conda env create -f environment.yml
conda activate sseval
```

The environment is specified as:

- Python 3.12
- pandas
- matplotlib
- seaborn
- requests
- PyYAML
- tqdm
- python-dateutil
- ipykernel

If you prefer a project-local environment:

```bash
conda env create -p ./.conda_env -f environment.yml
conda activate ./.conda_env
```

## Running the pipeline
From this folder:

```bash
sseval run-all --joss --zenodo --zenodo-max-records 500
```

For a small test run:

```bash
sseval run-all --joss --joss-max-records 25 --zenodo --zenodo-max-records 25
```

The recommended poster workflow can also be run step by step:

```bash
sseval fetch-sources --joss --zenodo --zenodo-by-year --zenodo-max-records 10000 --start-year 2016 --end-year 2026 --skip-crossref --progress-every 100
sseval sample-sources --zenodo-per-year 1000 --seed 42
sseval collect-github-metrics --source-records data/processed/source_records_sampled.csv --n-jobs 1 --progress-every 10
sseval aggregate
sseval plot
```

The command prints ordinary flushed progress lines in addition to `tqdm`, for example every 10 records by default. This helps in terminals where dynamic progress bars are buffered.

```bash
sseval run-all --joss --zenodo --zenodo-max-records 5000 --progress-every 10
```

GitHub metric collection is resumable. During `collect-github-metrics`, partial results are written to:

```text
data/processed/github_metrics_partial.csv
```

If a run is interrupted, start the same command again. Already completed source-repository records are reused and skipped. If a final `data/processed/github_metrics.csv` exists but no partial cache exists, the final table is also reused as a cache for matching source records.

The full GitHub-metrics run over all source records remains possible:

```bash
sseval collect-github-metrics --source-records data/raw/source_records.csv --n-jobs 1 --progress-every 10
```

However, this can take several days for large source tables because GitHub Search is rate-limited. The sampled cohort is the recommended default for poster figures.

## Sampling the analysis cohort
The full source table can be much larger than is practical for GitHub metric collection. For poster-scale analyses, the recommended cohort keeps all JOSS records and samples a reproducible Zenodo comparison cohort per year after deduplicating Zenodo repositories within each year:

```bash
sseval sample-sources --zenodo-per-year 1000 --seed 42
```

This writes:

```text
data/processed/source_records_sampled.csv
```

Collect GitHub metrics for this sampled cohort with:

```bash
sseval collect-github-metrics --source-records data/processed/source_records_sampled.csv --n-jobs 1 --progress-every 10
```

## Time window
There are two different time concepts:

1. **Source cohort year:** the publication or archival year of the JOSS paper or Zenodo software record.
2. **Activity window:** the first 365 days after the source publication or archival date, used for issues, pull requests, and commits.

By default, the pipeline keeps all source years returned by the selected source collectors. You can restrict the source cohort years explicitly:

```bash
sseval run-all --joss --zenodo --zenodo-max-records 5000 --start-year 2010 --end-year 2026
```

For a 15-year view from 2012 to 2026:

```bash
sseval run-all --joss --zenodo --zenodo-max-records 5000 --start-year 2012 --end-year 2026
```

For a 20-year view from 2007 to 2026:

```bash
sseval run-all --joss --zenodo --zenodo-max-records 5000 --start-year 2007 --end-year 2026
```

Note that Zenodo records are queried sorted from oldest to newest unless `--zenodo-by-year` is used. Without `--zenodo-by-year`, `--zenodo-max-records` limits how many Zenodo software records are inspected before year filtering. With `--zenodo-by-year`, Zenodo is queried separately for each year from `--start-year` to `--end-year`, and `--zenodo-max-records` is interpreted as the per-year inspection cap.

For the poster cohort starting with the first JOSS publication year:

```bash
sseval fetch-sources --joss --zenodo --zenodo-by-year --zenodo-max-records 10000 --start-year 2016 --end-year 2026 --skip-crossref --progress-every 100
```

## Parallelization
GitHub metric collection can be parallelized:

```bash
sseval run-all --joss --zenodo --zenodo-max-records 5000 --n-jobs 2
```

Use this cautiously. GitHub's authenticated core API limit is high, but the search API used for issue and pull-request counts is much lower, about 30 requests per minute. Each repository needs separate issue and pull-request search calls. For stable runs with issue and pull-request metrics, use `--n-jobs 1`. Higher values may trigger rate limits and produce partial metric tables with `metric_error` entries. The client waits and retries once when GitHub returns a reset time, but parallel runs can still exhaust the search bucket faster than it refills.

## Output files
Raw source records:

```text
data/raw/
```

Processed merged records:

```text
data/processed/
```

CSV tables for inspection and plotting:

```text
results/csv/
```

Plots:

```text
results/png/
results/pdf/
```

Each plot is written as both PNG and PDF.

## Planned plots
The plotting step currently prepares:

- annual number of GitHub-linked published/archived software repositories
- cumulative number of repositories
- share of repositories with documentation signals by cohort year
- share of repositories with at least one issue in the first year
- average and median number of issues in the first year
- share of repositories with at least one pull request in the first year
- average and median number of pull requests in the first year
- share of repositories with at least one commit in the first year
- average and median number of commits in the first year

## Methodological limitations
This is an exploratory analysis, not a complete census of scientific software.

Important limitations:

- JOSS is high-quality but selective and biased toward software communities that publish in JOSS.
- Zenodo software records are broad but not necessarily peer-reviewed.
- GitHub-linked Zenodo records may miss software archived elsewhere or software without explicit GitHub links.
- Documentation detection is heuristic and may undercount projects with external documentation not linked from the repository.
- Commit counts are collected from the default branch by API-visible history, not from every branch.
- Issues and pull requests are counted through GitHub search queries and depend on repository visibility and GitHub indexing.
- Repository renames, transfers, deletions, and archived states can affect measurement.

These limitations should be stated on any poster or manuscript panel that uses the plots.

## Citation
If you use `sseval` for scientific work, please cite the software archive:


> Musacchio, F. (2026). *sseval: Evaluating sustainability signals in published scientific software* (Version v0.0.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.23153713


Please, also cite the accompagning preprint 

> Musacchio,  F., and Fuhrmann,  M., *What Transforms Project-Specific Code into Sustainable Scientific Software? Principles for Developing Reusable Open-Source Research Tools*. Preprints 2026, 2026100523. https://doi.org/10.20944/preprints202610.0523.v1

If you use the associated dataset or reproduce the published plots, please cite the Zenodo archive:

> Musacchio, F. (2026). *GitHub-linked published and archived scientific software records with repository activity metrics*, 2016-2026 [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.23151326

