from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import math
import re
import string
import textwrap
import matplotlib as mpl
import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cmocean.cm as cmo
import matplotlib.dates as mdates
import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER
import numpy as np # type: ignore
import logging

from . import models
from .processors import (preprocess_ctd_df, preprocess_power_df,
                         preprocess_wave_df, preprocess_weather_df)
from .processors import preprocess_telemetry_df, telemetry_speed_over_ground_series

logger = logging.getLogger(__name__)

# PDF text uses Matplotlib’s font resolver only (not browser @font-face). Candidates are
# common Windows / server fonts verified with findfont(..., fallback_to_default=False) so
# we never ask Matplotlib to probe names that only exist in web CSS (e.g. Inter Tight).
_CANDIDATE_REPORT_PDF_FONTS: List[str] = [
    "Segoe UI",
    "Arial",
    "Calibri",
    "Cambria",
    "Verdana",
    "Lucida Sans Unicode",
    "Tahoma",
    "DejaVu Sans",
]


def _font_family_resolves(family: str) -> bool:
    try:
        path = font_manager.findfont(
            font_manager.FontProperties(family=family),
            fallback_to_default=False,
        )
    except (ValueError, RuntimeError, OSError):
        return False
    return bool(path)


def _resolved_report_pdf_font_stack() -> List[str]:
    picked: List[str] = []
    for candidate in _CANDIDATE_REPORT_PDF_FONTS:
        if not _font_family_resolves(candidate):
            continue
        if candidate not in picked:
            picked.append(candidate)
    return picked or ["DejaVu Sans"]


REPORT_PDF_FONT_STACK: List[str] = _resolved_report_pdf_font_stack()
REPORT_PDF_FONT_PRIMARY: str = REPORT_PDF_FONT_STACK[0]


@contextmanager
def report_pdf_rc_context():
    """Temporarily set matplotlib defaults for legacy PDF report figures."""
    primary = REPORT_PDF_FONT_PRIMARY
    with mpl.rc_context(
        {
            "font.family": primary,
            "font.sans-serif": [primary, "DejaVu Sans"],
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 9,
        }
    ):
        yield


def ensure_plots_dir():
    plots_dir = Path("waveglider_plots_temp")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir


def unwrap_degree_series(series: pd.Series) -> pd.Series:
    """Return a continuous (display-only) view of a 0..360 degree series.

    Uses ``numpy.unwrap`` on the radian-converted values so plotted lines do not jump
    by ~360 when the source angle wraps around 0/360. Original missing values are
    preserved as NaN so matplotlib still breaks the line where data is missing.
    Returned values may extend outside 0..360 by design (that is the unwrapping).
    """
    if series is None or series.empty:
        return series
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    valid_mask = np.isfinite(values)
    if not valid_mask.any():
        return pd.Series(values, index=series.index, name=series.name)

    unwrapped = np.full(values.shape, np.nan, dtype=float)
    # Unwrap each contiguous run of valid values independently so NaN gaps stay as gaps.
    in_run = False
    run_start = 0
    for idx in range(values.size):
        if valid_mask[idx] and not in_run:
            in_run = True
            run_start = idx
        elif not valid_mask[idx] and in_run:
            in_run = False
            run_slice = slice(run_start, idx)
            unwrapped[run_slice] = np.degrees(np.unwrap(np.radians(values[run_slice])))
    if in_run:
        run_slice = slice(run_start, values.size)
        unwrapped[run_slice] = np.degrees(np.unwrap(np.radians(values[run_slice])))

    return pd.Series(unwrapped, index=series.index, name=series.name)


def generate_power_plot(power_df, mission_id, hours_back=72):
    """Generates and saves a power trend plot. Returns the plot path or None if data is missing or an error occurs."""
    try:
        power_df = preprocess_power_df(power_df)
        if power_df.empty or "Timestamp" not in power_df.columns or power_df["Timestamp"].isnull().all():
            return None

        max_timestamp = power_df["Timestamp"].max()
        cutoff_time = max_timestamp - timedelta(hours=hours_back)
        recent_power = power_df[power_df["Timestamp"] > cutoff_time]
        if recent_power.empty:
            return None

        data_to_resample = recent_power.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        hourly_power = numeric_cols.resample("1h").mean()

        plots_dir = ensure_plots_dir()
        plot_path = plots_dir / f"power_trend_{mission_id}.png"

        plt.figure(figsize=(10, 6))
        if "BatteryWattHours" in hourly_power.columns:
            plt.plot(
                hourly_power.index,
                hourly_power["BatteryWattHours"],
                label="Battery (Wh)",
                color="blue",
            )
        if "SolarInputWatts" in hourly_power.columns:
            plt.plot(
                hourly_power.index,
                hourly_power["SolarInputWatts"],
                label="Solar Input (W)",
                color="orange",
            )
        if "PowerDrawWatts" in hourly_power.columns:
            plt.plot(
                hourly_power.index,
                hourly_power["PowerDrawWatts"],
                label="Power Draw (W)",
                color="red",
            )
        if "NetPowerWatts" in hourly_power.columns:
            plt.plot(
                hourly_power.index,
                hourly_power["NetPowerWatts"],
                label="Net Power (W)",
                color="green",
            )

        plt.title(f"Power Trends - Mission {mission_id}")
        plt.xlabel("Time")
        plt.ylabel("Power")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path, bbox_inches='tight')
        plt.close()
        return plot_path
    except Exception as e:
        logger.error(f"Error generating power plot: {e}", exc_info=True)
        return None


