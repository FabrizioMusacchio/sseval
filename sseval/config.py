"""Project paths and default configuration values.

The constants in this module keep file locations and default API settings in
one place. This makes it easier to inspect and change the analysis without
searching through the individual collector and plotting modules.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
import os
from pathlib import Path
# %% PATHS AND DIRECTORIES
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = PROJECT_ROOT / "results"
CSV_DIR = RESULTS_DIR / "csv"
PNG_DIR = RESULTS_DIR / "png"
PDF_DIR = RESULTS_DIR / "pdf"
MATPLOTLIB_CONFIG_DIR = PROJECT_ROOT / ".matplotlib"

os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CONFIG_DIR))

JOSS_REPO_API_TREE = ("https://api.github.com/repos/openjournals/joss-papers/git/trees/master")
JOSS_RAW_BASE = "https://raw.githubusercontent.com/openjournals/joss-papers/master"
ZENODO_RECORDS_API = "https://zenodo.org/api/records"
CROSSREF_WORKS_API = "https://api.crossref.org/works"
GITHUB_API = "https://api.github.com"

DEFAULT_USER_AGENT = (
    "scientific-software-evaluation/0.1 "
    "(research-software-sustainability exploratory analysis)")
# %% END
