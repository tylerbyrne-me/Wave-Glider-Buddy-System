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
from matplotlib.patches import FancyArrowPatch, Rectangle
import numpy as np  # type: ignore
import logging

from . import models, utils
from .data.processors import (preprocess_ctd_df, preprocess_power_df,
                         preprocess_wave_df, preprocess_weather_df)
from .data.processors import preprocess_telemetry_df, telemetry_speed_over_ground_series
from .geo.bathymetry import fetch_etopo_bathymetry, nice_contour_levels
from .infra.feature_toggles import is_report_bathymetry_contours_enabled

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
# Telemetry-track maps for weekly and end-of-mission PDFs (plot_telemetry_page_with_notes).
#
# Layout pipeline:
#   1. Track bbox + percentage padding (_track_bounding_extent)
#   2. Southern overlay strip for compass / scale / inset (_compute_overlay_strip_extent)
#   3. Aspect padding to fill the page (_pad_extent_to_aspect)
#   4. Cartopy base map + optional ETOPO bathymetry contours (fetch_etopo_bathymetry)
#   5. SOG-colored track, then overlay strip elements after tight_layout

REPORT_MAP_OCEAN_COLOR = "#B8D4E8"
REPORT_MAP_LAND_COLOR = "#C4A882"
_NM_PER_KM = 1.0 / 1.852
_KM_PER_DEG_LAT = 111.32
_SCALE_BAR_CANDIDATES_KM = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000)

# Track extent and overlay layout — corner-anchored, fraction-based (no fixed degrees).
TRACK_EXTENT_PADDING_FRACTION = 0.12
TRACK_EXTENT_MIN_SPAN_DEG = 0.02
OVERLAY_STRIP_FRACTION = 0.20
OVERLAY_STRIP_MIN_FRACTION = 0.12
INSET_SIZE_FRACTION = (0.22, 0.18)  # inset width; height comes from strip_fraction
STRIP_COMPASS_AXES_X = 0.12  # left third of strip (transAxes)
STRIP_SCALE_AXES_X = 0.50  # center of strip (transAxes)
STRIP_ELEMENT_Y_FRACTION = 0.45  # vertical center within strip band
INSET_MARGIN_FRACTION = 0.025
MAP_LAYOUT_WIDTH_RESERVE_IN = 1.3
MAP_LAYOUT_HEIGHT_RESERVE_IN = 1.2
MAP_TIGHT_LAYOUT_PAD = 1.0


def _track_bounding_extent(
    longitudes,
    latitudes,
    *,
    padding_fraction: float = TRACK_EXTENT_PADDING_FRACTION,
    min_span_deg: float = TRACK_EXTENT_MIN_SPAN_DEG,
) -> List[float]:
    """Bounding box around track coordinates with symmetric percentage padding."""
    west = float(np.min(longitudes))
    east = float(np.max(longitudes))
    south = float(np.min(latitudes))
    north = float(np.max(latitudes))

    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    lon_span = max(east - west, min_span_deg)
    lat_span = max(north - south, min_span_deg)
    pad_lon = lon_span * padding_fraction
    pad_lat = lat_span * padding_fraction
    half_lon = lon_span / 2.0
    half_lat = lat_span / 2.0
    return [
        center_lon - half_lon - pad_lon,
        center_lon + half_lon + pad_lon,
        center_lat - half_lat - pad_lat,
        center_lat + half_lat + pad_lat,
    ]


def _compute_overlay_strip_extent(
    data_extent: List[float],
    *,
    strip_fraction: float = OVERLAY_STRIP_FRACTION,
) -> tuple[List[float], float]:
    """Add a southern strip reserved for overlays and return its degree height."""
    west, east, south, north = data_extent
    lat_span = max(north - south, TRACK_EXTENT_MIN_SPAN_DEG)
    strip_deg = lat_span * strip_fraction
    return [west, east, south - strip_deg, north], strip_deg


def _resolve_overlay_strip_fraction(
    strip_deg: float,
    extent: List[float],
    *,
    min_fraction: float = OVERLAY_STRIP_MIN_FRACTION,
) -> float:
    """Resolve strip fraction in the final extent, with minimum clamp."""
    total_lat = max(extent[3] - extent[2], 1e-6)
    return max(strip_deg / total_lat, min_fraction)


