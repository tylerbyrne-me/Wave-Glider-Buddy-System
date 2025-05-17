from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests
import io


def ensure_plots_dir():
    plots_dir = Path("waveglider_plots")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir


def load_report(report_type, mission_id, base_path=None, base_url=None):
    # You can optionally expand this later
    reports = {
        "power": "Amps Power Summary Report.csv",
        "solar": "Amps Solar Input Port Report.csv",
        "ctd"  : "Seabird CTD Records with D.O..csv",
        "weather" : "Weather Records 2.csv",
        "waves": "GPS Waves Sensor Data.csv",
        "ais"  : "AIS Report.csv",
        "telemetry" : "Telemetry 6 Report by WGMS Datetime.csv",
        "errors": "Vehicle Error Report.csv"
    }

    if report_type not in reports:
        raise ValueError(f"Unknown report type: {report_type}")
    
    filename = reports[report_type]

    if base_path:
        file_path = Path(base_path) / mission_id / filename
        return pd.read_csv(file_path)

    elif base_url:
        url = f"{base_url}/{mission_id}/{filename}"
        response = requests.get(url)
        response.raise_for_status()
        return pd.read_csv(io.StringIO(response.text))

    else:
        # Default to local path
        default_path = Path(r"C:\Users\ty225269\Documents\1 - WG\2025\Spring Bloom 2025\Data")
        file_path = default_path / mission_id / filename
        return pd.read_csv(file_path)


def standardize_timestamp_column(df, preferred="timeStamp"):
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in ["gliderTimeStamp", "lastLocationFix"]:
            return df.rename(columns={col: preferred})
    return df



def get_power_status(power_df):
    power_df = standardize_timestamp_column(power_df)
    power_df["timeStamp"] = pd.to_datetime(power_df["timeStamp"], errors="coerce")
    power_df = power_df.dropna(subset=["timeStamp"])
    if power_df.empty:
        return None


    # Divide current-related columns by 1000 if they exist
    for col in ["totalBatteryPower", "solarPowerGenerated", "outputPortPower"]:
        if col in power_df.columns:
            power_df[col] = power_df[col] / 1000

    latest = power_df.sort_values("timeStamp", ascending=False).iloc[0]
    battery_wh = latest.get("totalBatteryPower")
    solar_input = latest.get("solarPowerGenerated")
    output_power = latest.get("outputPortPower")
    net_power = solar_input - output_power if solar_input is not None and output_power is not None else None

    return {
        "BatteryWattHours": battery_wh,
        "SolarInputWatts": solar_input,
        "PowerDrawWatts": output_power,
        "NetPower": net_power,
        "Timestamp": latest["timeStamp"]
    }

def get_ctd_status(ctd_df):
    ctd_df.rename(columns={
        'temperature (degC)': 'Temperature',
        'salinity (PSU)': 'Salinity',
        'conductivity (S/m)': 'Conductivity',
        'oxygen (freq)': 'DissolvedOxygen',
        'pressure (dbar)': 'Depth',
    }, inplace=True)

    ctd_df["timeStamp"] = pd.to_datetime(ctd_df["timeStamp"], errors='coerce')
    ctd_df = ctd_df.dropna(subset=["timeStamp"])

    if ctd_df.empty:
        return None

    latest = ctd_df.sort_values("timeStamp", ascending=False).iloc[0]

    return {
        "Temperature": latest.get("Temperature"),
        "Salinity": latest.get("Salinity"),
        "Conductivity": latest.get("Conductivity"),
        "DissolvedOxygen": latest.get("DissolvedOxygen"),
        "Depth": latest.get("Depth"),
        "Timestamp": latest["timeStamp"],
    }

