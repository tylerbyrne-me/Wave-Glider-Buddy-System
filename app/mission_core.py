from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests
import io
import logging

# logger = logging.getLogger(__name__)


# --- Config Functions ---

def ensure_plots_dir():
    plots_dir = Path("waveglider_plots_temp")
    plots_dir.mkdir(exist_ok=True)
    return plots_dir


def load_report(report_type: str, mission_id: str, base_path: Path = None, base_url: str = None):
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

    if base_path: # Attempt to load from local path if provided
        file_path = Path(base_path) / mission_id / filename
        # Let exceptions like FileNotFoundError, pd.errors.EmptyDataError propagate
        return pd.read_csv(file_path)

    elif base_url: # Attempt to load from remote URL if provided (and base_path was not)
        url = f"{str(base_url).rstrip('/')}/{mission_id}/{filename}"
        try:
            response = requests.get(url, timeout=10) # Added timeout
            response.raise_for_status() # Raises HTTPError for bad responses (4XX or 5XX)
            return pd.read_csv(io.StringIO(response.text))
        except requests.exceptions.RequestException as e:
            # logger.error(f"Failed to fetch data from URL {url}: {e}") # Uncomment if logger is configured
            raise  # Re-raise the exception to be handled by the caller
    else: # Neither base_path nor base_url provided
        raise ValueError("Either base_path or base_url must be provided to load_report.")


def standardize_timestamp_column(df, preferred="Timestamp"):
    """Renames the first found common timestamp column"""
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in ["timeStamp", "gliderTimeStamp", "lastLocationFix"]:
            df = df.rename(columns={col: preferred})
            return df
    return df

# --- Preprocessing Functions ---

def _preprocess_power_df(df):
    if df is None or df.empty:
        return pd.DataFrame() # Return empty DataFrame to avoid errors downstream
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    # Scale and rename power columns
    # Assuming original CSV columns are like 'totalBatteryPower', 'solarPowerGenerated', 'outputPortPower'
    # These might need adjustment based on actual CSV headers
    rename_map = {
        "totalBatteryPower": "BatteryWattHours",
        "solarPowerGenerated": "SolarInputWatts",
        "outputPortPower": "PowerDrawWatts"
    }
    for old_name, new_name in rename_map.items():
        if old_name in df.columns:
            df[new_name] = df[old_name] / 1000 # Assuming values are in mWh or mW
            if old_name != new_name: # Avoid deleting if old_name is same as new_name (though unlikely here)
                df = df.drop(columns=[old_name], errors='ignore')
        elif new_name not in df.columns and old_name not in df.columns: # If neither new nor old name exists
            df[new_name] = np.nan # Add the column with NaNs

    if "SolarInputWatts" in df.columns and "PowerDrawWatts" in df.columns:
        df["NetPowerWatts"] = df["SolarInputWatts"] - df["PowerDrawWatts"] #update to ouput power if necessary, but battery charge rate might be even better
    else:
        df["NetPowerWatts"] = np.nan

    return df
# --
def _preprocess_ctd_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    df = standardize_timestamp_column(df, preferred="Timestamp")

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors='coerce')
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        'temperature (degC)': 'WaterTemperature',
        'salinity (PSU)': 'Salinity',
        'conductivity (S/m)': 'Conductivity',
        'oxygen (freq)': 'DissolvedOxygen', # Assuming this is the raw frequency, update later with calibraiton input data
        'pressure (dbar)': 'Pressure',
    }
    df = df.rename(columns=rename_map)
    # Ensure all target columns exist, adding them with NaN if not
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df
# --
def _preprocess_weather_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        "avgTemp(C)": "AirTemperature",
        "avgWindSpeed(kt)": "WindSpeed",
        "gustSpeed(kt)": "WindGust",
        "avgWindDir(deg)": "WindDirection",
    }
    df = df.rename(columns=rename_map)
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df
# --
def _preprocess_wave_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        "hs (m)": "SignificantWaveHeight",
        "tp (s)": "WavePeriod",
        "dp (deg)": "MeanWaveDirection",
    }
    df = df.rename(columns=rename_map)
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df
# --
def _preprocess_ais_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="LastSeenTimestamp")
    df["LastSeenTimestamp"] = pd.to_datetime(df["LastSeenTimestamp"], errors="coerce")
    df = df.dropna(subset=["LastSeenTimestamp"])
    if df.empty:
        return df

    rename_map = {
        "shipName": "ShipName",
        "mmsi": "MMSI",
        "speedOverGround": "SpeedOverGround",
        "courseOverGround": "CourseOverGround",
    }
    df = df.rename(columns=rename_map)
    # Ensure MMSI is int, handle potential float if NaNs were present then filled
    if "MMSI" in df.columns:
        # Convert to numeric, coercing errors. This might result in floats.
        temp_mmsi_series = pd.to_numeric(df["MMSI"], errors='coerce')

        # If the result is a float series, ensure all valid numbers are whole numbers.
        # Non-whole numbers will be converted to NaN, which Int64 can handle as <NA>.
        if pd.api.types.is_float_dtype(temp_mmsi_series):
            # Create a boolean mask for numbers that are not whole
            not_whole_number_mask = temp_mmsi_series.notna() & (temp_mmsi_series != np.floor(temp_mmsi_series))
            # Set these non-whole numbers to NaN
            temp_mmsi_series[not_whole_number_mask] = np.nan
        
        # Now, cast to Int64. All numbers should be whole or NaN.
        df["MMSI"] = temp_mmsi_series.astype('Int64')

    for target_col in rename_map.values():
        if target_col not in df.columns:
            if target_col == "MMSI":
                 df[target_col] = pd.Series(dtype='Int64')
            else:
                df[target_col] = np.nan
    return df