def _figure_rect_from_axes_corner(
    axes_pos,
    corner: str,
    width_fraction: float,
    height_fraction: float,
    margin_fraction: float,
) -> List[float]:
    """Figure-fraction [x, y, w, h] for an overlay inset anchored to a map corner."""
    width = axes_pos.width * width_fraction
    height = axes_pos.height * height_fraction
    margin_x = axes_pos.width * margin_fraction
    margin_y = axes_pos.height * margin_fraction
    if corner == "sw":
        x = axes_pos.x0 + margin_x
        y = axes_pos.y0 + margin_y
    elif corner == "se":
        x = axes_pos.x0 + axes_pos.width - width - margin_x
        y = axes_pos.y0 + margin_y
    elif corner == "nw":
        x = axes_pos.x0 + margin_x
        y = axes_pos.y0 + axes_pos.height - height - margin_y
    elif corner == "ne":
        x = axes_pos.x0 + axes_pos.width - width - margin_x
        y = axes_pos.y0 + axes_pos.height - height - margin_y
    else:
        raise ValueError(f"Unknown corner {corner!r}")
    return [x, y, width, height]


def _extent_center_and_spans_km(extent: List[float]) -> tuple[float, float, float, float]:
    """Return center lat/lon and lat/lon span in km for a [west, east, south, north] extent."""
    west, east, south, north = extent
    mid_lat = (south + north) / 2.0
    cos_lat = max(math.cos(math.radians(mid_lat)), 0.2)
    lat_km = max((north - south) * _KM_PER_DEG_LAT, 1e-6)
    lon_km = max((east - west) * _KM_PER_DEG_LAT * cos_lat, 1e-6)
    return mid_lat, (west + east) / 2.0, lat_km, lon_km


def _nice_scale_bar_length_km(view_span_km: float) -> float:
    """Pick a readable scale-bar length (~22% of the shorter map dimension)."""
    target = max(view_span_km * 0.22, 0.5)
    chosen = float(_SCALE_BAR_CANDIDATES_KM[0])
    for candidate in _SCALE_BAR_CANDIDATES_KM:
        if candidate <= target:
            chosen = float(candidate)
    return chosen


def _km_to_lon_degrees(km: float, lat: float) -> float:
    cos_lat = max(math.cos(math.radians(lat)), 0.2)
    return km / (_KM_PER_DEG_LAT * cos_lat)


def _regional_inset_extent(
    main_extent: List[float],
    *,
    expansion: float = 4.0,
    min_span_deg: float = 3.0,
    max_span_deg: float = 25.0,
) -> List[float]:
    """Expand the main map bbox for a regional locator inset (land/ocean context only)."""
    west, east, south, north = main_extent
    lon_span = max(east - west, 1e-6)
    lat_span = max(north - south, 1e-6)
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    span = max(lon_span, lat_span) * expansion
    span = max(min_span_deg, min(max_span_deg, span))
    half = span / 2.0
    return [center_lon - half, center_lon + half, center_lat - half, center_lat + half]


def _setup_report_map(ax, extent):
    """Configures a Cartopy map with basic features for PDF reports."""
    ax.set_extent(extent)
    ax.add_feature(cfeature.OCEAN, facecolor=REPORT_MAP_OCEAN_COLOR, zorder=0)
    ax.add_feature(cfeature.LAND, facecolor=REPORT_MAP_LAND_COLOR, zorder=1)
    ax.coastlines(resolution="10m", zorder=2)
    ax.add_feature(cfeature.BORDERS, linestyle=":", zorder=2)
    g1 = ax.gridlines(draw_labels=True, linewidth=0.25, color="gray", alpha=0.5, linestyle="--")
    g1.top_labels = False
    g1.right_labels = False
    g1.xlabel_style = {"size": 10}
    g1.ylabel_style = {"size": 10}
    g1.xformatter = LONGITUDE_FORMATTER
    g1.yformatter = LATITUDE_FORMATTER


def _setup_report_inset_map(ax, extent: List[float]) -> None:
    """Regional locator inset: land/ocean only, no grid labels."""
    ax.set_extent(extent)
    ax.add_feature(cfeature.OCEAN, facecolor=REPORT_MAP_OCEAN_COLOR, zorder=0)
    ax.add_feature(cfeature.LAND, facecolor=REPORT_MAP_LAND_COLOR, zorder=1)
    ax.coastlines(resolution="50m", zorder=2)