def generate_ctd_plot(ctd_df, mission_id, hours_back=24):
    """Generates and saves a CTD data trend plot. Returns the plot path or None if data is missing or an error occurs."""
    try:
        ctd_df = preprocess_ctd_df(ctd_df)
        if ctd_df.empty or "Timestamp" not in ctd_df.columns or ctd_df["Timestamp"].isnull().all():
            return None

        max_timestamp = ctd_df["Timestamp"].max()
        cutoff_time = max_timestamp - timedelta(hours=hours_back)
        recent_data = ctd_df[ctd_df["Timestamp"] > cutoff_time]
        if recent_data.empty:
            return None

        data_to_resample = recent_data.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        hourly_data = numeric_cols.resample("1h").mean()

        plots_dir = ensure_plots_dir()
        plot_path = plots_dir / f"ctd_trend_{mission_id}.png"

        fig, axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        if "WaterTemperature" in hourly_data.columns:
            axs[0].plot(
                hourly_data.index,
                hourly_data["WaterTemperature"],
                "r-",
                label="Water Temperature (°C)",
            )
            axs[0].set_ylabel("Temperature (°C)")
            axs[0].grid(True, alpha=0.3)
            axs[0].legend(loc="upper left")
        # Plot Conductivity on the second subplot, as Salinity is derived from it.
        if "Conductivity" in hourly_data.columns:
            axs[1].plot(
                hourly_data.index,
                hourly_data["Conductivity"],
                "orange",
                label="Conductivity (S/m)",
            )
        # Twin axis for Dissolved Oxygen on the Conductivity plot (axs[1])
        if "DissolvedOxygen" in hourly_data.columns:
            ax1_twin = axs[1].twinx()
            ax1_twin.plot(
                hourly_data.index, hourly_data["DissolvedOxygen"], "g--", label="O₂ (Hz)"
            )
            ax1_twin.set_ylabel("O₂ (Hz)", color="green")
            ax1_twin.tick_params(axis="y", labelcolor="green")
        axs[1].set_ylabel("Conductivity (S/m)")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc="upper left")
        # Plot Salinity on the third subplot
        if "Salinity" in hourly_data.columns:
            axs[2].plot(
                hourly_data.index, hourly_data["Salinity"], "b-", label="Salinity (PSU)"
            )
            axs[2].set_ylabel("Salinity (PSU)")
            axs[2].grid(True, alpha=0.3)
            axs[2].legend(loc="upper left")
        axs[2].set_xlabel("Time")
        plt.suptitle(f"CTD Data Trends - Last {hours_back} Hours")
        plt.tight_layout()
        plt.savefig(plot_path, bbox_inches='tight')
        plt.close()
        return plot_path
    except Exception as e:
        logger.error(f"Error generating CTD plot: {e}", exc_info=True)
        return None


def generate_weather_plot(weather_df, mission_id, hours_back=72):
    """Generates and saves a weather trend plot. Returns the plot path or None if data is missing or an error occurs."""
    try:
        weather_df = preprocess_weather_df(weather_df)
        if weather_df.empty or "Timestamp" not in weather_df.columns or weather_df["Timestamp"].isnull().all():
            return None

        max_timestamp = weather_df["Timestamp"].max()
        cutoff_time = max_timestamp - timedelta(hours=hours_back)
        recent_weather = weather_df[weather_df["Timestamp"] > cutoff_time]
        if recent_weather.empty:
            return None

        data_to_resample = recent_weather.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        hourly = numeric_cols.resample("1h").mean()

        plots_dir = ensure_plots_dir()
        plot_path = plots_dir / f"weather_trend_{mission_id}.png"

        plt.figure(figsize=(10, 6))
        if "AirTemperature" in hourly.columns:
            plt.plot(
                hourly.index,
                hourly["AirTemperature"],
                label="Air Temp (°C)",
                color="blue",
            )
        if "WindSpeed" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WindSpeed"], label="Wind Speed (kt)", color="green"
            )
        if "WindGust" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WindGust"], label="Wind Gust (kt)", color="red"
            )
        plt.title(f"Weather Trends - Mission {mission_id}")
        plt.xlabel("Time")
        plt.ylabel("Value")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path, bbox_inches='tight')
        plt.close()
        return plot_path
    except Exception as e:
        logger.error(f"Error generating weather plot: {e}", exc_info=True)
        return None


def generate_wave_plot(wave_df, mission_id, hours_back=72):
    """Generates and saves a wave condition trend plot. Returns the plot path or None if data is missing or an error occurs."""
    try:
        wave_df = preprocess_wave_df(wave_df)
        if wave_df.empty or "Timestamp" not in wave_df.columns or wave_df["Timestamp"].isnull().all():
            return None

        max_timestamp = wave_df["Timestamp"].max()
        cutoff_time = max_timestamp - timedelta(hours=hours_back)
        recent = wave_df[wave_df["Timestamp"] > cutoff_time]
        if recent.empty:
            return None

        data_to_resample = recent.set_index("Timestamp")
        numeric_cols = data_to_resample.select_dtypes(include=[np.number])
        hourly = numeric_cols.resample("1h").mean()

        plots_dir = ensure_plots_dir()
        plot_path = plots_dir / f"wave_trend_{mission_id}.png"

        plt.figure(figsize=(10, 6))
        if "SignificantWaveHeight" in hourly.columns:
            plt.plot(
                hourly.index,
                hourly["SignificantWaveHeight"],
                label="Wave Height (m)",
                color="blue",
            )
        if "WavePeriod" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WavePeriod"], label="Wave Period (s)", color="orange"
            )
        if "MeanWaveDirection" in hourly.columns:
            plt.plot(
                hourly.index,
                unwrap_degree_series(hourly["MeanWaveDirection"]),
                label="Wave Dir (°)",
                color="green",
            )
        plt.title(f"Wave Conditions - Mission {mission_id}")
        plt.xlabel("Time")
        plt.ylabel("Value")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path, bbox_inches='tight')
        plt.close()
        return plot_path
    except Exception as e:
        logger.error(f"Error generating wave plot: {e}", exc_info=True)
        return None


# --- PDF Report Plotting Functions ---
# These functions are designed to be called by the reporting module.
# They accept a matplotlib Axes object and draw onto it, rather than creating a new figure.

def _setup_report_map(ax, extent):
    """Configures a Cartopy map with basic features for PDF reports."""
    ax.set_extent(extent)
    ax.coastlines(resolution='10m')
    ax.add_feature(cfeature.LAND, facecolor='brown', zorder=0)
    ax.add_feature(cfeature.BORDERS, linestyle=':')
    g1 = ax.gridlines(draw_labels=True, linewidth=0.25, color='gray', alpha=0.5, linestyle='--')
    g1.top_labels = False
    g1.right_labels = False
    g1.xlabel_style = {'size': 10}
    g1.ylabel_style = {'size': 10}
    g1.xformatter = LONGITUDE_FORMATTER
    g1.yformatter = LATITUDE_FORMATTER

def _annotate_track_start_end(ax, tele):
    """Adds start and end markers to a track plot for PDF reports."""
    if tele.empty:
        return
    start = tele.iloc[0]
    end = tele.iloc[-1]
    ax.plot(start['longitude'], start['latitude'], marker='^', color='green', markersize=8, label='Start', transform=ccrs.Geodetic())
    ax.plot(end['longitude'], end['latitude'], marker='X', color='red', markersize=8, label='Current', transform=ccrs.Geodetic())
    ax.legend(loc='upper left')