def get_weather_status(weather_df):
    weather_df = standardize_timestamp_column(weather_df)
    weather_df["timeStamp"] = pd.to_datetime(weather_df["timeStamp"], errors="coerce")
    weather_df = weather_df.dropna(subset=["timeStamp"])
    if weather_df.empty:
        return None

    latest = weather_df.sort_values("timeStamp", ascending=False).iloc[0]

    return {
        "Temp": latest.get("avgTemp(C)"),
        "WindSpeed": latest.get("avgWindSpeed(kt)"),
        "Gust": latest.get("gustSpeed(kt)"),
        "Direction": latest.get("avgWindDir(deg)"),
        "Timestamp": latest["timeStamp"],
    }

def get_wave_status(wave_df):
    wave_df = standardize_timestamp_column(wave_df)
    wave_df["timeStamp"] = pd.to_datetime(wave_df["timeStamp"], errors="coerce")
    wave_df = wave_df.dropna(subset=["timeStamp"])
    if wave_df.empty:
        return None

    latest = wave_df.sort_values("timeStamp", ascending=False).iloc[0]

    return {
        "Height": latest.get("hs (m)"),
        "Period": latest.get("tp (s)"),
        "Direction": latest.get("dp (deg)"),
        "Timestamp": latest["timeStamp"],
    }

def get_ais_summary(ais_df, max_age_hours=24):
    ais_df = standardize_timestamp_column(ais_df)
    ais_df["timeStamp"] = pd.to_datetime(ais_df["timeStamp"], errors="coerce")
    ais_df = ais_df.dropna(subset=["timeStamp"])
    if ais_df.empty:
        return []

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    recent = ais_df[ais_df["timeStamp"] > cutoff]
    if recent.empty:
        return []

    grouped = recent.sort_values("timeStamp", ascending=False).groupby("mmsi", as_index=False)

    vessels = []
    for _, group in grouped:
        row = group.iloc[0]
        vessel = {
            "name": row.get("shipName", "Unknown"),
            "mmsi": int(row["mmsi"]) if "mmsi" in row else None,
            "sog": row.get("speedOverGround"),
            "cog": row.get("courseOverGround"),
            "last_seen": row["timeStamp"]
        }
        vessels.append(vessel)

    return sorted(vessels, key=lambda v: v["last_seen"], reverse=True)

def get_recent_errors(error_df, max_age_hours=24):
    error_df = standardize_timestamp_column(error_df)
    error_df["timeStamp"] = pd.to_datetime(error_df["timeStamp"])
    error_df = error_df.dropna(subset=["timeStamp"])

    if error_df.empty:
        return []

    recent = error_df[error_df["timeStamp"] > datetime.now() - timedelta(hours=max_age_hours)]
    if recent.empty:
        return []

    return recent.sort_values("timeStamp", ascending=False).to_dict(orient="records")

def get_open_meteo_forecast(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&hourly=temperature_2m,weathercode,precipitation,windspeed_10m"
    )
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Forecast API error: {e}")
        return None




