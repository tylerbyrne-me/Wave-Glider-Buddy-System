import argparse
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlmodel import select

from app.core import models
from app.core.db import SQLModelSession, sqlite_engine


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("offload_utc_repair")


TARGET_FIELDS = [
    "arrival_date",
    "time_first_command_sent_utc",
    "offload_start_time_utc",
    "offload_end_time_utc",
    "departure_date",
]


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _to_utc(value).isoformat()


def _candidate_has_any_target_value(log: models.OffloadLog) -> bool:
    for field_name in TARGET_FIELDS:
        if getattr(log, field_name, None) is not None:
            return True
    return False


def _shift_row_values(log: models.OffloadLog, hours: int = -3) -> Dict[str, Optional[datetime]]:
    shifted: Dict[str, Optional[datetime]] = {}
    delta = timedelta(hours=hours)
    for field_name in TARGET_FIELDS:
        current = getattr(log, field_name, None)
        shifted[field_name] = (_to_utc(current) + delta) if current is not None else None
    return shifted


def _offload_sort_key(log: models.OffloadLog) -> datetime:
    ts = log.offload_end_time_utc or log.offload_start_time_utc or log.log_timestamp_utc
    ts = _to_utc(ts)
    return ts if ts is not None else datetime.min.replace(tzinfo=timezone.utc)


def _refresh_station_rollup(session: SQLModelSession, station_id: str) -> None:
    station = session.get(models.StationMetadata, station_id)
    if not station:
        return
    logs = list(
        session.exec(
            select(models.OffloadLog).where(models.OffloadLog.station_id == station_id)
        ).all()
    )
    if not logs:
        return
    latest = max(logs, key=_offload_sort_key)
    ts = latest.offload_end_time_utc or latest.offload_start_time_utc or latest.log_timestamp_utc
    if ts is not None:
        station.last_offload_timestamp_utc = ts
    if latest.was_offloaded is not None:
        station.was_last_offload_successful = latest.was_offloaded
    session.add(station)


