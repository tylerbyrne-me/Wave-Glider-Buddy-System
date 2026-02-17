"""
Slocum ERDDAP fetch CLI.

Run from project root with WorkPython:
  python -m app.cli.slocum_cli --dataset peggy_20250522_206_delayed
  python -m app.cli.slocum_cli --dataset cabot_20240901_198_realtime --start 2024-09-01 --end 2024-09-19
  python -m app.cli.slocum_cli --summary-only
"""
import argparse
import sys
from pathlib import Path

from ..core.slocum_erddap_client import DEFAULT_VARIABLES, fetch_slocum_data

DEFAULT_DATASET_ID = "peggy_20250522_206_delayed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Slocum ERDDAP data (Ocean Track). Uses app config for server URL."
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
        default=None,
        help="Start time ISO 8601 or date (e.g. 2024-09-01). Omit with --end to fetch full dataset.",
    )
    parser.add_argument(
        "--end",
        "-e",
        default=None,
        help="End time ISO 8601 or date (e.g. 2024-09-19). Omit with --start to fetch full dataset.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write CSV to this path (default: slocum_fetch.csv in cwd)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print shape and time range only; do not write CSV",
    )
    args = parser.parse_args()

    if (args.start is None) != (args.end is None):
        print("Error: provide both --start and --end, or omit both to fetch the full dataset.", file=sys.stderr)
        sys.exit(1)

    time_start: str | None = None
    time_end: str | None = None
    if args.start is not None and args.end is not None:
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
        out_path = Path(args.output) if args.output else Path("slocum_fetch.csv")
        df.to_csv(out_path, index=False)
        print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
