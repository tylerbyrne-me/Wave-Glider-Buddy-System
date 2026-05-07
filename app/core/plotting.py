from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import textwrap
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
from matplotlib.transforms import Bbox
import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER
import numpy as np # type: ignore
import logging

from . import models
from .processors import (preprocess_ctd_df, preprocess_power_df,
                         preprocess_wave_df, preprocess_weather_df)
from .processors import preprocess_telemetry_df # Explicitly import for report plot

logger = logging.getLogger(__name__)

def ensure_plots_dir():
    plots_dir = Path("waveglider_plots_temp")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir


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
                hourly["MeanWaveDirection"],
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

def _annotate_mission_notes(
    ax,
    note_annotations: List[Dict[str, Any]],
) -> None:
    if not note_annotations:
        return

    fig = ax.get_figure()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer)
    # Keep note boxes inside the map and away from title/legend-heavy zones.
    inset_axes_bbox = Bbox.from_extents(
        axes_bbox.x0 + 8,
        axes_bbox.y0 + 8,
        axes_bbox.x1 - 8,
        axes_bbox.y1 - 8,
    )
    reserved_bboxes: List[Bbox] = [
        # Top title band
        Bbox.from_extents(
            inset_axes_bbox.x0,
            inset_axes_bbox.y1 - inset_axes_bbox.height * 0.10,
            inset_axes_bbox.x1,
            inset_axes_bbox.y1,
        ),
        # Upper-left legend area
        Bbox.from_extents(
            inset_axes_bbox.x0,
            inset_axes_bbox.y1 - inset_axes_bbox.height * 0.26,
            inset_axes_bbox.x0 + inset_axes_bbox.width * 0.38,
            inset_axes_bbox.y1,
        ),
    ]
    occupied_bboxes: List[Bbox] = []
    candidate_offsets_pts = [
        (12, 10), (12, -10), (-12, 10), (-12, -10),
        (18, 0), (-18, 0), (0, 16), (0, -16),
        (24, 14), (-24, 14), (24, -14), (-24, -14),
    ]
    callout_spacing_px = 26.0

    def _place_in_callout_column(
        anchor_x_px: float,
        anchor_y_px: float,
        label_text: str,
    ) -> tuple[Any, Optional[Bbox]]:
        place_on_right = anchor_x_px < (inset_axes_bbox.x0 + inset_axes_bbox.width * 0.60)
        if place_on_right:
            x_px = inset_axes_bbox.x1 - 12.0
            ha = "right"
            step_direction = -1.0
        else:
            x_px = inset_axes_bbox.x0 + 12.0
            ha = "left"
            step_direction = 1.0

        base_y_px = min(max(anchor_y_px, inset_axes_bbox.y0 + 16.0), inset_axes_bbox.y1 - 16.0)
        slot_sequence: List[float] = [base_y_px]
        for slot_idx in range(1, 24):
            delta = callout_spacing_px * slot_idx
            slot_sequence.append(base_y_px + delta)
            slot_sequence.append(base_y_px - delta)

        for y_px in slot_sequence:
            y_px = min(max(y_px, inset_axes_bbox.y0 + 8.0), inset_axes_bbox.y1 - 8.0)
            candidate_lon, candidate_lat = ax.transData.inverted().transform((x_px, y_px))
            candidate_text = ax.text(
                candidate_lon,
                candidate_lat,
                label_text,
                fontsize=7.0,
                va="center",
                ha=ha,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="black", alpha=0.80),
                transform=ccrs.PlateCarree(),
                zorder=5,
                clip_on=True,
            )
            candidate_bbox = candidate_text.get_window_extent(renderer=renderer)
            is_inside_axes = (
                candidate_bbox.x0 >= inset_axes_bbox.x0
                and candidate_bbox.y0 >= inset_axes_bbox.y0
                and candidate_bbox.x1 <= inset_axes_bbox.x1
                and candidate_bbox.y1 <= inset_axes_bbox.y1
            )
            has_overlap = any(
                _bboxes_overlap(candidate_bbox, existing_bbox)
                for existing_bbox in occupied_bboxes + reserved_bboxes
            )
            if is_inside_axes and not has_overlap:
                return candidate_text, candidate_bbox
            candidate_text.remove()

        # Last resort: clipped near top/bottom guardrail in chosen column.
        fallback_y_px = inset_axes_bbox.y0 + 18.0 if step_direction > 0 else inset_axes_bbox.y1 - 18.0
        fallback_lon, fallback_lat = ax.transData.inverted().transform((x_px, fallback_y_px))
        fallback_text = ax.text(
            fallback_lon,
            fallback_lat,
            label_text,
            fontsize=7.0,
            va="center",
            ha=ha,
            bbox=dict(boxstyle="round,pad=0.20", fc="white", ec="black", alpha=0.78),
            transform=ccrs.PlateCarree(),
            zorder=5,
            clip_on=True,
        )
        return fallback_text, fallback_text.get_window_extent(renderer=renderer)

    def _bboxes_overlap(left: Bbox, right: Bbox, pad_px: float = 4.0) -> bool:
        return not (
            left.x1 + pad_px < right.x0
            or left.x0 - pad_px > right.x1
            or left.y1 + pad_px < right.y0
            or left.y0 - pad_px > right.y1
        )

    for note in note_annotations:
        longitude = note.get("longitude")
        latitude = note.get("latitude")
        label = str(note.get("label", "")).strip()
        if longitude is None or latitude is None or not label:
            continue

        label_wrapped = textwrap.fill(label, width=38)
        anchor_x_px, anchor_y_px = ax.transData.transform((longitude, latitude))
        chosen_text = None
        chosen_bbox = None

        for offset_x_pts, offset_y_pts in candidate_offsets_pts:
            # 72 points per inch; use figure DPI to convert points to pixels.
            offset_x_px = (offset_x_pts / 72.0) * fig.dpi
            offset_y_px = (offset_y_pts / 72.0) * fig.dpi
            candidate_x_px = anchor_x_px + offset_x_px
            candidate_y_px = anchor_y_px + offset_y_px
            candidate_lon, candidate_lat = ax.transData.inverted().transform((candidate_x_px, candidate_y_px))
            candidate_text = ax.text(
                candidate_lon,
                candidate_lat,
                label_wrapped,
                fontsize=7.2,
                va="center",
                ha="left" if offset_x_pts >= 0 else "right",
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="black", alpha=0.78),
                transform=ccrs.PlateCarree(),
                zorder=5,
            )
            candidate_bbox = candidate_text.get_window_extent(renderer=renderer)

            is_inside_axes = (
                candidate_bbox.x0 >= inset_axes_bbox.x0
                and candidate_bbox.y0 >= inset_axes_bbox.y0
                and candidate_bbox.x1 <= inset_axes_bbox.x1
                and candidate_bbox.y1 <= inset_axes_bbox.y1
            )
            has_overlap = any(
                _bboxes_overlap(candidate_bbox, existing_bbox)
                for existing_bbox in occupied_bboxes + reserved_bboxes
            )
            if is_inside_axes and not has_overlap:
                chosen_text = candidate_text
                chosen_bbox = candidate_bbox
                break
            candidate_text.remove()

        if chosen_text is None:
            # Dense-cluster fallback: route to a non-overlapping callout column.
            chosen_text, chosen_bbox = _place_in_callout_column(
                anchor_x_px=anchor_x_px,
                anchor_y_px=anchor_y_px,
                label_text=label_wrapped,
            )

        ax.plot(
            longitude,
            latitude,
            marker="o",
            color="black",
            markersize=4,
            transform=ccrs.Geodetic(),
            zorder=4,
        )
        text_anchor_data = chosen_text.get_position()
        ax.plot(
            [longitude, text_anchor_data[0]],
            [latitude, text_anchor_data[1]],
            color="black",
            linewidth=0.7,
            transform=ccrs.PlateCarree(),
            zorder=4,
        )
        if chosen_bbox is not None:
            occupied_bboxes.append(chosen_bbox)