# --
def _preprocess_error_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        "vehicleName": "VehicleName",
        "selfCorrected": "SelfCorrected", # Keep as is, handle boolean conversion later
        "error_Message": "ErrorMessage", # truncate message later for common name/verbage
    }
    df = df.rename(columns=rename_map)
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df

# --- Status Functions ---

def get_power_status(power_df):
    power_df = _preprocess_power_df(power_df)
    if power_df.empty:
        return None


    latest = power_df.sort_values("Timestamp", ascending=False).iloc[0]


    return {
        "BatteryWattHours": latest.get("BatteryWattHours"),
        "SolarInputWatts": latest.get("SolarInputWatts"),
        "PowerDrawWatts": latest.get("PowerDrawWatts"),
        "NetPowerWatts": latest.get("NetPowerWatts"),
        "Timestamp": latest["Timestamp"]
    }
# --
def get_ctd_status(ctd_df):
    ctd_df = _preprocess_ctd_df(ctd_df)
    if ctd_df.empty:
        return None

    # Ensure sorting by the standardized "Timestamp" column
    latest = ctd_df.sort_values("Timestamp", ascending=False).iloc[0]

    return {
        "WaterTemperature": latest.get("WaterTemperature"), # Key matches preprocessed column
        "Salinity": latest.get("Salinity"),
        "Conductivity": latest.get("Conductivity"),
        "DissolvedOxygen": latest.get("DissolvedOxygen"),
        "Pressure": latest.get("Pressure"),
        "Timestamp": latest["Timestamp"]
    }
# --
def get_weather_status(weather_df):
    weather_df = _preprocess_weather_df(weather_df)
    if weather_df.empty:
        return None

    # Ensure sorting by the standardized "Timestamp" column
    latest = weather_df.sort_values("Timestamp", ascending=False).iloc[0]

    return {
        "AirTemperature": latest.get("AirTemperature"),
        "WindSpeed": latest.get("WindSpeed"),
        "WindGust": latest.get("WindGust"),
        "WindDirection": latest.get("WindDirection"),
        "Timestamp": latest["Timestamp"]
    }
# --
def get_wave_status(wave_df):
    wave_df = _preprocess_wave_df(wave_df)
    if wave_df.empty:
        return None

    latest = wave_df.sort_values("Timestamp", ascending=False).iloc[0]

    return {
        "SignificantWaveHeight": latest.get("SignificantWaveHeight"),
        "WavePeriod": latest.get("WavePeriod"),
        "MeanWaveDirection": latest.get("MeanWaveDirection"),
        "Timestamp": latest["Timestamp"]
    }
# --
def get_ais_summary(ais_df, max_age_hours=24):
    ais_df = _preprocess_ais_df(ais_df) # Use full preprocessing
    if ais_df.empty:
        return []

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    # Ensure LastSeenTimestamp is datetime for comparison
    recent = ais_df[pd.to_datetime(ais_df["LastSeenTimestamp"], errors='coerce') > cutoff]
    if recent.empty:
        return []
    
    # MMSI present for grouping
    if "MMSI" not in recent.columns or recent["MMSI"].isnull().all():
        return [] # Cannot group by MMSI if it's missing or all null
    
    grouped = recent.sort_values("LastSeenTimestamp", ascending=False).groupby("MMSI", as_index=False) # as_index=False is good

    vessels = []
    for _, group in grouped:
        row = group.iloc[0]
        vessel = {
            "ShipName": row.get("ShipName", "Unknown"),
            "MMSI": row.get("MMSI"), #int64 or None
            "SpeedOverGround": row.get("SpeedOverGround"),
            "CourseOverGround": row.get("CourseOverGround"),
            "LastSeenTimestamp": row["LastSeenTimestamp"]
        }
        vessels.append(vessel)

    return sorted(vessels, key=lambda v: v["LastSeenTimestamp"], reverse=True)
# --
def get_recent_errors(error_df, max_age_hours=24):
    error_df = _preprocess_error_df(error_df)
    if error_df.empty:
        return []

    recent = error_df[error_df["Timestamp"] > datetime.now() - timedelta(hours=max_age_hours)]
    if recent.empty:
        return []

    # Standardize columns to_dict
    expected_cols = ["Timestamp", "VehicleName", "SelfCorrected", "ErrorMessage"]
    for col in expected_cols:
        if col not in recent.columns:
            recent[col] = np.nan # _precrocess should catch but add if missing

    return recent.sort_values("Timestamp", ascending=False).to_dict(orient="records")

# --- Forecast Function ---
# --
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


# --- Display and Plot Functions ---

def generate_power_plot(power_df, mission_id, hours_back=72, output_dir=None):
    power_df = _preprocess_power_df(power_df) 
    recent_power = power_df[power_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_power.empty:
        return None

    # Set Timestamp as index for resampling
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
    ctd_df = _preprocess_ctd_df(ctd_df)
    if ctd_df.empty:
        return None

    recent_data = ctd_df[ctd_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]

    if recent_data.empty:
        return None

    # Set Timestamp as index for resampling
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
    weather_df = _preprocess_weather_df(weather_df)
    recent_weather = weather_df[weather_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]
    if recent_weather.empty:
        return None

    # Set Timestamp as index for resampling
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
    wave_df = _preprocess_wave_df(wave_df)
    recent = wave_df[wave_df["Timestamp"] > datetime.now() - timedelta(hours=hours_back)]

    if recent.empty:
        return None

    # Set Timestamp as index for resampling
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

    # limit to 48hrs, meteo defaults to 7-days
    display_limit = 48

    for i in range(min(len(times), display_limit)):
        t, temp, wind, p = times[i], temps[i], winds[i], precip[i]
        table.add_row(t, f"{temp:.1f}", f"{wind:.1f}", f"{p:.1f}")

    console.print(table)