# --- Telemetry-page layout helpers ----------------------------------------


def assign_note_letters(note_annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster-aware letter assignment.

    Notes that share a snapped (lat, lon) belong to the same cluster. Each
    cluster receives the next available cluster letter (A, B, ... Z, AA,
    AB, ...). Within a cluster, the first note keeps the cluster letter
    alone (e.g. "A"); subsequent notes get a numeric sub-index suffix
    (e.g. "A1", "A2"). The cluster letter and sub-index are also stored on
    the note dict so downstream code (the marker renderer and the notes
    page) can group cluster-mates together without re-parsing.

    Mutates and returns the same list. Notes that already carry a `letter`
    field are left alone.
    """
    cluster_alphabet = string.ascii_uppercase + "".join(
        f"A{ch}" for ch in string.ascii_uppercase
    )  # A..Z, AA..AZ — supports up to 52 distinct clusters

    cluster_letters: Dict[tuple, str] = {}
    cluster_counts: Dict[tuple, int] = {}
    next_cluster_index = 0

    for note in note_annotations:
        if note.get("letter"):
            continue
        latitude = note.get("latitude")
        longitude = note.get("longitude")
        if latitude is None or longitude is None:
            continue
        key = (round(float(latitude), 5), round(float(longitude), 5))
        if key not in cluster_letters:
            if next_cluster_index < len(cluster_alphabet):
                cluster_letters[key] = cluster_alphabet[next_cluster_index]
            else:
                cluster_letters[key] = f"#{next_cluster_index + 1}"
            cluster_counts[key] = 0
            next_cluster_index += 1
        cluster_letter = cluster_letters[key]
        sub_index = cluster_counts[key]
        cluster_counts[key] += 1
        note["cluster_letter"] = cluster_letter
        note["cluster_sub_idx"] = sub_index
        note["letter"] = cluster_letter if sub_index == 0 else f"{cluster_letter}{sub_index}"

    return note_annotations


def _bboxes_overlap(a, b, pad: float = 6.0) -> bool:
    """Return True if two display-coord bboxes overlap, allowing `pad` px of
    visual separation. The padding accounts for the rounded bbox decoration
    that `Text.get_window_extent` does not include in its returned extent.
    """
    return not (
        a.x1 + pad < b.x0
        or a.x0 - pad > b.x1
        or a.y1 + pad < b.y0
        or a.y0 - pad > b.y1
    )


def _create_marker_annotation(
    ax,
    label: str,
    lon: float,
    lat: float,
    dx_unit: int,
    dy_unit: int,
    standoff_pts: float,
):
    """Render a labelled marker callout offset from `(lon, lat)` with a
    leader line back to the point. Direction is given by the (dx, dy) unit
    vector in display space; magnitude by `standoff_pts`.
    """
    ha = "left" if dx_unit > 0 else ("right" if dx_unit < 0 else "center")
    va = "bottom" if dy_unit > 0 else ("top" if dy_unit < 0 else "center")
    return ax.annotate(
        label,
        xy=(lon, lat),
        xycoords=ax.transData,
        xytext=(dx_unit * standoff_pts, dy_unit * standoff_pts),
        textcoords="offset points",
        fontsize=7.5,
        fontweight="bold",
        ha=ha,
        va=va,
        color="black",
        bbox=dict(
            boxstyle="round,pad=0.30",
            facecolor="white",
            edgecolor="black",
            linewidth=0.8,
        ),
        arrowprops=dict(
            arrowstyle="-",
            color="black",
            linewidth=0.6,
            shrinkA=0,
            shrinkB=3,
        ),
        zorder=6,
    )


def _annotate_note_markers(
    ax,
    note_annotations: List[Dict[str, Any]],
) -> None:
    """Drop a lettered marker at each mission note's lat/lon.

    Notes that share a snapped (lat, lon) — typically because they matched the
    same nearest telemetry point — are clustered under a single auto-sized
    rounded label keyed by the cluster letter (e.g. "A" for a 1-note cluster
    or "A+4" for a 5-note cluster). The follow-up Mission Notes page lists
    each note individually as A, A1, A2, A3, A4 so readers can disambiguate.

    Each label is drawn off-set from its telemetry point with a leader line
    back to a small marker dot, so the text doesn't sit on top of the
    speed-coloured scatter. A short placement search picks the first
    candidate offset that doesn't overlap any previously-placed label —
    enough to keep nearby clusters (e.g. several notes at adjacent
    telemetry fixes) from stacking on top of each other.
    """
    if not note_annotations:
        return

    clusters: Dict[tuple, Dict[str, Any]] = {}
    cluster_order: List[tuple] = []
    for note in note_annotations:
        longitude = note.get("longitude")
        latitude = note.get("latitude")
        cluster_letter = str(
            note.get("cluster_letter") or note.get("letter") or ""
        ).strip()
        if longitude is None or latitude is None or not cluster_letter:
            continue
        key = (round(float(latitude), 5), round(float(longitude), 5))
        if key not in clusters:
            clusters[key] = {
                "letter": cluster_letter,
                "lat": float(latitude),
                "lon": float(longitude),
                "count": 0,
            }
            cluster_order.append(key)
        clusters[key]["count"] += 1

    fig = ax.get_figure()
    # Force a draw so the renderer is ready to compute window extents for
    # collision detection.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    try:
        west, east, south, north = ax.get_extent(crs=ccrs.PlateCarree())
        mid_lon = (west + east) / 2.0
        mid_lat = (south + north) / 2.0
    except Exception:
        mid_lon = mid_lat = None

    base_standoff_pts = 22  # display-point standoff between marker dot and label
    distance_multipliers = (1.0, 1.5, 2.2)

    placed_bboxes: List[Any] = []

    for key in cluster_order:
        cluster = clusters[key]
        if cluster["count"] == 1:
            label = cluster["letter"]
        else:
            label = f"{cluster['letter']}+{cluster['count'] - 1}"

        lon = cluster["lon"]
        lat = cluster["lat"]

        # Marker dot at the actual telemetry point — drawn once regardless of
        # which label position the search ends up choosing.
        ax.plot(
            lon,
            lat,
            marker="o",
            markerfacecolor="black",
            markeredgecolor="white",
            markeredgewidth=0.6,
            markersize=4.5,
            transform=ccrs.Geodetic(),
            zorder=5,
            linestyle="None",
        )

        # Direction preference: nudge the label toward the map centre so
        # edge points don't push their label off the page. Horizontal-first
        # ordering avoids stacking text on top of the (usually N-S) track.
        prefer_dx = -1 if (mid_lon is not None and lon > mid_lon) else 1
        prefer_dy = -1 if (mid_lat is not None and lat > mid_lat) else 1
        sorted_directions = [
            (prefer_dx, 0),
            (prefer_dx, prefer_dy),
            (prefer_dx, -prefer_dy),
            (0, prefer_dy),
            (-prefer_dx, prefer_dy),
            (-prefer_dx, 0),
            (0, -prefer_dy),
            (-prefer_dx, -prefer_dy),
        ]

        chosen_annotation = None
        chosen_bbox = None
        for distance_mult in distance_multipliers:
            for dx_unit, dy_unit in sorted_directions:
                annotation = _create_marker_annotation(
                    ax,
                    label,
                    lon,
                    lat,
                    dx_unit,
                    dy_unit,
                    base_standoff_pts * distance_mult,
                )
                bbox = annotation.get_window_extent(renderer)
                if not any(
                    _bboxes_overlap(bbox, existing) for existing in placed_bboxes
                ):
                    chosen_annotation = annotation
                    chosen_bbox = bbox
                    break
                annotation.remove()
            if chosen_annotation is not None:
                break

        if chosen_annotation is None:
            # Every candidate overlapped — keep the highest-priority direction
            # at maximum distance to at least minimise the visual mess.
            dx_unit, dy_unit = sorted_directions[0]
            chosen_annotation = _create_marker_annotation(
                ax,
                label,
                lon,
                lat,
                dx_unit,
                dy_unit,
                base_standoff_pts * distance_multipliers[-1],
            )
            chosen_bbox = chosen_annotation.get_window_extent(renderer)

        placed_bboxes.append(chosen_bbox)


def _pad_extent_to_aspect(
    extent: List[float],
    target_aspect: float,
) -> List[float]:
    """Expand the smaller dimension of `extent` so the geographic aspect of
    the data matches `target_aspect` (the visual width/height ratio of the
    subplot we're going to draw into). Eliminates the dead margins that
    appear when Cartopy's equal-aspect axes would otherwise letterbox the
    track inside its allotted cell.
    """
    if target_aspect <= 0:
        return extent
    west, east, south, north = extent
    lon_span = max(east - west, 1e-6)
    lat_span = max(north - south, 1e-6)
    mid_lat_rad = math.radians((north + south) / 2.0)
    cos_mid_lat = max(math.cos(mid_lat_rad), 1e-3)
    current_aspect = (lon_span * cos_mid_lat) / lat_span

    if current_aspect < target_aspect:
        # Subplot is wider than data → expand longitude.
        new_lon_span = (target_aspect * lat_span) / cos_mid_lat
        delta = (new_lon_span - lon_span) / 2.0
        return [west - delta, east + delta, south, north]
    if current_aspect > target_aspect:
        # Subplot is taller than data → expand latitude.
        new_lat_span = (lon_span * cos_mid_lat) / target_aspect
        delta = (new_lat_span - lat_span) / 2.0
        return [west, east, south - delta, north + delta]
    return extent


def plot_telemetry_page_with_notes(
    fig,
    df: pd.DataFrame,
    note_annotations: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Render the full-page telemetry-track report on `fig`.

    The map fills the entire page (with the standard title + colorbar),
    extent-padded so E-W or N-S dominant tracks both fill the page area
    instead of being letterboxed by Cartopy's equal-aspect projection.

    Mission notes are NOT rendered on this page — call
    `plot_mission_notes_page` afterwards to emit a follow-up page listing
    them. The map itself only shows the lettered markers.
    """
    if df.empty or 'longitude' not in df.columns or 'latitude' not in df.columns:
        ax = fig.add_subplot(1, 1, 1)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "No telemetry data in the selected range.",
            ha='center',
            va='center',
            transform=ax.transAxes,
        )
        return

    df = df.sort_values(by='lastLocationFix')
    df_clean = df.dropna(subset=['latitude', 'longitude'])
    if df_clean.empty:
        ax = fig.add_subplot(1, 1, 1)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "No valid telemetry coordinates in the selected range.",
            ha='center',
            va='center',
            transform=ax.transAxes,
        )
        return

    annotations = assign_note_letters(list(note_annotations or []))

    extent = [
        float(df_clean['longitude'].min()) - 0.05,
        float(df_clean['longitude'].max()) + 0.05,
        float(df_clean['latitude'].min()) - 0.05,
        float(df_clean['latitude'].max()) + 0.05,
    ]

    map_ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())

    # Estimate the page-content cell so we can pad the extent and avoid the
    # equal-aspect letterboxing that otherwise hides axis labels off-page.
    # The reserved 1.5"/2.0" leaves room for margins, title, and colorbar.
    fig_width_in, fig_height_in = fig.get_size_inches()
    target_aspect = max(fig_width_in - 1.5, 1e-3) / max(fig_height_in - 2.0, 1e-3)
    padded_extent = _pad_extent_to_aspect(extent, target_aspect)
    _setup_report_map(map_ax, padded_extent)

    norm = mcolors.Normalize(vmin=0, vmax=4)
    cmap = cmo.speed
    sog = telemetry_speed_over_ground_series(df_clean)
    color_values = sog if sog is not None and sog.notna().any() else "tab:blue"
    scatter = map_ax.scatter(
        df_clean['longitude'],
        df_clean['latitude'],
        c=color_values,
        cmap=cmap,
        norm=norm,
        s=20,
        linewidths=0,
        edgecolors="none",
        transform=ccrs.PlateCarree(),
    )
    cbar = fig.colorbar(scatter, ax=map_ax, orientation='vertical', shrink=0.8, pad=0.08)
    cbar.set_label('Speed Over Ground (knots)')

    _annotate_track_start_end(map_ax, df_clean)
    _annotate_note_markers(map_ax, annotations)

    start_time = df_clean['lastLocationFix'].min()
    latest_time = df_clean['lastLocationFix'].max()
    map_ax.set_title(
        f"Telemetry Track\n"
        f"{start_time.strftime('%Y-%m-%d %H:%M')} to {latest_time.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    fig.tight_layout(pad=3.0)


def plot_mission_notes_page(
    add_footer_and_save,
    note_annotations: List[Dict[str, Any]],
) -> None:
    """Render the mission notes list on its own page (auto-paginates).

    Notes are grouped by cluster: cluster-mates (A, A1, A2, ...) appear
    together before the next cluster (B, B1, ...) so the layout matches
    the marker scheme on the telemetry map. Layout/wrapping/pagination is
    delegated to the shared `render_text_sections` helper, so a long list
    naturally spills onto additional pages.
    """
    if not note_annotations:
        return

    annotations = assign_note_letters(list(note_annotations))

    sorted_annotations = sorted(
        annotations,
        key=lambda note: (
            note.get("cluster_letter") or note.get("letter") or "?",
            note.get("cluster_sub_idx", 0),
        ),
    )

    sections: List[Dict[str, Any]] = [
        {
            "heading": None,
            "lines": [
                "Mission notes for the report period, keyed by the letter shown on the telemetry map."
            ],
        }
    ]
    for note in sorted_annotations:
        event_time = note.get("event_time")
        if isinstance(event_time, datetime):
            event_time_text = event_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            event_time_text = "unknown time"
        letter = str(note.get("letter") or "?").strip()
        username = str(note.get("created_by_username") or "").strip()
        body_text = str(note.get("full_note_text") or "").strip()
        meta_line = (
            f"— {username} on {event_time_text}" if username else f"— {event_time_text}"
        )
        sections.append({
            "heading": f"{letter}  —  {event_time_text}",
            "lines": [body_text or "(no content)", meta_line],
        })

    render_text_sections(
        add_footer_and_save,
        page_title="Mission Notes",
        sections=sections,
    )


def plot_telemetry_for_report(
    ax,
    df: pd.DataFrame,
    note_annotations: Optional[List[Dict[str, Any]]] = None,
):
    """Single-axis telemetry plot for embedded/legacy use.

    Renders the speed-coloured track, start/end markers, and clustered
    lettered note markers on the supplied Axes. Callers wanting the full
    page + dedicated notes-page flow should use `plot_telemetry_page_with_notes`
    + `plot_mission_notes_page` instead.
    """
    df = df.sort_values(by='lastLocationFix')

    if df.empty or 'longitude' not in df.columns or 'latitude' not in df.columns:
        ax.text(0.5, 0.5, "No telemetry data in the selected range.", horizontalalignment='center', verticalalignment='center', transform=ax.transAxes)
        return

    start_time = df['lastLocationFix'].min()
    latest_time = df['lastLocationFix'].max()

    extent = [df['longitude'].min() - 0.05, df['longitude'].max() + 0.05, df['latitude'].min() - 0.05, df['latitude'].max() + 0.05]
    _setup_report_map(ax, extent)

    norm = mcolors.Normalize(vmin=0, vmax=4)
    cmap = cmo.speed
    sog = telemetry_speed_over_ground_series(df)
    color_values = sog if sog is not None and sog.notna().any() else "tab:blue"

    scatter = ax.scatter(df['longitude'], df['latitude'], c=color_values, cmap=cmap, norm=norm, s=20, linewidths=0, edgecolors="none", transform=ccrs.PlateCarree())

    fig = ax.get_figure()
    cbar = fig.colorbar(scatter, ax=ax, orientation='vertical', shrink=0.8, pad=0.08)
    cbar.set_label('Speed Over Ground (knots)')

    annotations = assign_note_letters(list(note_annotations or []))
    _annotate_note_markers(ax, annotations)
    _annotate_track_start_end(ax, df)
    ax.set_title(f"Telemetry Track\n{start_time.strftime('%Y-%m-%d %H:%M')} to {latest_time.strftime('%Y-%m-%d %H:%M')} UTC")
    
def plot_power_for_report(ax1, df: pd.DataFrame):
    """Plots the detailed power summary on the given axes for a PDF report."""
    # The 'gliderTimeStamp' column is expected from the power data source.
    
    # These column names are from the Amps Power Summary Report
    cols_to_adjust = ['totalBatteryPower', 'solarPowerGenerated', 'outputPortPower', 'batteryChargingPower']
    df_plot = df.copy()
    for col in cols_to_adjust:
        if col in df_plot.columns:
            # Convert from mWh to Wh
            df_plot[col] = df_plot[col].div(1000).round(2)

    x_pwr = df_plot['gliderTimeStamp']
    
    color1 = 'tab:blue'
    ax1.set_xlabel('TimeStamp (UTC)')
    ax1.set_ylabel('Total Battery Power (Wh)', color=color1)
    ax1.plot(x_pwr, df_plot['totalBatteryPower'], label='Total Battery Power', color=color1)
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.grid(True, which='both', linestyle='--', alpha=0.3)

    ax2 = ax1.twinx()
    color2 = 'tab:orange'
    ax2.set_ylabel('Power Input/Outputs (Wh)', color=color2)
    ax2.plot(x_pwr, df_plot['solarPowerGenerated'], label='Solar Power Generated', color='orange')
    ax2.plot(x_pwr, df_plot['outputPortPower'], label='Output Port Power', color='red')
    ax2.plot(x_pwr, df_plot['batteryChargingPower'], label='Battery Charging Power', color='green')
    ax2.tick_params(axis='y', labelcolor=color2)

    # Combine legends from both axes
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2, loc='upper left')
    
    ax1.set_title("Power Subsystem Summary")
    
