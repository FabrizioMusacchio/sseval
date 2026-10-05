"""Run the full scientific software evaluation pipeline.

This script is a thin wrapper around the package CLI. It exists for users who
prefer running a visible script from the project folder instead of installing
the `sseval` command. All methods and outputs are implemented in the package
modules under `src/scientific_software_evaluation`.

author: Fabrizio Musacchio
date:   October 2026
"""
# %% IMPORTS
from scientific_software_evaluation.cli import main

# %% MAIN FUNCTION
def run() -> None:
    """Execute the command-line interface."""

    main()

# %% MAIN ENTRY POINT
if __name__ == "__main__":
    run()
# %% END