def _add_report_bathymetry_contours(ax, extent: List[float]) -> None:
    """Draw labeled ETOPO ocean-depth contours under the telemetry track.

    Fetches a bbox subset from NOAA ERDDAP griddap (ETOPO_2022_v1_15s). On fetch
    or render failure the map is left unchanged.
    """
    if not is_report_bathymetry_contours_enabled():
        return

    grid = fetch_etopo_bathymetry(extent)
    if grid is None or grid.z.size == 0:
        return

    z_ocean = np.ma.masked_where(grid.z >= 0, grid.z)
    if z_ocean.count() == 0:
        return

    valid_z = z_ocean.compressed()
    levels = nice_contour_levels(float(np.min(valid_z)), float(np.max(valid_z)))
    if not levels:
        return

    try:
        contour_set = ax.contour(
            grid.longitude,
            grid.latitude,
            z_ocean,
            levels=levels,
            colors="#1E3A5F",
            linewidths=0.5,
            alpha=0.75,
            transform=ccrs.PlateCarree(),
            zorder=1.5,
        )
        ax.clabel(
            contour_set,
            inline=True,
            fontsize=6,
            fmt=lambda value: f"{abs(int(value))} m",
        )
    except Exception as exc:
        logger.warning("Skipping bathymetry contours for extent %s: %s", extent, exc)


def _add_report_map_scale_and_compass(
    ax,
    extent: List[float],
    strip_fraction: float,
) -> None:
    """Overlay strip: compass (left), scale bar + labels (center). Inset is drawn separately."""
    _mid_lat, _mid_lon, lat_km, lon_km = _extent_center_and_spans_km(extent)
    view_span_km = min(lat_km, lon_km)
    bar_km = _nice_scale_bar_length_km(view_span_km)
    bar_nm = bar_km * _NM_PER_KM

    west, east, south, north = extent
    strip_fraction = max(strip_fraction, OVERLAY_STRIP_MIN_FRACTION)
    strip_deg = (north - south) * strip_fraction
    bar_lat = south + strip_deg * STRIP_ELEMENT_Y_FRACTION
    bar_lon_half = _km_to_lon_degrees(bar_km, bar_lat) / 2.0
    center_lon = (west + east) / 2.0
    bar_lon_start = center_lon - bar_lon_half
    bar_lon_end = center_lon + bar_lon_half
    tick_h = strip_deg * 0.10

    ax.plot(
        [bar_lon_start, bar_lon_end],
        [bar_lat, bar_lat],
        color="black",
        linewidth=2.0,
        solid_capstyle="butt",
        transform=ccrs.PlateCarree(),
        zorder=8,
    )
    for lon in (bar_lon_start, bar_lon_end):
        ax.plot(
            [lon, lon],
            [bar_lat - tick_h, bar_lat + tick_h],
            color="black",
            linewidth=1.5,
            transform=ccrs.PlateCarree(),
            zorder=8,
        )

    strip_y = strip_fraction * STRIP_ELEMENT_Y_FRACTION
    label_y = strip_fraction * 0.72
    ax.text(
        STRIP_SCALE_AXES_X,
        label_y,
        f"{bar_nm:.0f} nm\n{bar_km:.0f} km",
        transform=ax.transAxes,
        fontsize=8,
        fontweight="bold",
        va="bottom",
        ha="center",
        linespacing=1.15,
        color="black",
        bbox=dict(boxstyle="round,pad=0.30", facecolor="white", edgecolor="#D1D5DB", alpha=0.92),
        zorder=9,
    )

    compass_x = STRIP_COMPASS_AXES_X
    arrow_height = strip_fraction * 0.38
    arrow = FancyArrowPatch(
        (compass_x, strip_y - arrow_height * 0.35),
        (compass_x, strip_y + arrow_height * 0.55),
        transform=ax.transAxes,
        arrowstyle="-|>",
        mutation_scale=11,
        linewidth=1.4,
        color="black",
        zorder=9,
    )
    ax.add_patch(arrow)
    ax.text(
        compass_x,
        label_y,
        "N",
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        ha="center",
        va="bottom",
        color="black",
        bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="#D1D5DB", alpha=0.92),
        zorder=9,
    )