# --- Shared text-page renderer ---------------------------------------------
# Generalizes the bounded-axes + textwrap pattern used by `plot_errors_for_report`
# so the Summary page, Sensor Tracker metadata pages, and Mission Note Appendix
# all share one layout path with consistent margins, wrapping, and pagination.

_TEXT_PAGE_LEFT_MARGIN = 0.05
_TEXT_PAGE_RIGHT_MARGIN = 0.05
_TEXT_PAGE_TOP_MARGIN = 0.90
_TEXT_PAGE_BOTTOM_MARGIN = 0.10
_TEXT_PAGE_BODY_PROPS = {
    "va": "top",
    "ha": "left",
    "fontsize": 10,
    "family": REPORT_PDF_FONT_PRIMARY,
}
_TEXT_PAGE_LINE_SPACING = 1.15
_TEXT_PAGE_WRAP_WIDTH = 100
# Lines per page for the text axes box at _TEXT_PAGE_LINE_SPACING.
_TEXT_PAGE_LINES_PER_PAGE = 58
_TEXT_PAGE_SUPTITLE_KWARGS = {"fontsize": 16, "fontfamily": REPORT_PDF_FONT_PRIMARY}


def _flatten_sections_to_lines(sections: List[Dict[str, Any]]) -> List[str]:
    """Flatten section dicts into a single pre-wrapped line list.

    Each section dict supports: heading (str), lines (list[str]), indent (int).
    A blank separator is inserted between sections; the heading is followed by
    a dashed underline. Body lines are wrapped to fit the page width minus the
    indent prefix using `textwrap.wrap(break_long_words=True, break_on_hyphens=False)`
    -- the same options already used by `plot_errors_for_report` so long URLs
    and comma-separated lists actually break.
    """
    rendered: List[str] = []
    for idx, section in enumerate(sections):
        if idx > 0:
            rendered.append("")
        heading = section.get("heading")
        if heading:
            rendered.append(heading)
            rendered.append("-" * min(len(heading) + 4, _TEXT_PAGE_WRAP_WIDTH))
        indent = section.get("indent", 0)
        prefix = "  " * indent
        for line in section.get("lines", []):
            if not line:
                rendered.append("")
                continue
            wrapped = textwrap.wrap(
                line,
                width=max(_TEXT_PAGE_WRAP_WIDTH - len(prefix), 20),
                break_long_words=True,
                break_on_hyphens=False,
            )
            if not wrapped:
                rendered.append("")
                continue
            rendered.append(prefix + wrapped[0])
            for cont in wrapped[1:]:
                rendered.append(prefix + "    " + cont)
    return rendered