def _build_query(
    season_year: Optional[int],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> Any:
    stmt = select(models.OffloadLog).where(models.OffloadLog.created_by_source == "user")
    if season_year is not None:
        stmt = stmt.where(models.OffloadLog.field_season_year == season_year)
    if start_date is not None:
        stmt = stmt.where(models.OffloadLog.log_timestamp_utc >= start_date)
    if end_date is not None:
        stmt = stmt.where(models.OffloadLog.log_timestamp_utc <= end_date)
    stmt = stmt.order_by(models.OffloadLog.station_id, models.OffloadLog.id)
    return stmt


def _build_audit_rows(logs: Iterable[models.OffloadLog]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in logs:
        shifted = _shift_row_values(log, hours=-3)
        row: Dict[str, Any] = {
            "offload_log_id": log.id,
            "station_id": log.station_id,
            "field_season_year": log.field_season_year,
            "logged_by_username": log.logged_by_username,
            "created_by_source": log.created_by_source,
            "updated_by_source": log.updated_by_source,
            "updated_at_utc": _format_dt(log.updated_at_utc),
            "log_timestamp_utc": _format_dt(log.log_timestamp_utc),
        }
        for field_name in TARGET_FIELDS:
            row[f"{field_name}_before"] = _format_dt(getattr(log, field_name, None))
            row[f"{field_name}_after"] = _format_dt(shifted[field_name])
        rows.append(row)
    return rows


def _write_audit_files(audit_rows: List[Dict[str, Any]], output_dir: Path, run_label: str) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"offload_utc_repair_{run_label}_{ts}"
    json_path = output_dir / f"{base_name}.json"
    csv_path = output_dir / f"{base_name}.csv"

    with json_path.open("w", encoding="utf-8") as jf:
        json.dump(audit_rows, jf, indent=2)

    fieldnames = list(audit_rows[0].keys()) if audit_rows else [
        "offload_log_id",
        "station_id",
        "field_season_year",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        for row in audit_rows:
            writer.writerow(row)

    return json_path, csv_path


def _count_column_changes(audit_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {field: 0 for field in TARGET_FIELDS}
    for row in audit_rows:
        for field in TARGET_FIELDS:
            if row.get(f"{field}_before") != row.get(f"{field}_after"):
                counts[field] += 1
    return counts


def run_repair(
    apply: bool,
    season_year: Optional[int],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    limit: Optional[int],
    output_dir: Path,
) -> None:
    with SQLModelSession(sqlite_engine) as session:
        stmt = _build_query(season_year=season_year, start_date=start_date, end_date=end_date)
        logs = list(session.exec(stmt).all())
        if limit is not None:
            logs = logs[:limit]
        candidates = [log for log in logs if _candidate_has_any_target_value(log)]

        logger.info("Scanned user logs: %s", len(logs))
        logger.info("Repair candidates with target datetime values: %s", len(candidates))
        if not candidates:
            logger.info("No candidates found. Exiting.")
            return

        audit_rows = _build_audit_rows(candidates)
        run_label = "apply" if apply else "dry_run"
        json_path, csv_path = _write_audit_files(audit_rows, output_dir=output_dir, run_label=run_label)
        logger.info("Audit JSON: %s", json_path)
        logger.info("Audit CSV: %s", csv_path)

        changed_by_column = _count_column_changes(audit_rows)
        logger.info("Column-level planned changes: %s", changed_by_column)

        if not apply:
            logger.info("Dry run only; no database writes performed.")
            return

        affected_station_ids = set()
        now_utc = datetime.now(timezone.utc)
        for log in candidates:
            shifted_values = _shift_row_values(log, hours=-3)
            for field_name, shifted in shifted_values.items():
                setattr(log, field_name, shifted)
            log.updated_by_source = "utc_repair_cli"
            log.updated_at_utc = now_utc
            session.add(log)
            affected_station_ids.add(log.station_id)

        for station_id in affected_station_ids:
            _refresh_station_rollup(session, station_id)

        session.commit()
        logger.info("Applied -3h correction to %s rows", len(candidates))
        logger.info("Recomputed station rollups for %s stations", len(affected_station_ids))


def run_restore(audit_json: Path, output_dir: Path) -> None:
    if not audit_json.exists():
        raise FileNotFoundError(f"Audit file not found: {audit_json}")
    with audit_json.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        raise ValueError("Audit JSON format invalid; expected a list of row objects.")
    if not rows:
        logger.info("Audit file is empty; nothing to restore.")
        return

    restored: List[Dict[str, Any]] = []
    affected_station_ids = set()
    with SQLModelSession(sqlite_engine) as session:
        for row in rows:
            log_id = row.get("offload_log_id")
            if log_id is None:
                continue
            log = session.get(models.OffloadLog, int(log_id))
            if not log:
                continue
            for field_name in TARGET_FIELDS:
                before_val = _parse_iso_datetime(row.get(f"{field_name}_before"))
                setattr(log, field_name, before_val)
            log.updated_by_source = "utc_repair_restore_cli"
            log.updated_at_utc = datetime.now(timezone.utc)
            session.add(log)
            affected_station_ids.add(log.station_id)
            restored.append({"offload_log_id": log_id, "station_id": log.station_id})

        for station_id in affected_station_ids:
            _refresh_station_rollup(session, station_id)
        session.commit()

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    restored_path = output_dir / f"offload_utc_restore_{ts}.json"
    with restored_path.open("w", encoding="utf-8") as fh:
        json.dump(restored, fh, indent=2)
    logger.info("Restored rows: %s", len(restored))
    logger.info("Restore receipt: %s", restored_path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-time Station Offload UTC repair CLI (-3h correction)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repair updates. Default behavior is dry-run only.",
    )
    parser.add_argument(
        "--season-year",
        type=int,
        default=None,
        help="Optional field_season_year filter.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional UTC lower bound on log_timestamp_utc (ISO-8601).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional UTC upper bound on log_timestamp_utc (ISO-8601).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of rows to process (for staged rollout).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data_store/offload_utc_repair_audits",
        help="Directory to write audit artifacts.",
    )
    parser.add_argument(
        "--restore-audit-json",
        type=str,
        default=None,
        help="Restore mode: replay *_before values from a prior audit JSON.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    if args.restore_audit_json:
        run_restore(audit_json=Path(args.restore_audit_json).resolve(), output_dir=output_dir)
        return

    start_date = _parse_iso_datetime(args.start_date)
    end_date = _parse_iso_datetime(args.end_date)
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be greater than end_date.")
    run_repair(
        apply=bool(args.apply),
        season_year=args.season_year,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
