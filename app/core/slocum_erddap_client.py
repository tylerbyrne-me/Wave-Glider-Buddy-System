"""
Slocum ERDDAP client - Ocean Track Slocum glider data.

Single source of truth for fetching Slocum tabledap data from ERDDAP.
Used by exploration API, map telemetry endpoint, mirror sync, and CLI/scripts.
Server URL is read from app config (slocum_erddap_server).
"""

import io
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd
from erddapy import ERDDAP

from ..config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

def _get_erddap_server() -> str:
    """ERDDAP server URL from config (default Ocean Track)."""
    return getattr(settings, "slocum_erddap_server", "https://erddap.oceantrack.org/erddap")


DEFAULT_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "depth",
    "temperature",
    "salinity",
]

# Four variables for map track: time, lat, lon, depth
TRACK_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "depth",
]

# Variables for Slocum mission dashboard charts (includes lat/lon for map/forecast reuse)
SLOCUM_DASHBOARD_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "m_depth",
    "m_altitude",
    "m_raw_altitude",
    "m_water_depth",
    "c_pitch",
    "m_pitch",
    "m_roll",
    "c_heading",
    "m_heading",
    "c_fin",
    "m_fin",
    "m_battery",
    "m_coulomb_amphr_total",
]

# Variables for CTD sensor card (conductivity, temperature, pressure, salinity, density)
SLOCUM_CTD_VARIABLES = [
    "time",
    "depth",
    "conductivity",
    "temperature",
    "pressure",
    "salinity",
    "density",
]

# Variables for daily pilot checklist autofill (wishlist; absent vars dropped per-dataset).
SLOCUM_CHECKLIST_VARIABLES = [
    "time",
    "latitude",
    "longitude",
    "m_depth",
    "m_altitude",
    "m_water_depth",
    "c_pitch",
    "m_pitch",
    "m_roll",
    "c_heading",
    "m_heading",
    "c_fin",
    "m_fin",
    "m_battery",
    "m_coulomb_amphr_total",
    "m_coulomb_current",
    "m_vacuum",
    "m_leakdetect_voltage",
    "m_leakdetect_voltage_forward",
    "m_leakdetect_voltage_science",
    "c_de_oil_vol",
    "m_de_oil_vol",
    "c_ballast_pumped",
    "m_ballast_pumped",
    "c_battpos",
    "m_battpos",
    "m_depth_rate_avg_final",
    "m_bms_pitch_current",
    "m_bms_aft_current",
    "m_bms_ebay_current",
    "m_speed",
    "m_final_water_vx",
    "m_final_water_vy",
    "m_gps_lat",
    "m_gps_lon",
    "c_wpt_lat",
    "c_wpt_lon",
    "density",
]

# Timeout in seconds for ERDDAP HTTP requests (avoids hanging on slow/unresponsive server)
ERDDAP_TIMEOUT = 30
# Retry transient connection errors (e.g. remote host closed connection, timeouts)
ERDDAP_RETRY_ATTEMPTS = 3
ERDDAP_RETRY_DELAY_SECONDS = 2

# In-memory cache for dataset time extent probes (dataset_id -> (min_iso, max_iso, monotonic_time))
_EXTENT_CACHE: dict[str, tuple[str, str, float]] = {}
_EXTENT_CACHE_TTL_SECONDS = 600

# In-memory cache for dataset variable inventories (dataset_id -> (frozenset[str], monotonic_time))
_VARIABLES_CACHE: dict[str, tuple[frozenset[str], float]] = {}
_VARIABLES_CACHE_TTL_SECONDS = 3600


def _requests_kwargs() -> dict:
    """
    HTTP kwargs for erddapy requests.

    erddapy caches responses via functools.lru_cache, so requests_kwargs values must be
    hashable (no nested dicts). gzip/deflate is negotiated by requests/urllib by default,
    so we only pass a scalar timeout here.
    """
    return {"timeout": ERDDAP_TIMEOUT}