def _justify_line_fill(line: str, width: int) -> str:
    """Pad a wrapped line to `width` characters by expanding spaces between words."""
    if not line:
        return line
    raw = line.rstrip("\n")
    if not raw.strip():
        return line
    st = raw.strip()
    if st and set(st) == {"-"}:
        return line
    m = re.match(r"^(\s*)", raw)
    leading = m.group(1) if m else ""
    content = raw[len(leading) :].rstrip()
    if not content or " " not in content:
        return line
    words = content.split()
    if len(words) < 2:
        return line
    base_one_space = " ".join(words)
    available = width - len(leading)
    if available <= 0 or len(base_one_space) >= available:
        return line
    if len(base_one_space) < max(24, int(available * 0.52)):
        return line
    extra = available - len(base_one_space)
    gaps = len(words) - 1
    if gaps <= 0 or extra < 0:
        return line
    per = extra // gaps
    rem = extra % gaps
    parts: List[str] = []
    for i, w in enumerate(words):
        parts.append(w)
        if i >= gaps:
            break
        nspaces = 1 + per + (1 if i < rem else 0)
        parts.append(" " * nspaces)
    justified = leading + "".join(parts)
    if len(justified) > width:
        return line
    return justified


def render_text_sections(
    add_footer_and_save,
    *,
    page_title: str,
    sections: List[Dict[str, Any]],
    page_size=(8.27, 11.69),
    justify_body: bool = True,
) -> None:
    """Render an ordered list of text sections across one or more PDF pages.

    Each page uses the same bounded text-axes pattern as `plot_errors_for_report`
    (figure-coord margins, report sans-serif text, manual wrapping). When the flattened
    line list is longer than what fits on one page, additional pages are emitted
    with a "(continued)" suptitle. Saving and footer/page-number stamping is
    delegated to the supplied `add_footer_and_save` callback (the existing
    closure inside `generate_weekly_report`).

    When ``justify_body`` is True, wrapped body lines are padded to ``_TEXT_PAGE_WRAP_WIDTH``
    by expanding inter-word spaces (TOC and similar pages should pass False).
    """
    lines = _flatten_sections_to_lines(sections)
    if not lines:
        return
    if justify_body:
        lines = [_justify_line_fill(line, _TEXT_PAGE_WRAP_WIDTH) for line in lines]

    pages = [
        lines[i:i + _TEXT_PAGE_LINES_PER_PAGE]
        for i in range(0, len(lines), _TEXT_PAGE_LINES_PER_PAGE)
    ]

    for page_idx, page_lines in enumerate(pages):
        fig = plt.figure(figsize=page_size)
        suptitle = page_title if page_idx == 0 else f"{page_title} (continued)"
        fig.suptitle(suptitle, **_TEXT_PAGE_SUPTITLE_KWARGS)

        text_ax = fig.add_axes([
            _TEXT_PAGE_LEFT_MARGIN,
            _TEXT_PAGE_BOTTOM_MARGIN,
            1 - _TEXT_PAGE_LEFT_MARGIN - _TEXT_PAGE_RIGHT_MARGIN,
            _TEXT_PAGE_TOP_MARGIN - _TEXT_PAGE_BOTTOM_MARGIN,
        ])
        text_ax.set_axis_off()
        text_ax.text(0, 1.0, "\n".join(page_lines), linespacing=_TEXT_PAGE_LINE_SPACING, **_TEXT_PAGE_BODY_PROPS)
        add_footer_and_save(fig)