def _add_report_regional_inset(
    fig,
    map_ax,
    main_extent: List[float],
    regional_extent: List[float],
    strip_fraction: float,
) -> None:
    """Bottom-right regional inset anchored to the overlay strip."""
    inset_height_fraction = strip_fraction * 0.85
    inset_rect = _figure_rect_from_axes_corner(
        map_ax.get_position(),
        "se",
        INSET_SIZE_FRACTION[0],
        inset_height_fraction,
        INSET_MARGIN_FRACTION,
    )

    inset_ax = fig.add_axes(inset_rect, projection=ccrs.PlateCarree())
    inset_ax.set_facecolor("white")
    inset_ax.patch.set_alpha(0.97)
    _setup_report_inset_map(inset_ax, regional_extent)

    west, east, south, north = main_extent
    inset_ax.add_patch(
        Rectangle(
            (west, south),
            east - west,
            north - south,
            linewidth=1.5,
            edgecolor="#B91C1C",
            facecolor="none",
            transform=ccrs.PlateCarree(),
            zorder=5,
        )
    )
    for spine in inset_ax.spines.values():
        spine.set_edgecolor("#374151")
        spine.set_linewidth(1.2)
    inset_ax.set_zorder(map_ax.get_zorder() + 1)


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

    The map fills the entire page (with the standard title + colorbar).
    Extent is derived from the track bounding box plus percentage padding,
    then aspect-adjusted so E-W or N-S dominant tracks fill the page area
    instead of being letterboxed by Cartopy's equal-aspect projection.

    A dynamic southern overlay strip reserves room for context overlays:
    compass (left), scale bar (center), regional inset (right).

    ETOPO 2022 bathymetry depth contours (when enabled) are streamed for the
    map bbox via ERDDAP griddap and drawn under the track.

    Mission notes are NOT rendered on this page — the PDF report pipeline
    renders a separate mission-notes section. The map only shows lettered markers.
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

    extent = _track_bounding_extent(
        df_clean["longitude"],
        df_clean["latitude"],
    )

    map_ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())

    # Estimate the page-content cell so we can pad the extent and avoid the
    # equal-aspect letterboxing that otherwise hides axis labels off-page.
    # Reserve modest space for title and colorbar while maximizing map pixel area.
    fig_width_in, fig_height_in = fig.get_size_inches()
    target_aspect = max(fig_width_in - MAP_LAYOUT_WIDTH_RESERVE_IN, 1e-3) / max(
        fig_height_in - MAP_LAYOUT_HEIGHT_RESERVE_IN,
        1e-3,
    )
    strip_extent, strip_deg = _compute_overlay_strip_extent(extent)
    padded_extent = _pad_extent_to_aspect(strip_extent, target_aspect)
    strip_fraction = _resolve_overlay_strip_fraction(strip_deg, padded_extent)
    _setup_report_map(map_ax, padded_extent)
    _add_report_bathymetry_contours(map_ax, padded_extent)

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
    cbar = fig.colorbar(scatter, ax=map_ax, orientation='vertical', shrink=0.92, pad=0.05)
    cbar.set_label('Speed Over Ground (knots)')

    _annotate_track_start_end(map_ax, df_clean)
    _annotate_note_markers(map_ax, annotations)

    regional_extent = _regional_inset_extent(padded_extent)
    _add_report_map_scale_and_compass(map_ax, padded_extent, strip_fraction)

    start_time = df_clean['lastLocationFix'].min()
    latest_time = df_clean['lastLocationFix'].max()
    map_ax.set_title(
        f"Telemetry Track\n"
        f"{start_time.strftime('%Y-%m-%d %H:%M')} to {latest_time.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    fig.tight_layout(pad=MAP_TIGHT_LAYOUT_PAD)
    _add_report_regional_inset(fig, map_ax, padded_extent, regional_extent, strip_fraction)


def _prepare_power_report_frame(
    power_df: pd.DataFrame,
    *,
    resample_minutes: int = 30,
) -> pd.DataFrame:
    """Normalize raw AMPS power CSV rows and resample for report charts."""
    if power_df.empty or "gliderTimeStamp" not in power_df.columns:
        return pd.DataFrame()

    frame = power_df.copy()
    frame["Timestamp"] = utils.parse_timestamp_column(
        frame["gliderTimeStamp"], errors="coerce", utc=True
    )
    frame = frame.dropna(subset=["Timestamp"]).sort_values("Timestamp")
    if frame.empty:
        return frame

    column_map = {
        "totalBatteryPower": "BatteryWattHours",
        "solarPowerGenerated": "SolarInputWatts",
        "outputPortPower": "PowerDrawWatts",
        "batteryChargingPower": "battery_charging_power_w",
    }
    for raw_col, target_col in column_map.items():
        if raw_col in frame.columns:
            frame[target_col] = pd.to_numeric(frame[raw_col], errors="coerce") / 1000.0

    if resample_minutes <= 0:
        return frame

    numeric_cols = [
        col
        for col in ("BatteryWattHours", "SolarInputWatts", "PowerDrawWatts", "battery_charging_power_w")
        if col in frame.columns
    ]
    if not numeric_cols:
        return frame

    resampled = (
        frame.set_index("Timestamp")[numeric_cols]
        .resample(f"{resample_minutes}min")
        .mean()
        .dropna(how="all")
    )
    if "SolarInputWatts" in resampled.columns and "PowerDrawWatts" in resampled.columns:
        resampled["NetPowerWatts"] = resampled["SolarInputWatts"] - resampled["PowerDrawWatts"]
    return resampled.reset_index()


def _prepare_solar_report_frame(
    solar_df: pd.DataFrame,
    *,
    resample_minutes: int = 30,
) -> pd.DataFrame:
    """Normalize raw AMPS solar CSV rows and resample for report charts."""
    if solar_df.empty or "gliderTimeStamp" not in solar_df.columns:
        return pd.DataFrame()

    frame = solar_df.copy()
    frame["Timestamp"] = utils.parse_timestamp_column(
        frame["gliderTimeStamp"], errors="coerce", utc=True
    )
    frame = frame.dropna(subset=["Timestamp"]).sort_values("Timestamp")
    if frame.empty:
        return frame

    panel_map = {
        "panelPower1": "Panel1Power",
        "panelPower3": "Panel2Power",
        "panelPower4": "Panel4Power",
    }
    for raw_col, target_col in panel_map.items():
        if raw_col in frame.columns:
            frame[target_col] = pd.to_numeric(frame[raw_col], errors="coerce") / 1000.0

    panel_cols = [col for col in panel_map.values() if col in frame.columns]
    if not panel_cols:
        return pd.DataFrame()

    if resample_minutes <= 0:
        return frame[["Timestamp", *panel_cols]]

    resampled = (
        frame.set_index("Timestamp")[panel_cols]
        .resample(f"{resample_minutes}min")
        .mean()
        .dropna(how="all")
    )
    return resampled.reset_index()


def plot_power_for_report(
    fig,
    power_df: pd.DataFrame,
    solar_df: Optional[pd.DataFrame] = None,
    *,
    battery_max_wh: float = 2940.0,
    resample_minutes: int = 30,
) -> None:
    """Plot a three-panel power subsystem summary for weekly PDF reports."""
    power_frame = _prepare_power_report_frame(power_df, resample_minutes=resample_minutes)
    solar_frame = _prepare_solar_report_frame(
        solar_df if solar_df is not None else pd.DataFrame(),
        resample_minutes=resample_minutes,
    )

    if power_frame.empty:
        ax = fig.add_subplot(1, 1, 1)
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "No power data in the selected range.",
            ha="center",
            va="center",
            transform=ax.transAxes,
            family=REPORT_PDF_FONT_PRIMARY,
        )
        return

    ax_battery, ax_net, ax_solar = fig.subplots(3, 1, sharex=True)
    fig.suptitle("Power Subsystem Summary", **REPORT_FIG_SUPTITLE_KWARGS)

    timestamps = power_frame["Timestamp"]
    battery_wh = power_frame["BatteryWattHours"]
    ax_battery.plot(timestamps, battery_wh, label="Battery level", color="tab:blue", linewidth=1.4)
    ax_battery.set_ylabel("Battery (Wh)")
    ax_battery.grid(True, which="both", linestyle="--", alpha=0.3)

    if battery_max_wh > 0:
        ax_battery.set_ylim(0, battery_max_wh)
        ax_pct = ax_battery.twinx()
        ax_pct.set_ylabel("Battery (%)")
        ax_pct.set_ylim(0, 100)

    ax_battery.legend(loc="upper left", fontsize=8)

    if "NetPowerWatts" in power_frame.columns:
        net_power = power_frame["NetPowerWatts"]
        ax_net.plot(timestamps, net_power, label="Net power", color="#047857", linewidth=1.0, alpha=0.8)
        ax_net.fill_between(
            timestamps,
            net_power,
            0,
            where=net_power >= 0,
            color="#10B981",
            alpha=0.25,
            interpolate=True,
        )
        ax_net.fill_between(
            timestamps,
            net_power,
            0,
            where=net_power < 0,
            color="#EF4444",
            alpha=0.25,
            interpolate=True,
        )
        rolling_mean = net_power.rolling(window=12, min_periods=1).mean()
        ax_net.plot(
            timestamps,
            rolling_mean,
            label="6h rolling mean",
            color="#111827",
            linewidth=1.4,
            linestyle="--",
        )
    ax_net.axhline(0, color="#9CA3AF", linewidth=0.8)
    ax_net.set_ylabel("Net power (W)")
    ax_net.grid(True, which="both", linestyle="--", alpha=0.3)
    ax_net.legend(loc="upper left", fontsize=8)

    panel_specs = [
        ("Panel1Power", "Panel 1", "tab:orange"),
        ("Panel2Power", "Panel 2", "tab:green"),
        ("Panel4Power", "Panel 3", "tab:purple"),
    ]
    plotted_panel = False
    if not solar_frame.empty:
        for column_name, label, color in panel_specs:
            if column_name in solar_frame.columns:
                ax_solar.plot(
                    solar_frame["Timestamp"],
                    solar_frame[column_name],
                    label=label,
                    color=color,
                    linewidth=1.0,
                )
                plotted_panel = True

    if "SolarInputWatts" in power_frame.columns:
        ax_solar.plot(
            timestamps,
            power_frame["SolarInputWatts"],
            label="Total solar input",
            color="#B45309",
            linewidth=1.4,
            linestyle="--",
        )
        plotted_panel = True

    if not plotted_panel:
        ax_solar.text(
            0.5,
            0.5,
            "No per-panel solar data in the selected range.",
            ha="center",
            va="center",
            transform=ax_solar.transAxes,
            family=REPORT_PDF_FONT_PRIMARY,
        )
    ax_solar.set_ylabel("Solar input (W)")
    ax_solar.set_xlabel("Timestamp (UTC)")
    ax_solar.grid(True, which="both", linestyle="--", alpha=0.3)
    ax_solar.legend(loc="upper left", fontsize=8, ncol=2)

    ax_solar.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=0, ha="center")