def list_dataset_variables(dataset_id: str, *, use_cache: bool = True) -> frozenset[str]:
    """
    Return the set of variable names exposed by a tabledap dataset.

    Uses ERDDAP /info/{dataset_id}/index.csv. Cached briefly so sync/fetch paths
    do not re-hit info on every bundle.
    """
    now = time.monotonic()
    if use_cache and dataset_id in _VARIABLES_CACHE:
        cached_vars, cached_at = _VARIABLES_CACHE[dataset_id]
        if (now - cached_at) < _VARIABLES_CACHE_TTL_SECONDS:
            return cached_vars

    server = _get_erddap_server().rstrip("/")
    url = f"{server}/info/{dataset_id}/index.csv"
    try:
        resp = httpx.get(url, timeout=ERDDAP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except Exception as err:
        logger.warning("ERDDAP info request failed for %s: %s", dataset_id, err)
        return frozenset()

    variables: set[str] = set()
    for line in resp.text.splitlines():
        if not line.startswith("variable,"):
            continue
        parts = line.split(",")
        if len(parts) > 1 and parts[1].strip():
            variables.add(parts[1].strip())

    frozen = frozenset(variables)
    _VARIABLES_CACHE[dataset_id] = (frozen, now)
    return frozen


def filter_available_variables(
    dataset_id: str,
    variables: list[str],
    *,
    use_cache: bool = True,
) -> list[str]:
    """
    Drop variables that are not present on the dataset.

    Policy: variable lists are wishlists. Missions publish different sensors, so we
    always pull what is available and never fail the whole request because one
    optional column is missing. ERDDAP returns HTTP 400 if any requested tabledap
    variable is absent (e.g. m_altitude on many Ocean Track deployments).
    """
    available = list_dataset_variables(dataset_id, use_cache=use_cache)
    if not available:
        # Info endpoint failed — do not prune; let ERDDAP validate / best-effort retry.
        return list(variables)

    kept: list[str] = []
    missing: list[str] = []
    for name in variables:
        if name in available:
            kept.append(name)
        else:
            missing.append(name)

    if missing:
        logger.debug(
            "Slocum dataset %s missing variables (dropped from request): %s",
            dataset_id,
            ", ".join(missing),
        )
    if "time" not in kept and "time" in available and "time" in variables:
        kept.insert(0, "time")
    return kept


def _is_http_client_error(err: Exception, *codes: int) -> bool:
    status = getattr(getattr(err, "response", None), "status_code", None)
    if status in codes:
        return True
    text = str(err)
    return any(str(code) in text for code in codes)


def _is_http_400(err: Exception) -> bool:
    return _is_http_client_error(err, 400)


def _is_query_reject(err: Exception) -> bool:
    """True for ERDDAP 400/404 rejects (bad vars, empty match with orderByClosest, etc.)."""
    return _is_http_client_error(err, 400, 404)


def _merge_on_time(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Outer-merge DataFrames on the ERDDAP time column (keeps all available sensors)."""
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    time_col = _find_time_column(merged) or "time"
    for frame in frames[1:]:
        other_time = _find_time_column(frame) or time_col
        if other_time != time_col and other_time in frame.columns:
            frame = frame.rename(columns={other_time: time_col})
        merged = merged.merge(frame, on=time_col, how="outer", suffixes=("", "_dup"))
        dup_cols = [c for c in merged.columns if c.endswith("_dup")]
        if dup_cols:
            merged = merged.drop(columns=dup_cols)
    if time_col in merged.columns:
        merged = merged.sort_values(time_col).reset_index(drop=True)
    return merged


def _execute_erddap_download(
    e: ERDDAP,
    server_functions: list[str],
    to_pandas_kw: dict,
    pandas_kwargs: Optional[dict],
) -> pd.DataFrame:
    if server_functions:
        return _fetch_via_server_functions(e, server_functions, pandas_kwargs)
    return e.to_pandas(**to_pandas_kw)


def _fetch_variables_best_effort(
    e: ERDDAP,
    variables: list[str],
    server_functions: list[str],
    to_pandas_kw: dict,
    pandas_kwargs: Optional[dict],
    dataset_id: str,
) -> pd.DataFrame:
    """
    Pull each requested variable independently and outer-merge on time.

    Used when a multi-variable ERDDAP request fails (typically 400 from one missing
    or incompatible column). Successful sensors are kept; failures are logged and
    skipped so the overall fetch still succeeds with partial data.
    """
    if not variables:
        return pd.DataFrame()

    time_present = "time" in variables
    sensor_vars = [v for v in variables if v != "time"]
    if not sensor_vars:
        e.variables = ["time"] if time_present else variables
        return _execute_erddap_download(e, server_functions, to_pandas_kw, pandas_kwargs)

    frames: list[pd.DataFrame] = []
    for sensor in sensor_vars:
        request_vars = ["time", sensor] if time_present else [sensor]
        e.variables = request_vars
        try:
            part = _execute_erddap_download(e, server_functions, to_pandas_kw, pandas_kwargs)
            if part is not None and not part.empty:
                frames.append(part)
        except Exception as err:
            logger.debug(
                "Slocum dataset %s skipped unavailable/failed variable %s: %s",
                dataset_id,
                sensor,
                err,
            )
    if not frames:
        return pd.DataFrame()
    return _merge_on_time(frames)


def _find_time_column(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        if str(col).startswith("time"):
            return str(col)
    return None


def _build_server_functions(
    order_by_max_time: bool,
    order_by_closest_minutes: Optional[int],
) -> list[str]:
    """
    ERDDAP server-side functions to append to a download URL.

    These cannot go through erddapy's constraints dict: erddapy quotes constraint
    values (producing malformed strings like orderByMax("time")""), so we append
    them to the URL directly instead.
    """
    functions: list[str] = []
    if order_by_max_time:
        functions.append('orderByMax("time")')
    if order_by_closest_minutes and order_by_closest_minutes > 0:
        functions.append(f'orderByClosest("time,{order_by_closest_minutes} minutes")')
    return functions


def _fetch_via_server_functions(
    e: ERDDAP,
    server_functions: list[str],
    pandas_kwargs: Optional[dict],
) -> pd.DataFrame:
    """
    Fetch a tabledap CSV using ERDDAP server-side functions.

    Builds the base download URL via erddapy (variables + time constraints), appends
    the raw server functions, then fetches with httpx and parses like erddapy would.
    ERDDAP tabledap CSV normally includes a units row after the header; skip it unless
    the caller already provided skiprows.
    """
    url = e.get_download_url(response="csv")
    for func in server_functions:
        url += "&" + func
    resp = httpx.get(url, timeout=ERDDAP_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    read_kwargs = dict(pandas_kwargs or {})
    read_kwargs.setdefault("skiprows", [1])
    return pd.read_csv(io.StringIO(resp.text), **read_kwargs)


def _parse_erddap_time(value: object) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if hasattr(parsed, "to_pydatetime"):
        parsed = parsed.to_pydatetime()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ============================================================================
# Main Functions
# ============================================================================

def fetch_slocum_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    variables: Optional[list[str]] = None,
    pandas_kwargs: Optional[dict] = None,
    order_by_max_time: bool = False,
    order_by_closest_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch Slocum tabledap data from Ocean Track ERDDAP as a pandas DataFrame.

    Sync function; call from async code via asyncio.to_thread().

    Variable lists are treated as wishlists: the client asks ERDDAP for whatever
    sensors the dataset actually exposes and continues when some are missing.
    Dashboard, CTD, track, exploration, and CLI all share this path.

    Args:
        dataset_id: ERDDAP dataset_id (e.g. peggy_20250522_206_delayed).
        time_start: Start time ISO 8601. At least one of time_start/time_end required unless
            order_by_max_time is True.
        time_end: End time ISO 8601.
        variables: Optional wishlist of variable names; defaults to DEFAULT_VARIABLES.
            Unavailable names are dropped before the request.
        pandas_kwargs: Optional dict for pandas.read_csv.
        order_by_max_time: When True, fetch only the row with maximum time (extent probe).
        order_by_closest_minutes: When set, add ERDDAP orderByClosest decimation.

    Returns:
        DataFrame with available requested variables (missing sensors simply absent).

    Raises:
        Exception: On ERDDAP request or parse errors that cannot be recovered by
            pruning variables / best-effort per-sensor fetches.
    """
    requested = list(variables or DEFAULT_VARIABLES)
    # Skip inventory lookup for tiny probes (orderByMax time-only) to keep them cheap.
    if not (order_by_max_time and requested == ["time"]):
        vars_ = filter_available_variables(dataset_id, requested)
    else:
        vars_ = requested
    if not vars_:
        logger.warning(
            "No requested variables available on dataset %s (requested=%s)",
            dataset_id,
            ", ".join(requested),
        )
        return pd.DataFrame()

    server = _get_erddap_server()
    e = ERDDAP(server=server, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = dataset_id

    constraints: dict[str, str] = {}
    if not order_by_max_time:
        if time_start is not None:
            constraints["time>="] = time_start
        if time_end is not None:
            constraints["time<="] = time_end

    e.constraints = constraints
    e.variables = vars_
    active_decimation = order_by_closest_minutes
    server_functions = _build_server_functions(order_by_max_time, active_decimation)
    logger.debug(
        "Fetching Slocum dataset %s from %s (start=%s end=%s orderByMax=%s decimate=%s vars=%s)",
        dataset_id,
        server,
        time_start,
        time_end,
        order_by_max_time,
        active_decimation,
        vars_,
    )
    to_pandas_kw = {"requests_kwargs": _requests_kwargs()}
    if pandas_kwargs:
        to_pandas_kw.update(pandas_kwargs)

    df: pd.DataFrame | None = None
    refreshed_inventory = False
    for attempt in range(ERDDAP_RETRY_ATTEMPTS):
        try:
            df = _execute_erddap_download(e, server_functions, to_pandas_kw, pandas_kwargs)
            break
        except OSError as err:
            if attempt < ERDDAP_RETRY_ATTEMPTS - 1:
                logger.warning(
                    "ERDDAP connection error for %s (attempt %s/%s): %s; retrying in %ss",
                    dataset_id, attempt + 1, ERDDAP_RETRY_ATTEMPTS, err, ERDDAP_RETRY_DELAY_SECONDS,
                )
                time.sleep(ERDDAP_RETRY_DELAY_SECONDS)
            else:
                logger.warning(f"ERDDAP fetch failed for {dataset_id}: {err}")
                raise
        except Exception as err:
            # If orderByClosest itself triggers a 400/404, retry once without decimation.
            if (
                active_decimation
                and _is_query_reject(err)
                and server_functions
                and any(f.startswith("orderByClosest") for f in server_functions)
            ):
                logger.warning(
                    "ERDDAP returned %s with orderByClosest for %s; retrying without decimation",
                    getattr(getattr(err, "response", None), "status_code", "reject"),
                    dataset_id,
                )
                active_decimation = None
                server_functions = _build_server_functions(order_by_max_time, None)
                continue

            # Refresh variable inventory and prune again (stale cache / weird reject).
            if _is_http_400(err) and not refreshed_inventory and len(vars_) > 1:
                refreshed_inventory = True
                refreshed = filter_available_variables(
                    dataset_id, requested, use_cache=False
                )
                if refreshed and refreshed != vars_:
                    logger.warning(
                        "ERDDAP 400 for %s; retrying with refreshed variable list (%s -> %s)",
                        dataset_id,
                        len(vars_),
                        len(refreshed),
                    )
                    vars_ = refreshed
                    e.variables = vars_
                    continue

            # Ultimate fallback: pull each sensor alone and keep whatever succeeds.
            if _is_http_400(err) and len(vars_) > 1 and not order_by_max_time:
                logger.warning(
                    "ERDDAP 400 for %s multi-variable request; falling back to per-variable best-effort fetch",
                    dataset_id,
                )
                df = _fetch_variables_best_effort(
                    e, vars_, server_functions, to_pandas_kw, pandas_kwargs, dataset_id
                )
                break

            # Empty match (common with narrow windows) — return empty rather than fail sync.
            if _is_http_client_error(err, 404) and not order_by_max_time:
                logger.debug(
                    "ERDDAP returned 404 for %s (no matching rows for window/vars); returning empty frame",
                    dataset_id,
                )
                df = pd.DataFrame()
                break

            if attempt < ERDDAP_RETRY_ATTEMPTS - 1:
                err_msg = str(err).lower()
                if "connection" in err_msg or "forcibly closed" in err_msg or "timeout" in err_msg or "10054" in err_msg:
                    logger.warning(
                        "ERDDAP request error for %s (attempt %s/%s): %s; retrying in %ss",
                        dataset_id, attempt + 1, ERDDAP_RETRY_ATTEMPTS, err, ERDDAP_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(ERDDAP_RETRY_DELAY_SECONDS)
                    continue
            logger.warning(f"ERDDAP fetch failed for {dataset_id}: {err}")
            raise
    if df is not None and not df.empty:
        logger.debug(f"Fetched {len(df)} rows for dataset {dataset_id}")
    return df if df is not None else pd.DataFrame()


def fetch_dataset_max_time(dataset_id: str) -> Optional[datetime]:
    """Return the latest timestamp in a dataset via a tiny orderByMax probe."""
    df = fetch_slocum_data(
        dataset_id=dataset_id,
        variables=["time"],
        order_by_max_time=True,
    )
    if df is None or df.empty:
        return None
    time_col = _find_time_column(df)
    if not time_col:
        return None
    return _parse_erddap_time(df[time_col].iloc[-1])


def fetch_dataset_time_extent(
    dataset_id: str,
    *,
    use_cache: bool = True,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Return (min_time, max_time) for a dataset.

    Uses allDatasets metadata when available; falls back to orderByMax probe for max time.
    Results are cached briefly to avoid repeated metadata hits.
    """
    now = time.monotonic()
    if use_cache and dataset_id in _EXTENT_CACHE:
        min_iso, max_iso, cached_at = _EXTENT_CACHE[dataset_id]
        if (now - cached_at) < _EXTENT_CACHE_TTL_SECONDS:
            min_dt = _parse_erddap_time(min_iso) if min_iso else None
            max_dt = _parse_erddap_time(max_iso) if max_iso else None
            return min_dt, max_dt

    min_dt: Optional[datetime] = None
    max_dt: Optional[datetime] = None
    try:
        meta_df = list_slocum_datasets(dataset_ids=[dataset_id])
        if meta_df is not None and not meta_df.empty:
            row = meta_df.iloc[0]
            # ERDDAP csv/csvp often returns "minTime (UTC)" / "maxTime (UTC)".
            for col in meta_df.columns:
                col_lower = str(col).lower().replace(" ", "")
                if col_lower.startswith("mintime"):
                    min_dt = _parse_erddap_time(row[col])
                elif col_lower.startswith("maxtime"):
                    max_dt = _parse_erddap_time(row[col])
    except Exception as err:
        logger.debug("allDatasets extent lookup failed for %s: %s", dataset_id, err)

    if max_dt is None:
        try:
            max_dt = fetch_dataset_max_time(dataset_id)
        except Exception as err:
            # Large delayed datasets often time out on orderByMax; avoid failing the request.
            logger.warning(
                "orderByMax extent probe failed for %s: %s",
                dataset_id,
                err,
            )

    min_iso = min_dt.isoformat().replace("+00:00", "Z") if min_dt else ""
    max_iso = max_dt.isoformat().replace("+00:00", "Z") if max_dt else ""
    _EXTENT_CACHE[dataset_id] = (min_iso, max_iso, now)
    return min_dt, max_dt


def list_slocum_datasets(
    search_term: Optional[str] = None,
    dataset_ids: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Query ERDDAP for available Slocum datasets (metadata only).

    Sync function; call from async code via asyncio.to_thread().

    Args:
        search_term: Optional string to filter datasets by title (case-insensitive).
        dataset_ids: Optional explicit dataset IDs to constrain the server query.

    Returns:
        DataFrame with columns such as datasetID, title, institution, minTime, maxTime.
    """
    server = _get_erddap_server()
    e = ERDDAP(server=server, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = "allDatasets"
    # erddapy joins constraints as &{key}{value} and quotes string values, so the
    # regex operator must live in the key (datasetID=~) not the value. Otherwise
    # ERDDAP receives malformed constraints like datasetID"=~"(id)"".
    constraints: dict[str, str] = {}
    if dataset_ids:
        cleaned = [d.strip() for d in dataset_ids if d and d.strip()]
        if len(cleaned) == 1:
            constraints["datasetID="] = cleaned[0]
        elif cleaned:
            escaped = "|".join(cleaned)
            constraints["datasetID=~"] = f"^({escaped})$"
    else:
        pattern = getattr(settings, "slocum_erddap_dataset_id_filter", r".*(_realtime|_delayed)$")
        if pattern:
            constraints["datasetID=~"] = pattern
    e.constraints = constraints
    e.variables = ["datasetID", "title", "institution", "minTime", "maxTime"]
    logger.debug(f"Listing Slocum datasets from {server}")
    try:
        df = e.to_pandas(requests_kwargs=_requests_kwargs())
    except Exception as err:
        logger.warning(f"ERDDAP allDatasets request failed: {err}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if search_term and search_term.strip():
        term = search_term.strip().lower()
        if "title" in df.columns:
            mask = df["title"].astype(str).str.lower().str.contains(term, na=False)
            df = df.loc[mask]
    return df


def fetch_slocum_ctd_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    pandas_kwargs: Optional[dict] = None,
    order_by_closest_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch Slocum CTD data from ERDDAP."""
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=SLOCUM_CTD_VARIABLES,
        pandas_kwargs=pandas_kwargs,
        order_by_closest_minutes=order_by_closest_minutes,
    )


def fetch_slocum_track(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    order_by_closest_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch Slocum track data (time, latitude, longitude, depth) for map display."""
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=TRACK_VARIABLES,
        order_by_closest_minutes=order_by_closest_minutes,
    )


def fetch_slocum_dashboard_data(
    dataset_id: str,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    pandas_kwargs: Optional[dict] = None,
    order_by_closest_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch Slocum dashboard bundle (includes latitude/longitude for map/forecast reuse)."""
    return fetch_slocum_data(
        dataset_id=dataset_id,
        time_start=time_start,
        time_end=time_end,
        variables=SLOCUM_DASHBOARD_VARIABLES,
        pandas_kwargs=pandas_kwargs,
        order_by_closest_minutes=order_by_closest_minutes,
    )