def estimate_text_sections_page_count(sections: List[Dict[str, Any]]) -> int:
    """Estimate number of pages render_text_sections will produce."""
    lines = _flatten_sections_to_lines(sections)
    if not lines:
        return 0
    return max(1, math.ceil(len(lines) / _TEXT_PAGE_LINES_PER_PAGE))


def plot_table_of_contents_page(
    add_footer_and_save,
    toc_entries: List[Dict[str, Any]],
) -> None:
    """Render a simple table of contents page with page numbers."""
    sections: List[Dict[str, Any]] = [{
        "heading": None,
        "lines": ["This table of contents reflects final rendered page numbers."],
    }]
    lines: List[str] = []
    for entry in toc_entries:
        title = str(entry.get("title", "Section")).strip()
        page_number = entry.get("page_number")
        page_text = f"{page_number}" if page_number is not None else "N/A"
        lines.append(f"{title.ljust(78, '.')} {page_text}")
    sections.append({"heading": "Contents", "lines": lines or ["(No sections available)"]})
    render_text_sections(
        add_footer_and_save,
        page_title="Table of Contents",
        sections=sections,
        justify_body=False,
    )


def plot_summary_page(
    add_footer_and_save,
    telemetry_mission,
    telemetry_report,
    power_report,
    ctd_report,
    weather_report,
    wave_report,
    error_report,
    mission_goals: Optional[List[models.MissionGoal]] = None,
):
    """Creates a two-column mission summary page with key statistics."""

    def format_block(title, stats, unit):
        lines = [f"{title}:"]
        if "avg" in stats: lines.append(f"  • Avg: {stats['avg']:.2f} {unit}")
        if "min" in stats: lines.append(f"  • Min: {stats['min']:.2f} {unit}")
        if "max" in stats: lines.append(f"  • Max: {stats['max']:.2f} {unit}")
        return lines

    sections: List[Dict[str, Any]] = []

    telemetry_lines = [
        "Report Period:",
        f"  • Distance Traveled: {telemetry_report.get('total_distance_km', 0.0):.2f} km",
        f"  • Average Speed: {telemetry_report.get('avg_speed_knots', 0.0):.2f} knots",
        "",
        "Total Mission:",
        f"  • Distance Traveled: {telemetry_mission.get('total_distance_km', 0.0):.2f} km",
    ]
    sections.append({"heading": "Telemetry Summary", "lines": telemetry_lines})

    power_lines = [
        f"  • Total Input: {power_report.get('avg_total_input_W', 0.0):.2f} W",
        f"  • Total Output: {power_report.get('avg_total_output_W', 0.0):.2f} W",
        "  • Solar Panel Input:",
    ]
    for name, avg_w in power_report.get("avg_solar_panel_W", {}).items():
        power_lines.append(f"      • {name}: {avg_w:.2f} W")
    sections.append({"heading": "Power Summary (Averages)", "lines": power_lines})

    if mission_goals:
        goal_lines = []
        for goal in mission_goals:
            status = "✓" if goal.is_completed else "☐"
            goal_lines.append(f" {status} {goal.description}")
        sections.append({"heading": "Mission Goals", "lines": goal_lines})

    ctd_lines: List[str] = []
    if ctd_report.get("WaterTemperature"): ctd_lines.extend(format_block("Water Temp", ctd_report["WaterTemperature"], "°C"))
    if ctd_report.get("Salinity"): ctd_lines.extend(format_block("Salinity", ctd_report["Salinity"], "PSU"))
    if ctd_report.get("Conductivity"): ctd_lines.extend(format_block("Conductivity", ctd_report["Conductivity"], "S/m"))
    if ctd_lines:
        sections.append({"heading": "Oceanographic (CTD)", "lines": ctd_lines})

    weather_lines: List[str] = []
    if weather_report.get("AirTemperature"): weather_lines.extend(format_block("Air Temp", weather_report["AirTemperature"], "°C"))
    if weather_report.get("WindSpeed"): weather_lines.extend(format_block("Wind Speed", weather_report["WindSpeed"], "kt"))
    if weather_report.get("WindGust"): weather_lines.append(f"  • Max Gust: {weather_report['WindGust']['max']:.2f} kt")
    if weather_report.get("BarometricPressure"): weather_lines.extend(format_block("Pressure", weather_report["BarometricPressure"], "mbar"))
    if weather_lines:
        sections.append({"heading": "Meteorological (Weather)", "lines": weather_lines})

    wave_lines: List[str] = []
    if wave_report.get("SignificantWaveHeight"): wave_lines.extend(format_block("Sig. Wave Height", wave_report["SignificantWaveHeight"], "m"))
    if wave_report.get("WavePeriod"): wave_lines.extend(format_block("Peak Period", wave_report["WavePeriod"], "s"))
    if wave_lines:
        sections.append({"heading": "Sea State (Waves)", "lines": wave_lines})

    error_lines = [f"  • Total Errors: {error_report.get('total_errors', 0)}"]
    severity_items = error_report.get("by_severity", {}).items()
    if severity_items:
        for sev, count in severity_items:
            error_lines.append(f"  • {sev}: {count}")
    else:
        error_lines.append("  • No errors with severity.")
    sections.append({"heading": "Vehicle Errors", "lines": error_lines})

    left_sections = sections[0::2]
    right_sections = sections[1::2]
    left_lines = _flatten_sections_to_lines(left_sections)
    right_lines = _flatten_sections_to_lines(right_sections)

    fig = plt.figure(figsize=(8.27, 11.69))
    fig.suptitle("Mission Summary Statistics", **_TEXT_PAGE_SUPTITLE_KWARGS)
    left_ax = fig.add_axes([0.05, 0.10, 0.43, 0.80])
    right_ax = fig.add_axes([0.52, 0.10, 0.43, 0.80])
    left_ax.set_axis_off()
    right_ax.set_axis_off()
    left_ax.text(0, 1.0, "\n".join(left_lines), linespacing=_TEXT_PAGE_LINE_SPACING, **_TEXT_PAGE_BODY_PROPS)
    right_ax.text(0, 1.0, "\n".join(right_lines), linespacing=_TEXT_PAGE_LINE_SPACING, **_TEXT_PAGE_BODY_PROPS)
    add_footer_and_save(fig)

