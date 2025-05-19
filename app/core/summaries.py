import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from .processors import (
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df
)

def get_power_status(power_df):
    power_df = preprocess_power_df(power_df)
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

def get_ctd_status(ctd_df):
    ctd_df = preprocess_ctd_df(ctd_df)
    if ctd_df.empty:
        return None
    latest = ctd_df.sort_values("Timestamp", ascending=False).iloc[0]
    return {
        "WaterTemperature": latest.get("WaterTemperature"),
        "Salinity": latest.get("Salinity"),
        "Conductivity": latest.get("Conductivity"),
        "DissolvedOxygen": latest.get("DissolvedOxygen"),
        "Pressure": latest.get("Pressure"),
        "Timestamp": latest["Timestamp"]
    }

def get_weather_status(weather_df):
    weather_df = preprocess_weather_df(weather_df)
    if weather_df.empty:
        return None
    latest = weather_df.sort_values("Timestamp", ascending=False).iloc[0]
    return {
        "AirTemperature": latest.get("AirTemperature"),
        "WindSpeed": latest.get("WindSpeed"),
        "WindGust": latest.get("WindGust"),
        "WindDirection": latest.get("WindDirection"),
        "Timestamp": latest["Timestamp"]
    }

def get_wave_status(wave_df):
    wave_df = preprocess_wave_df(wave_df)
    if wave_df.empty:
        return None
    latest = wave_df.sort_values("Timestamp", ascending=False).iloc[0]
    return {
        "SignificantWaveHeight": latest.get("SignificantWaveHeight"),
        "WavePeriod": latest.get("WavePeriod"),
        "MeanWaveDirection": latest.get("MeanWaveDirection"),
        "Timestamp": latest["Timestamp"]
    }

def get_ais_summary(ais_df, max_age_hours=24):
    ais_df = preprocess_ais_df(ais_df)
    if ais_df.empty:
        return []

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    recent = ais_df[pd.to_datetime(ais_df["LastSeenTimestamp"], errors='coerce') > cutoff]
    if recent.empty:
        return []
    
    if "MMSI" not in recent.columns or recent["MMSI"].isnull().all():
        return []
    
    grouped = recent.sort_values("LastSeenTimestamp", ascending=False).groupby("MMSI", as_index=False)
    vessels = []
    for _, group in grouped:
        row = group.iloc[0]
        vessel = {
            "ShipName": row.get("ShipName", "Unknown"),
            "MMSI": row.get("MMSI"),
            "SpeedOverGround": row.get("SpeedOverGround"),
            "CourseOverGround": row.get("CourseOverGround"),
            "LastSeenTimestamp": row["LastSeenTimestamp"]
        }
        vessels.append(vessel)
    return sorted(vessels, key=lambda v: v["LastSeenTimestamp"], reverse=True)

def get_recent_errors(error_df, max_age_hours=24):
    error_df = preprocess_error_df(error_df)
    if error_df.empty:
        return []

    recent = error_df[error_df["Timestamp"] > datetime.now() - timedelta(hours=max_age_hours)]
    if recent.empty:
        return []

    expected_cols = ["Timestamp", "VehicleName", "SelfCorrected", "ErrorMessage"]
    for col in expected_cols:
        if col not in recent.columns:
            recent[col] = np.nan
    return recent.sort_values("Timestamp", ascending=False).to_dict(orient="records")