from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from .processors import preprocess_power_df, preprocess_ctd_df, preprocess_weather_df, preprocess_wave_df

def ensure_plots_dir():
    plots_dir = Path("waveglider_plots_temp")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir

def generate_power_plot(power_df, mission_id, hours_back=72, output_dir=None):
    power_df = preprocess_power_df(power_df) 
    recent_power = power_df[power_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_power.empty:
        return None

    data_to_resample = recent_power.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    hourly_power = numeric_cols.resample('1h').mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"power_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))
    if "BatteryWattHours" in hourly_power.columns:
        plt.plot(hourly_power.index, hourly_power["BatteryWattHours"], label="Battery (Wh)", color="blue")
    if "SolarInputWatts" in hourly_power.columns:
        plt.plot(hourly_power.index, hourly_power["SolarInputWatts"], label="Solar Input (W)", color="orange")
    if "PowerDrawWatts" in hourly_power.columns:
        plt.plot(hourly_power.index, hourly_power["PowerDrawWatts"], label="Power Draw (W)", color="red")
    if "NetPowerWatts" in hourly_power.columns:
        plt.plot(hourly_power.index, hourly_power["NetPowerWatts"], label="Net Power (W)", color="green")
    
    plt.title(f"Power Trends - Mission {mission_id}")
    plt.xlabel("Time")
    plt.ylabel("Power")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()
    return plot_path

def generate_ctd_plot(ctd_df, mission_id, hours_back=24, output_dir=None):
    ctd_df = preprocess_ctd_df(ctd_df)
    if ctd_df.empty:
        return None

    recent_data = ctd_df[ctd_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_data.empty:
        return None

    data_to_resample = recent_data.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    hourly_data = numeric_cols.resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"ctd_trend_{mission_id}.png"

    fig, axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    if 'WaterTemperature' in hourly_data.columns:
        axs[0].plot(hourly_data.index, hourly_data['WaterTemperature'], 'r-', label='Water Temperature (°C)')
        axs[0].set_ylabel('Temperature (°C)')
        axs[0].grid(True, alpha=0.3)
        axs[0].legend(loc='upper left')
    if 'Salinity' in hourly_data.columns:
        axs[1].plot(hourly_data.index, hourly_data['Salinity'], 'b-', label='Salinity (PSU)')
        axs[1].set_ylabel('Salinity (PSU)')
        axs[1].grid(True, alpha=0.3)
        axs[1].legend(loc='upper left')
    if 'Conductivity' in hourly_data.columns:
        axs[2].plot(hourly_data.index, hourly_data['Conductivity'], 'orange', label='Conductivity (S/m)')
    if 'DissolvedOxygen' in hourly_data.columns:
        ax2_twin = axs[2].twinx()
        ax2_twin.plot(hourly_data.index, hourly_data['DissolvedOxygen'], 'g--', label='O₂ (Hz)')
        ax2_twin.set_ylabel('O₂ (Hz)', color='green')
        ax2_twin.tick_params(axis='y', labelcolor='green')
    axs[2].set_ylabel('Conductivity (S/m)')
    axs[2].set_xlabel('Time')
    axs[2].grid(True, alpha=0.3)
    axs[2].legend(loc='upper left')
    plt.suptitle(f'CTD Data Trends - Last {hours_back} Hours')
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()
    return plot_path

def generate_weather_plot(weather_df, mission_id, hours_back=72, output_dir=None):
    weather_df = preprocess_weather_df(weather_df)
    recent_weather = weather_df[weather_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_weather.empty:
        return None

    data_to_resample = recent_weather.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    hourly = numeric_cols.resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"weather_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))
    if "AirTemperature" in hourly.columns:
        plt.plot(hourly.index, hourly["AirTemperature"], label="Air Temp (°C)", color="blue")
    if "WindSpeed" in hourly.columns:
        plt.plot(hourly.index, hourly["WindSpeed"], label="Wind Speed (kt)", color="green")
    if "WindGust" in hourly.columns:
        plt.plot(hourly.index, hourly["WindGust"], label="Wind Gust (kt)", color="red")
    plt.title(f"Weather Trends - Mission {mission_id}")
    plt.xlabel("Time")
    plt.ylabel("Value")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()
    return plot_path

def generate_wave_plot(wave_df, mission_id, hours_back=72, output_dir=None):
    wave_df = preprocess_wave_df(wave_df)
    recent = wave_df[wave_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent.empty:
        return None

    data_to_resample = recent.set_index("Timestamp")
    numeric_cols = data_to_resample.select_dtypes(include=[np.number])
    hourly = numeric_cols.resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"wave_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))
    if "SignificantWaveHeight" in hourly.columns:
        plt.plot(hourly.index, hourly["SignificantWaveHeight"], label="Wave Height (m)", color="blue")
    if "WavePeriod" in hourly.columns:
        plt.plot(hourly.index, hourly["WavePeriod"], label="Wave Period (s)", color="orange")
    if "MeanWaveDirection" in hourly.columns:
        plt.plot(hourly.index, hourly["MeanWaveDirection"], label="Wave Dir (°)", color="green")
    plt.title(f"Wave Conditions - Mission {mission_id}")
    plt.xlabel("Time")
    plt.ylabel("Value")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()
    return plot_path