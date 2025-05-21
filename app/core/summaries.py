import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from .processors import (
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df
)
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

def time_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/A"
    # Ensure datetime is timezone-aware (assume UTC if naive)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    if seconds < 0:
        return "in the future" 
    if seconds < 2:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    
    minutes = seconds / 60
    if minutes < 2:
        return "1 minute ago"
    if minutes < 60:
        return f"{int(minutes)} minutes ago"
        
    hours = minutes / 60
    if hours < 2:
        return "1 hour ago"
    if hours < 24:
        return f"{int(hours)} hours ago"
        
    days = hours / 24
    if days < 2:
        return "1 day ago"
    return f"{int(days)} days ago"

def get_power_status(df_power: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_power is None or df_power.empty:
        return result_shell

    try:
        df_power_processed = preprocess_power_df(df_power.copy())
    except Exception as e:
        logger.warning(f"Error preprocessing power data for summary: {e}")
        return result_shell

    if not df_power_processed.empty and "Timestamp" in df_power_processed.columns:
        df_power_processed["Timestamp"] = pd.to_datetime(df_power_processed["Timestamp"], errors='coerce')
        df_power_processed = df_power_processed.dropna(subset=["Timestamp"])

        if not df_power_processed.empty:
            latest_timestamp_obj = df_power_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_power_processed.sort_values(by="Timestamp", ascending=False).iloc[0]
            
            result_shell["values"] = {
                "BatteryWattHours": last_row.get("BatteryWattHours"),
                "SolarInputWatts": last_row.get("SolarInputWatts"),
                "PowerDrawWatts": last_row.get("PowerDrawWatts"),
                "NetPowerWatts": last_row.get("NetPowerWatts"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_ctd_status(df_ctd: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_ctd is None or df_ctd.empty:
        return result_shell

    try:
        df_ctd_processed = preprocess_ctd_df(df_ctd.copy())
    except Exception as e:
        logger.warning(f"Error preprocessing CTD data for summary: {e}")
        return result_shell

    if not df_ctd_processed.empty and "Timestamp" in df_ctd_processed.columns:
        df_ctd_processed["Timestamp"] = pd.to_datetime(df_ctd_processed["Timestamp"], errors='coerce')
        df_ctd_processed = df_ctd_processed.dropna(subset=["Timestamp"])

        if not df_ctd_processed.empty:
            latest_timestamp_obj = df_ctd_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_ctd_processed.sort_values(by="Timestamp", ascending=False).iloc[0]
            
            result_shell["values"] = {
                "WaterTemperature": last_row.get("WaterTemperature"),
                "Salinity": last_row.get("Salinity"),
                "Conductivity": last_row.get("Conductivity"),
                "DissolvedOxygen": last_row.get("DissolvedOxygen"),
                "Pressure": last_row.get("Pressure"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_weather_status(df_weather: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_weather is None or df_weather.empty:
        return result_shell

    try:
        df_weather_processed = preprocess_weather_df(df_weather.copy())
    except Exception as e:
        logger.warning(f"Error preprocessing Weather data for summary: {e}")
        return result_shell

    if not df_weather_processed.empty and "Timestamp" in df_weather_processed.columns:
        df_weather_processed["Timestamp"] = pd.to_datetime(df_weather_processed["Timestamp"], errors='coerce')
        df_weather_processed = df_weather_processed.dropna(subset=["Timestamp"])

        if not df_weather_processed.empty:
            latest_timestamp_obj = df_weather_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_weather_processed.sort_values(by="Timestamp", ascending=False).iloc[0]
            
            result_shell["values"] = {
                "AirTemperature": last_row.get("AirTemperature"),
                "WindSpeed": last_row.get("WindSpeed"),
                "WindGust": last_row.get("WindGust"),
                "WindDirection": last_row.get("WindDirection"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_wave_status(df_waves: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_waves is None or df_waves.empty:
        return result_shell

    try:
        df_waves_processed = preprocess_wave_df(df_waves.copy())
    except Exception as e:
        logger.warning(f"Error preprocessing Wave data for summary: {e}")
        return result_shell

    if not df_waves_processed.empty and "Timestamp" in df_waves_processed.columns:
        df_waves_processed["Timestamp"] = pd.to_datetime(df_waves_processed["Timestamp"], errors='coerce')
        df_waves_processed = df_waves_processed.dropna(subset=["Timestamp"])

        if not df_waves_processed.empty:
            latest_timestamp_obj = df_waves_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_waves_processed.sort_values(by="Timestamp", ascending=False).iloc[0]
            
            result_shell["values"] = {
                "SignificantWaveHeight": last_row.get("SignificantWaveHeight"),
                "WavePeriod": last_row.get("WavePeriod"), # Assuming this is PeakPeriod from index.html
                "MeanDirection": last_row.get("MeanWaveDirection"),
                # "SurfaceTemperature": last_row.get("SurfaceTemperature"), // This line is removed
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

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