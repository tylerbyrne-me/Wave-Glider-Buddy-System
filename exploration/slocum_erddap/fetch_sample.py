"""
Slocum Glider ERDDAP sample fetch (exploration only).

Uses app.core.slocum_erddap_client for fetch logic. Run from project root with
WorkPython conda env so that the app package is importable.

  conda activate WorkPython
  python exploration/slocum_erddap/fetch_sample.py
  python exploration/slocum_erddap/fetch_sample.py -d peggy_20250522_206_delayed -s 2025-08-01 -e 2025-08-31 -o my_test.csv
"""
import argparse
import sys
from pathlib import Path

# Project root (parent of exploration/) so "app" is importable
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.core.slocum_erddap_client import (
    DEFAULT_VARIABLES,
    fetch_slocum_data,
)

DEFAULT_DATASET_ID = "peggy_20250522_206_delayed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Slocum ERDDAP data for testing. Uses Ocean Track server."
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default=DEFAULT_DATASET_ID,
        help=f"ERDDAP dataset_id (default: {DEFAULT_DATASET_ID})",
    )
    parser.add_argument(
        "--start",
        "-s",
        default="2025-08-18T00:00:00Z",
        help="Start time ISO 8601 (default: 2025-08-18T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        "-e",
        default="2025-08-25T23:59:59Z",
        help="End time ISO 8601 (default: 2025-08-25T23:59:59Z)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write CSV to this path (default: exploration folder sample_slocum_erddap.csv)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print shape and time range only; do not write CSV",
    )
    args = parser.parse_args()

    time_start = args.start if "T" in args.start else f"{args.start}T00:00:00Z"
    time_end = args.end if "T" in args.end else f"{args.end}T23:59:59Z"

    df = fetch_slocum_data(args.dataset, time_start, time_end, variables=DEFAULT_VARIABLES)
    if df is None or df.empty:
        print("No data returned.")
        return

    print(f"Dataset: {args.dataset}")
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    time_col = [c for c in df.columns if "time" in c.lower()]
    if time_col:
        print(f"Time range: {df[time_col[0]].min()} -> {df[time_col[0]].max()}")
    if not args.summary_only:
        print(df.head())

    if not args.summary_only:
        out_path = args.output
        if out_path is None:
            out_path = Path(__file__).resolve().parent / "sample_slocum_erddap.csv"
        else:
            out_path = Path(out_path)
        df.to_csv(out_path, index=False)
        print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