def plot_telemetry_for_report(
    ax,
    df: pd.DataFrame,
    note_annotations: Optional[List[Dict[str, Any]]] = None,
):
    """Plots the 2D GPS track on the given map axes for a PDF report. Assumes a pre-filtered DataFrame."""
    # The 'lastLocationFix' column is expected from the telemetry data source.
    df = df.sort_values(by='lastLocationFix')

    if df.empty or 'longitude' not in df.columns or 'latitude' not in df.columns:
        ax.text(0.5, 0.5, "No telemetry data in the selected range.", horizontalalignment='center', verticalalignment='center', transform=ax.transAxes)
        return

    start_time = df['lastLocationFix'].min()
    latest_time = df['lastLocationFix'].max()

    extent = [df['longitude'].min() - 0.1, df['longitude'].max() + 0.1, df['latitude'].min() - 0.1, df['latitude'].max() + 0.1]
    _setup_report_map(ax, extent)

    # Use a more intuitive "cool-to-hot" colormap like 'plasma' for speed.
    # It's perceptually uniform and good for colorblind viewers.
    norm = mcolors.Normalize(vmin=0, vmax=4)
    cmap = cm.get_cmap('plasma')

    scatter = ax.scatter(df['longitude'], df['latitude'], c=df['speedOverGround'], cmap=cmap, norm=norm, s=20, edgecolor='k', linewidth=0.2, transform=ccrs.PlateCarree())
    
    # Add a colorbar to show the speed scale.
    # We get the figure from the axes and add the colorbar to it.
    fig = ax.get_figure()
    cbar = fig.colorbar(scatter, ax=ax, orientation='vertical', shrink=0.8, pad=0.08)
    cbar.set_label('Speed Over Ground (knots)')

    _annotate_mission_notes(ax, note_annotations or [])
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
_TEXT_PAGE_BODY_PROPS = {'va': 'top', 'ha': 'left', 'fontsize': 9, 'family': 'monospace'}
_TEXT_PAGE_WRAP_WIDTH = 100
_TEXT_PAGE_LINES_PER_PAGE = 58


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