def generate_power_plot(power_df, mission_id, hours_back=72, output_dir=None):
    power_df = standardize_timestamp_column(power_df)
    power_df["timeStamp"] = pd.to_datetime(power_df["timeStamp"], errors="coerce")
    power_df = power_df.dropna(subset=["timeStamp"])
    power_df = power_df.set_index("timeStamp")

    recent_power = power_df[power_df.index > datetime.now() - timedelta(hours=hours_back)]
    if recent_power.empty:
        return None

    hourly_power = recent_power.select_dtypes(include=[np.number]).resample('1h').mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"power_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))
    if "BatteryWattHours" in hourly_power:
        plt.plot(hourly_power.index, hourly_power["BatteryWattHours"], label="Battery (Wh)", color="blue")
    if "SolarInputWatts" in hourly_power:
        plt.plot(hourly_power.index, hourly_power["SolarInputWatts"], label="Solar Input (W)", color="orange")
    if "PowerDrawWatts" in hourly_power:
        plt.plot(hourly_power.index, hourly_power["PowerDrawWatts"], label="Power Draw (W)", color="red")

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
    ctd_df.rename(columns={
        'temperature (degC)': 'Temperature',
        'salinity (PSU)': 'Salinity',
        'conductivity (S/m)': 'Conductivity',
        'oxygen (freq)': 'DissolvedOxygen',
        'pressure (dbar)': 'Depth',
    }, inplace=True)

    ctd_df["timeStamp"] = pd.to_datetime(ctd_df["timeStamp"], errors='coerce')
    ctd_df = ctd_df.dropna(subset=["timeStamp"])

    if ctd_df.empty:
        return None

    ctd_df = ctd_df.set_index("timeStamp")
    recent_data = ctd_df[ctd_df.index > datetime.now() - timedelta(hours=hours_back)]

    if recent_data.empty:
        return None

    hourly_data = recent_data.select_dtypes(include=[np.number]).resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"ctd_trend_{mission_id}.png"

    fig, axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    if 'Temperature' in hourly_data.columns:
        axs[0].plot(hourly_data.index, hourly_data['Temperature'], 'r-', label='Temperature (°C)')
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
    weather_df = standardize_timestamp_column(weather_df)
    weather_df["timeStamp"] = pd.to_datetime(weather_df["timeStamp"], errors="coerce")
    weather_df = weather_df.dropna(subset=["timeStamp"])
    weather_df = weather_df.set_index("timeStamp")

    recent_weather = weather_df[weather_df.index > datetime.now() - timedelta(hours=hours_back)]
    if recent_weather.empty:
        return None

    hourly = recent_weather.select_dtypes(include=[np.number]).resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"weather_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))

    if "airTemperature" in hourly.columns:
        plt.plot(hourly.index, hourly["airTemperature"], label="Air Temp (°C)", color="blue")
    if "windSpeed" in hourly.columns:
        plt.plot(hourly.index, hourly["windSpeed"], label="Wind Speed (kt)", color="green")
    if "windGust" in hourly.columns:
        plt.plot(hourly.index, hourly["windGust"], label="Wind Gust (kt)", color="red")

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
    wave_df = standardize_timestamp_column(wave_df)
    wave_df["timeStamp"] = pd.to_datetime(wave_df["timeStamp"], errors="coerce")
    wave_df = wave_df.dropna(subset=["timeStamp"])
    wave_df = wave_df.set_index("timeStamp")

    recent = wave_df[wave_df.index > datetime.now() - timedelta(hours=hours_back)]
    if recent.empty:
        return None

    hourly = recent.select_dtypes(include=[np.number]).resample("1h").mean()

    plots_dir = ensure_plots_dir() if output_dir is None else Path(output_dir)
    plot_path = plots_dir / f"wave_trend_{mission_id}.png"

    plt.figure(figsize=(10, 6))
    if "waveHeight" in hourly.columns:
        plt.plot(hourly.index, hourly["hs (m)"], label="Wave Height (m)", color="blue")
    if "wavePeriod" in hourly.columns:
        plt.plot(hourly.index, hourly["tp (s)"], label="Wave Period (s)", color="orange")
    if "waveDirection" in hourly.columns:
        plt.plot(hourly.index, hourly["dp (deg)"], label="Wave Dir (°)", color="green")

    plt.title(f"Wave Conditions - Mission {mission_id}")
    plt.xlabel("Time")
    plt.ylabel("Value")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(plot_path)
    plt.close()

    return plot_path

def display_weather_forecast(forecast_data):
    hourly = forecast_data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get("windspeed_10m", [])
    precip = hourly.get("precipitation", [])

    if not times:
        return

    from rich.table import Table
    from rich.console import Console

    console = Console()
    table = Table(title="48-hour Weather Forecast")
    table.add_column("Time")
    table.add_column("Temp (°C)")
    table.add_column("Wind (kt)")
    table.add_column("Precip (mm)")

    for t, temp, wind, p in zip(times, temps, winds, precip):
        table.add_row(t, f"{temp:.1f}", f"{wind:.1f}", f"{p:.1f}")

    console.print(table)