REPORT_FIG_SUPTITLE_KWARGS = {"fontsize": 16, "fontfamily": REPORT_PDF_FONT_PRIMARY}


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
    fig.suptitle("CTD Summary", **REPORT_FIG_SUPTITLE_KWARGS)

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


def plot_c3_for_report(
    fig,
    df: pd.DataFrame,
    channel_map: Optional[dict] = None,
):
    """Plot C3 channels with fluorometer temperature overlays.

    When channel_map is provided (from Sensor Tracker sync), legend labels use aliases
    (e.g. C1 Avg with Chl-a subscript). Otherwise defaults to C1/C2/C3 Avg.
    """
    from .fluorometer_channels import (
        channel_y_axis_label,
        format_channel_label_matplotlib,
    )

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
    fig.suptitle("C3 Fluorometer Summary", **REPORT_FIG_SUPTITLE_KWARGS)
    channel_specs = [
        ("C1_Avg", "tab:blue"),
        ("C2_Avg", "tab:green"),
        ("C3_Avg", "tab:purple"),
    ]
    for idx, (column_name, color) in enumerate(channel_specs):
        if column_name in df.columns:
            channel_label = format_channel_label_matplotlib(column_name, channel_map)
            y_label = channel_y_axis_label(column_name, channel_map)
            axs[idx].plot(df["Timestamp"], df[column_name], color=color, label=channel_label)
            axs[idx].set_ylabel(y_label)
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
    fig.suptitle("Weather Summary", **REPORT_FIG_SUPTITLE_KWARGS)

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
    fig.suptitle("Wave Summary", **REPORT_FIG_SUPTITLE_KWARGS)

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