def plot_ctd_for_report(fig, df: pd.DataFrame):
    """
    Plots detailed CTD data on the given Figure object for a PDF report.
    Assumes a pre-filtered and pre-processed DataFrame.
    """
    if df.empty:
        fig.text(
            0.5,
            0.5,
            "No CTD data in the selected range.",
            ha="center",
            va="center",
            family=REPORT_PDF_FONT_PRIMARY,
        )
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("CTD Summary", **_TEXT_PAGE_SUPTITLE_KWARGS)

    # Plot Temperature
    if "WaterTemperature" in df.columns:
        axs[0].plot(df["Timestamp"], df["WaterTemperature"], "r-", label="Water Temperature (°C)")
        axs[0].set_ylabel("Temp (°C)")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(loc="upper left")

    # Plot Conductivity (swapped with Salinity for logical order)
    if "Conductivity" in df.columns:
        axs[1].plot(df["Timestamp"], df["Conductivity"], "orange", label="Conductivity (S/m)")
        axs[1].set_ylabel("Conductivity (S/m)")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc="upper left")

    # Plot Salinity
    if "Salinity" in df.columns:
        axs[2].plot(df["Timestamp"], df["Salinity"], "b-", label="Salinity (PSU)")
        axs[2].set_ylabel("Salinity (PSU)")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left")

    axs[2].set_xlabel("Time (UTC)")