def render_text_sections(
    add_footer_and_save,
    *,
    page_title: str,
    sections: List[Dict[str, Any]],
    page_size=(8.27, 11.69),
) -> None:
    """Render an ordered list of text sections across one or more PDF pages.

    Each page uses the same bounded text-axes pattern as `plot_errors_for_report`
    (figure-coord margins, monospace text, manual wrapping). When the flattened
    line list is longer than what fits on one page, additional pages are emitted
    with a "(continued)" suptitle. Saving and footer/page-number stamping is
    delegated to the supplied `add_footer_and_save` callback (the existing
    closure inside `generate_weekly_report`).
    """
    lines = _flatten_sections_to_lines(sections)
    if not lines:
        return

    pages = [
        lines[i:i + _TEXT_PAGE_LINES_PER_PAGE]
        for i in range(0, len(lines), _TEXT_PAGE_LINES_PER_PAGE)
    ]

    for page_idx, page_lines in enumerate(pages):
        fig = plt.figure(figsize=page_size)
        suptitle = page_title if page_idx == 0 else f"{page_title} (continued)"
        fig.suptitle(suptitle, fontsize=16)

        text_ax = fig.add_axes([
            _TEXT_PAGE_LEFT_MARGIN,
            _TEXT_PAGE_BOTTOM_MARGIN,
            1 - _TEXT_PAGE_LEFT_MARGIN - _TEXT_PAGE_RIGHT_MARGIN,
            _TEXT_PAGE_TOP_MARGIN - _TEXT_PAGE_BOTTOM_MARGIN,
        ])
        text_ax.set_axis_off()
        text_ax.text(0, 1.0, "\n".join(page_lines), **_TEXT_PAGE_BODY_PROPS)
        add_footer_and_save(fig)


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
    """
    Creates a mission summary page with key statistics from all data sources.

    Builds an ordered list of sections and delegates layout/pagination to the
    shared `render_text_sections` helper, replacing the previous dual-column
    `fig.text` + `y_pos -= 0.X` math that caused blocks to collide when content
    grew (e.g. long Mission Goals overlapping the Vehicle Errors block).
    """

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

    render_text_sections(
        add_footer_and_save,
        page_title="Mission Summary Statistics",
        sections=sections,
    )

def plot_ctd_for_report(fig, df: pd.DataFrame):
    """
    Plots detailed CTD data on the given Figure object for a PDF report.
    Assumes a pre-filtered and pre-processed DataFrame.
    """
    if df.empty:
        fig.text(0.5, 0.5, "No CTD data in the selected range.", ha='center', va='center')
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("CTD Summary", fontsize=16)

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

def plot_errors_for_report(add_footer_and_save, df: pd.DataFrame) -> None:
    """
    Creates one or more PDF pages with a bulleted list of recent vehicle errors.

    Delegates layout/margins/wrapping to `render_text_sections`, matching the
    same bounded-axes + monospace + textwrap pattern used elsewhere in reports.
    """
    if df.empty:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(
            0.5, 0.5,
            "No vehicle errors reported in the selected range.",
            ha='center', va='center',
        )
        add_footer_and_save(fig)
        return

    df_display = df.copy().tail(15)

    body_lines: List[str] = []
    for _, row in df_display.iterrows():
        vehicle = row.get('vehicleName', 'N/A')
        message = str(row.get('error_Message', 'No message.'))
        message = message.replace('@', '@\u200B')

        entry_text = f"• {vehicle}: {message}"
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
        fig.text(0.5, 0.5, "No weather data in the selected range.", ha='center', va='center')
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("Weather Summary", fontsize=16)

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
        fig.text(0.5, 0.5, "No wave data in the selected range.", ha='center', va='center')
        return

    axs = fig.subplots(3, 1, sharex=True)
    fig.suptitle("Wave Summary", fontsize=16)

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

    # Plot Mean Wave Direction
    if "MeanWaveDirection" in df.columns:
        axs[2].plot(df["Timestamp"], df["MeanWaveDirection"], "y-", label="Mean Direction (°)")
        axs[2].set_ylabel("Direction (°)")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left")

    axs[2].set_xlabel("Time (UTC)")
