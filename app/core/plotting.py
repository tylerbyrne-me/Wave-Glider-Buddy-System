from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER
import numpy as np # type: ignore

from .processors import (preprocess_ctd_df, preprocess_power_df,
                         preprocess_wave_df, preprocess_weather_df)
from .processors import preprocess_telemetry_df # Explicitly import for report plot

def ensure_plots_dir():
    plots_dir = Path("waveglider_plots_temp")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir


def generate_power_plot(power_df, mission_id, hours_back=72, output_dir=None):
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

        plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
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
        plt.savefig(plot_path)
        plt.close()
        return plot_path
    except Exception as e:
        print(f"Error generating power plot: {e}")
        return None


def generate_ctd_plot(ctd_df, mission_id, hours_back=24, output_dir=None):
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

        plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
        plot_path = plots_dir / f"ctd_trend_{mission_id}.png"

        fig, axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        if "WaterTemperature" in hourly_data.columns:
            axs[0].plot(
                hourly_data.index,
                hourly_data["WaterTemperature"],
                "r-", # type: ignore
                label="Water Temperature (°C)", # type: ignore
            )
            axs[0].set_ylabel("Temperature (°C)")
            axs[0].grid(True, alpha=0.3)
            axs[0].legend(loc="upper left")
        if "Salinity" in hourly_data.columns:
            axs[1].plot(
                hourly_data.index, hourly_data["Salinity"], "b-", label="Salinity (PSU)"
            ) # type: ignore
            axs[1].set_ylabel("Salinity (PSU)")
            axs[1].grid(True, alpha=0.3)
            axs[1].legend(loc="upper left")
        if "Conductivity" in hourly_data.columns:
            axs[2].plot(
                hourly_data.index,
                hourly_data["Conductivity"],
                "orange", # type: ignore
                label="Conductivity (S/m)", # type: ignore
            )
        if "DissolvedOxygen" in hourly_data.columns:
            ax2_twin = axs[2].twinx()
            ax2_twin.plot(
                hourly_data.index, hourly_data["DissolvedOxygen"], "g--", label="O₂ (Hz)"
            )
            ax2_twin.set_ylabel("O₂ (Hz)", color="green")
            ax2_twin.tick_params(axis="y", labelcolor="green")
        axs[2].set_ylabel("Conductivity (S/m)")
        axs[2].set_xlabel("Time")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left") # type: ignore
        plt.suptitle(f"CTD Data Trends - Last {hours_back} Hours")
        plt.tight_layout()
        plt.savefig(plot_path)
        plt.close()
        return plot_path
    except Exception as e:
        print(f"Error generating CTD plot: {e}")
        return None


def generate_weather_plot(weather_df, mission_id, hours_back=72, output_dir=None):
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

        plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
        plot_path = plots_dir / f"weather_trend_{mission_id}.png"

        plt.figure(figsize=(10, 6))
        if "AirTemperature" in hourly.columns:
            plt.plot(
                hourly.index, # type: ignore
                hourly["AirTemperature"], # type: ignore
                label="Air Temp (°C)",
                color="blue",
            )
        if "WindSpeed" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WindSpeed"], label="Wind Speed (kt)", color="green" # type: ignore
            )
        if "WindGust" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WindGust"], label="Wind Gust (kt)", color="red" # type: ignore
            )
        plt.title(f"Weather Trends - Mission {mission_id}") # type: ignore
        plt.xlabel("Time")
        plt.ylabel("Value")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path)
        plt.close()
        return plot_path
    except Exception as e:
        print(f"Error generating weather plot: {e}")
        return None


def generate_wave_plot(wave_df, mission_id, hours_back=72, output_dir=None):
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

        plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
        plot_path = plots_dir / f"wave_trend_{mission_id}.png"

        plt.figure(figsize=(10, 6))
        if "SignificantWaveHeight" in hourly.columns:
            plt.plot(
                hourly.index,
                hourly["SignificantWaveHeight"],
                label="Wave Height (m)", # type: ignore
                color="blue",
            )
        if "WavePeriod" in hourly.columns:
            plt.plot(
                hourly.index, hourly["WavePeriod"], label="Wave Period (s)", color="orange" # type: ignore
            )
        if "MeanWaveDirection" in hourly.columns:
            plt.plot(
                hourly.index,
                hourly["MeanWaveDirection"],
                label="Wave Dir (°)", # type: ignore
                color="green",
            )
        plt.title(f"Wave Conditions - Mission {mission_id}") # type: ignore
        plt.xlabel("Time")
        plt.ylabel("Value")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path)
        plt.close()
        return plot_path
    except Exception as e:
        print(f"Error generating wave plot: {e}")
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

def plot_telemetry_for_report(ax, df: pd.DataFrame):
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

    norm = mcolors.Normalize(vmin=0, vmax=4)
    cmap = cm.get_cmap('viridis')

    ax.scatter(df['longitude'], df['latitude'], c=df['speedOverGround'], cmap=cmap, norm=norm, s=20, edgecolor='k', linewidth=0.2, transform=ccrs.PlateCarree())
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

    # Plot Salinity
    if "Salinity" in df.columns:
        axs[1].plot(df["Timestamp"], df["Salinity"], "b-", label="Salinity (PSU)")
        axs[1].set_ylabel("Salinity (PSU)")
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc="upper left")

    # Plot Conductivity
    if "Conductivity" in df.columns:
        axs[2].plot(df["Timestamp"], df["Conductivity"], "orange", label="Conductivity (S/m)")
        axs[2].set_ylabel("Conductivity (S/m)")
        axs[2].grid(True, alpha=0.3)
        axs[2].legend(loc="upper left")

    axs[2].set_xlabel("Time (UTC)")

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