def plot_c3_for_report(fig, df: pd.DataFrame):
    """Plot C3 channels with fluorometer temperature overlays."""
    if df.empty:
        fig.text(
            0.5,
            0.5,
            "No C3 data in the selected range.",
            ha="center",
            va="center",
            family=REPORT_PDF_FONT_PRIMARY,
        )
        return
    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("C3 Fluorometer Summary", **_TEXT_PAGE_SUPTITLE_KWARGS)
    channel_specs = [
        ("C1_Avg", "Channel 1", "tab:blue"),
        ("C2_Avg", "Channel 2", "tab:green"),
        ("C3_Avg", "Channel 3", "tab:purple"),
    ]
    for idx, (column_name, channel_label, color) in enumerate(channel_specs):
        if column_name in df.columns:
            axs[idx].plot(df["Timestamp"], df[column_name], color=color, label=f"{channel_label} (RFU)")
            axs[idx].set_ylabel("RFU")
            axs[idx].grid(True, alpha=0.3)
            axs[idx].legend(loc="upper left")
        if "Temperature_Fluor" in df.columns:
            temperature_axis = axs[idx].twinx()
            temperature_axis.plot(
                df["Timestamp"], df["Temperature_Fluor"], color="tab:red", alpha=0.6, linestyle="--", label="Temp (C)"
            )
            temperature_axis.set_ylabel("Temp (C)", color="tab:red")
            temperature_axis.tick_params(axis="y", labelcolor="tab:red")
    axs[2].set_xlabel("Time (UTC)")

def plot_errors_for_report(add_footer_and_save, df: pd.DataFrame) -> None:
    """
    Creates one or more PDF pages with a bulleted list of recent vehicle errors.

    Delegates layout/margins/wrapping to `render_text_sections`, matching the
    same bounded-axes + report font + textwrap pattern used elsewhere in reports.
    """
    if df.empty:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(
            0.5, 0.5,
            "No vehicle errors reported in the selected range.",
            ha="center",
            va="center",
            family=REPORT_PDF_FONT_PRIMARY,
        )
        add_footer_and_save(fig)
        return

    df_display = df.copy().tail(15)

    vehicle_column = "VehicleName" if "VehicleName" in df_display.columns else "vehicleName"
    message_column = "ErrorMessage" if "ErrorMessage" in df_display.columns else "error_Message"
    timestamp_column = "Timestamp" if "Timestamp" in df_display.columns else "timeStamp"

    body_lines: List[str] = []
    for _, row in df_display.iterrows():
        vehicle_value = row.get(vehicle_column)
        message_value = row.get(message_column)
        timestamp_value = row.get(timestamp_column)

        vehicle = str(vehicle_value).strip() if pd.notna(vehicle_value) else "N/A"
        message = str(message_value).strip() if pd.notna(message_value) else "No message."
        if not message:
            message = "No message."
        message = message.replace('@', '@\u200B')

        timestamp_text = ""
        if pd.notna(timestamp_value):
            try:
                timestamp_text = pd.to_datetime(timestamp_value, utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                timestamp_text = str(timestamp_value)

        entry_text = f"• {timestamp_text} | {vehicle}: {message}" if timestamp_text else f"• {vehicle}: {message}"
        wrapped_lines = textwrap.wrap(
            entry_text,
            width=_TEXT_PAGE_WRAP_WIDTH,
            break_long_words=True,
            break_on_hyphens=False,
        )
        body_lines.extend(wrapped_lines)
        body_lines.append("")

    if body_lines and body_lines[-1] == "":
        body_lines.pop()

    render_text_sections(
        add_footer_and_save,
        page_title="Vehicle Error Report",
        sections=[{"heading": None, "lines": body_lines}],
    )

def plot_weather_for_report(fig, df: pd.DataFrame):
    """
    Plots detailed weather data on the given Figure object for a PDF report.
    Assumes a pre-filtered and pre-processed DataFrame.
    """
    if df.empty:
        fig.text(
            0.5,
            0.5,
            "No weather data in the selected range.",
            ha="center",
            va="center",
            family=REPORT_PDF_FONT_PRIMARY,
        )
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("Weather Summary", **_TEXT_PAGE_SUPTITLE_KWARGS)

    # Plot Air Temperature
    if "AirTemperature" in df.columns:
        axs[0].plot(df["Timestamp"], df["AirTemperature"], "r-", label="Air Temp (°C)")
        axs[0].set_ylabel("Temp (°C)")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(loc="upper left")

    # Plot Wind Speed and Gust
    if "WindSpeed" in df.columns:
        axs[1].plot(df["Timestamp"], df["WindSpeed"], "g-", label="Wind Speed (kt)")
        if "WindGust" in df.columns:
            axs[1].plot(df["Timestamp"], df["WindGust"], "b--", label="Wind Gust (kt)", alpha=0.7)
        axs[1].set_ylabel("Wind (kt)")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc="upper left")

    # Plot Barometric Pressure
    if "BarometricPressure" in df.columns:
        axs[2].plot(df["Timestamp"], df["BarometricPressure"], "m-", label="Pressure (mbar)")
        axs[2].set_ylabel("Pressure (mbar)")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left")

    axs[2].set_xlabel("Time (UTC)")

def plot_wave_for_report(fig, df: pd.DataFrame):
    """
    Plots detailed wave data on the given Figure object for a PDF report.
    Assumes a pre-filtered and pre-processed DataFrame.
    """
    if df.empty:
        fig.text(
            0.5,
            0.5,
            "No wave data in the selected range.",
            ha="center",
            va="center",
            family=REPORT_PDF_FONT_PRIMARY,
        )
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("Wave Summary", **_TEXT_PAGE_SUPTITLE_KWARGS)

    # Plot Significant Wave Height
    if "SignificantWaveHeight" in df.columns:
        axs[0].plot(df["Timestamp"], df["SignificantWaveHeight"], "c-", label="Sig. Wave Height (m)")
        axs[0].set_ylabel("Height (m)")
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(loc="upper left")

    # Plot Wave Period
    if "WavePeriod" in df.columns:
        axs[1].plot(df["Timestamp"], df["WavePeriod"], "m-", label="Peak Period (s)")
        axs[1].set_ylabel("Period (s)")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc="upper left")

    # Plot Mean Wave Direction (display-only unwrap to avoid 0/360 jumps)
    if "MeanWaveDirection" in df.columns:
        axs[2].plot(
            df["Timestamp"],
            unwrap_degree_series(df["MeanWaveDirection"]),
            "y-",
            label="Mean Direction (°)",
        )
        axs[2].set_ylabel("Direction (°)")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left")

    axs[2].set_xlabel("Time (UTC)")
