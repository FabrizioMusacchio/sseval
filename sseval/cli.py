"""Command-line interface for the scientific software evaluation pipeline.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from __future__ import annotations

import argparse
from pathlib import Path

from .config import CSV_DIR, PDF_DIR, PNG_DIR, PROCESSED_DIR, RAW_DIR
from .metrics import aggregate_by_year, collect_github_metrics
from .plotting import create_all_plots
from .sources import fetch_sources, sample_source_records
from .utils import ensure_directories
# %% FUNCTIONS
def add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """Add source-fetching flags shared by multiple subcommands.

    Parameters
    ----------
    parser:
        Parser to modify.
    """

    parser.add_argument("--joss", action="store_true", help="Fetch the JOSS cohort.")
    parser.add_argument(
        "--zenodo", action="store_true", help="Fetch the Zenodo software cohort."
    )
    parser.add_argument(
        "--joss-max-records",
        type=int,
        default=None,
        help="Optional cap for JOSS records, useful for test runs.",
    )
    parser.add_argument(
        "--zenodo-max-records",
        type=int,
        default=500,
        help=(
            "Optional cap for Zenodo records. Without --zenodo-by-year this is "
            "the total number inspected; with --zenodo-by-year it is the "
            "number inspected per year."
        ),
    )
    parser.add_argument(
        "--zenodo-by-year",
        action="store_true",
        help=(
            "Query Zenodo separately for each year from --start-year to "
            "--end-year. This gives a more balanced time series."
        ),
    )
    parser.add_argument(
        "--skip-crossref",
        action="store_true",
        help="Skip Crossref lookups for JOSS publication dates.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Earliest source publication or archival year to keep, inclusive.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Latest source publication or archival year to keep, inclusive.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print a flushed progress line every N records in addition to tqdm.",
    )


def add_metric_arguments(parser: argparse.ArgumentParser) -> None:
    """Add GitHub metric collection flags.

    Parameters
    ----------
    parser:
        Parser to modify.
    """

    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help=(
            "Number of parallel GitHub metric workers. Use cautiously because "
            "GitHub search has a low authenticated rate limit. Values above 1 "
            "are mainly useful when issue and pull-request counts are disabled "
            "in future variants."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print a flushed progress line every N records in addition to tqdm.",
    )
    parser.add_argument(
        "--source-records",
        default=None,
        help=(
            "Optional source-record CSV to collect metrics for. Defaults to "
            "data/raw/source_records.csv."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    Returns
    -------
    argparse.ArgumentParser
        Configured CLI parser.
    """

    parser = argparse.ArgumentParser(
        prog="sseval",
        description=(
            "Evaluate sustainability signals for published or archived "
            "scientific software linked to GitHub."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
        "fetch-sources", help="Fetch JOSS and/or Zenodo source records."
    )
    add_source_arguments(fetch_parser)

    metrics_parser = subparsers.add_parser(
        "collect-github-metrics",
        help="Collect GitHub documentation and activity metrics.",
    )
    add_metric_arguments(metrics_parser)

    sample_parser = subparsers.add_parser(
        "sample-sources",
        help="Create an analysis cohort from full source records.",
    )
    sample_parser.add_argument(
        "--input",
        default=str(RAW_DIR / "source_records.csv"),
        help="Full source-record CSV to sample from.",
    )
    sample_parser.add_argument(
        "--output",
        default=str(PROCESSED_DIR / "source_records_sampled.csv"),
        help="Destination CSV for sampled source records.",
    )
    sample_parser.add_argument(
        "--zenodo-per-year",
        type=int,
        default=1000,
        help="Maximum number of Zenodo records to sample per year.",
    )
    sample_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling.",
    )
    sample_parser.add_argument(
        "--no-deduplicate-zenodo",
        action="store_true",
        help="Sample Zenodo records without first deduplicating repositories per year.",
    )
    sample_parser.add_argument(
        "--exclude-joss",
        action="store_true",
        help="Do not include all JOSS records in the sampled cohort.",
    )

    subparsers.add_parser("aggregate", help="Aggregate metrics by source and year.")
    subparsers.add_parser("plot", help="Create PNG and PDF plots.")

    run_all_parser = subparsers.add_parser(
        "run-all", help="Fetch sources, collect metrics, aggregate, and plot."
    )
    add_source_arguments(run_all_parser)
    run_all_parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help=(
            "Number of parallel GitHub metric workers. Use cautiously because "
            "GitHub search has a low authenticated rate limit. Values above 1 "
            "can produce partial metric tables."
        ),
    )
    return parser


def prepare_output_directories() -> None:
    """Create all expected data and result directories."""

    ensure_directories([RAW_DIR, PROCESSED_DIR, CSV_DIR, PNG_DIR, PDF_DIR])
# %% MAIN FUNCTION
def main(argv: list[str] | None = None) -> None:
    """Run the command-line interface.

    Parameters
    ----------
    argv:
        Optional argument list for tests. When omitted, arguments are read from
        the command line.
    """

    prepare_output_directories()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "fetch-sources":
        if not args.joss and not args.zenodo:
            parser.error("Choose at least one source: --joss and/or --zenodo.")
        fetch_sources(
            include_joss=args.joss,
            include_zenodo=args.zenodo,
            joss_max_records=args.joss_max_records,
            zenodo_max_records=args.zenodo_max_records,
            skip_crossref=args.skip_crossref,
            start_year=args.start_year,
            end_year=args.end_year,
            zenodo_by_year=args.zenodo_by_year,
            progress_every=args.progress_every,
        )
    elif args.command == "collect-github-metrics":
        source_records = None
        if args.source_records:
            import pandas as pd

            source_records = pd.read_csv(args.source_records)
        collect_github_metrics(
            source_records=source_records,
            n_jobs=args.n_jobs,
            progress_every=args.progress_every,
        )
    elif args.command == "sample-sources":
        sample_source_records(
            input_path=Path(args.input),
            output_path=Path(args.output),
            include_all_joss=not args.exclude_joss,
            zenodo_per_year=args.zenodo_per_year,
            seed=args.seed,
            deduplicate_zenodo_repositories=not args.no_deduplicate_zenodo,
        )
    elif args.command == "aggregate":
        aggregate_by_year()
    elif args.command == "plot":
        create_all_plots()
    elif args.command == "run-all":
        if not args.joss and not args.zenodo:
            parser.error("Choose at least one source: --joss and/or --zenodo.")
        records = fetch_sources(
            include_joss=args.joss,
            include_zenodo=args.zenodo,
            joss_max_records=args.joss_max_records,
            zenodo_max_records=args.zenodo_max_records,
            skip_crossref=args.skip_crossref,
            start_year=args.start_year,
            end_year=args.end_year,
            zenodo_by_year=args.zenodo_by_year,
            progress_every=args.progress_every,
        )
        metrics = collect_github_metrics(
            records,
            n_jobs=args.n_jobs,
            progress_every=args.progress_every,
        )
        summary = aggregate_by_year(metrics)
        create_all_plots(summary)
# %% MAIN
if __name__ == "__main__":
    main()
# %% END