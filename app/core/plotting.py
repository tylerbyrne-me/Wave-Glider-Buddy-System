from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np # type: ignore

from .processors import (preprocess_ctd_df, preprocess_power_df,
                         preprocess_wave_df, preprocess_weather_df)


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
