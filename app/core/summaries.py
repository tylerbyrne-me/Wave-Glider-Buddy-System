import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from .processors import (
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df, preprocess_vr2c_df,
    preprocess_fluorometer_df
)
from typing import Optional, List, Dict, Any
import logging
import httpx

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
        # Processor now handles copying and ensures UTC timestamps
        df_power_processed = preprocess_power_df(df_power) 
    except Exception as e:
        logger.warning(f"Error preprocessing power data for summary: {e}")
        return result_shell

    # df_power_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_power_processed.empty: # "Timestamp" column is guaranteed if not empty
            latest_timestamp_obj = df_power_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_power_processed.loc[df_power_processed["Timestamp"].idxmax()]
            
            result_shell["values"] = {
                "BatteryWattHours": last_row.get("BatteryWattHours"),
                "SolarInputWatts": last_row.get("SolarInputWatts"),
                "PowerDrawWatts": last_row.get("PowerDrawWatts"),
                "NetPowerWatts": last_row.get("NetPowerWatts"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_fluorometer_status(df_fluorometer: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_fluorometer is None or df_fluorometer.empty:
        return result_shell

    try:
        df_fluorometer_processed = preprocess_fluorometer_df(df_fluorometer)
    except Exception as e:
        logger.warning(f"Error preprocessing Fluorometer data for summary: {e}")
        return result_shell

    # df_fluorometer_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_fluorometer_processed.empty: # "Timestamp" column is guaranteed
            logger.info(f"Fluorometer Summary: df_fluorometer_processed head before selecting last_row:\n{df_fluorometer_processed[['Timestamp', 'C1_Avg', 'C2_Avg', 'C3_Avg', 'Temperature_Fluor']].head()}")
            logger.info(f"Fluorometer Summary: df_fluorometer_processed tail before selecting last_row:\n{df_fluorometer_processed[['Timestamp', 'C1_Avg', 'C2_Avg', 'C3_Avg', 'Temperature_Fluor']].tail()}")

            latest_timestamp_obj = df_fluorometer_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_fluorometer_processed.loc[df_fluorometer_processed["Timestamp"].idxmax()]
            logger.info(f"Fluorometer Summary: last_row content:\n{last_row}")
            
            result_shell["values"] = {
                "C1_Avg": last_row.get("C1_Avg"),
                "C2_Avg": last_row.get("C2_Avg"),
                "C3_Avg": last_row.get("C3_Avg"),
                "Temperature_Fluor": last_row.get("Temperature_Fluor"),
                "Latitude": last_row.get("Latitude"),
                "Longitude": last_row.get("Longitude"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_ctd_status(df_ctd: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_ctd is None or df_ctd.empty:
        return result_shell

    try:
        df_ctd_processed = preprocess_ctd_df(df_ctd)
    except Exception as e:
        logger.warning(f"Error preprocessing CTD data for summary: {e}")
        return result_shell

    # df_ctd_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_ctd_processed.empty: # "Timestamp" column is guaranteed
            latest_timestamp_obj = df_ctd_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_ctd_processed.loc[df_ctd_processed["Timestamp"].idxmax()]
            
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
        df_weather_processed = preprocess_weather_df(df_weather)
    except Exception as e:
        logger.warning(f"Error preprocessing Weather data for summary: {e}")
        return result_shell

    # df_weather_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_weather_processed.empty: # "Timestamp" column is guaranteed
            latest_timestamp_obj = df_weather_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_weather_processed.loc[df_weather_processed["Timestamp"].idxmax()]
            
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
        df_waves_processed = preprocess_wave_df(df_waves)
    except Exception as e:
        logger.warning(f"Error preprocessing Wave data for summary: {e}")
        return result_shell

    # df_waves_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_waves_processed.empty: # "Timestamp" column is guaranteed
            latest_timestamp_obj = df_waves_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_waves_processed.loc[df_waves_processed["Timestamp"].idxmax()]
            
            result_shell["values"] = {
                "SignificantWaveHeight": last_row.get("SignificantWaveHeight"),
                "WavePeriod": last_row.get("WavePeriod"), # Assuming this is PeakPeriod from index.html
                "MeanDirection": last_row.get("MeanWaveDirection"),
                # "SurfaceTemperature": last_row.get("SurfaceTemperature"), // This line is removed
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_ais_summary(ais_df, max_age_hours=24):
    # Preprocessor ensures "LastSeenTimestamp" is datetime64[ns, UTC] or df is empty
    # It also handles copying.
    df_ais_processed = preprocess_ais_df(ais_df if ais_df is not None else pd.DataFrame())
    if df_ais_processed.empty:
        return []

    # Timestamps in df_ais_processed["LastSeenTimestamp"] are UTC datetime objects.
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    
    # Direct comparison with UTC datetime objects
    recent = df_ais_processed[df_ais_processed["LastSeenTimestamp"] > cutoff_time]
    if recent.empty:
        return []
    
    # MMSI is Int64 or pd.NA from processor.
    if "MMSI" not in recent.columns or recent["MMSI"].isna().all(): # Use .isna() for nullable integers
        logger.debug("AIS summary: No recent vessels with valid MMSI found.")
    
     # Get the latest record for each MMSI, dropping rows where MMSI is NA before grouping
    latest_by_mmsi = recent.dropna(subset=["MMSI"]).sort_values("LastSeenTimestamp", ascending=False).groupby("MMSI").first().reset_index()
    vessels = []
    for _, row in latest_by_mmsi.iterrows():
        vessel = {
            "ShipName": row.get("ShipName", "Unknown"),
            "MMSI": int(row["MMSI"]) if pd.notna(row["MMSI"]) else None, # Convert Int64 to standard int or None
            "SpeedOverGround": row.get("SpeedOverGround"),
            "CourseOverGround": row.get("CourseOverGround"),
            "LastSeenTimestamp": row["LastSeenTimestamp"] # This is already a datetime object
        }
        vessels.append(vessel)
    return sorted(vessels, key=lambda v: v["LastSeenTimestamp"], reverse=True)

def get_recent_errors(error_df, max_age_hours=24):
     # Preprocessor ensures "Timestamp" is datetime64[ns, UTC] or df is empty
    df_error_processed = preprocess_error_df(error_df if error_df is not None else pd.DataFrame())
    if df_error_processed.empty:
        return []

    # Timestamps in df_error_processed["Timestamp"] are UTC datetime objects.
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    recent = df_error_processed[df_error_processed["Timestamp"] > cutoff_time]
    if recent.empty:
        return []

    # Processor ensures expected columns exist.
    # Timestamps will be pd.Timestamp objects (UTC). API layer might format them if needed.
    return recent.sort_values("Timestamp", ascending=False).to_dict(orient="records")




def get_vr2c_status(df_vr2c: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_vr2c is None or df_vr2c.empty:
        return result_shell

    try:
        df_vr2c_processed = preprocess_vr2c_df(df_vr2c)
    except Exception as e:
        logger.warning(f"Error preprocessing VR2C data for summary: {e}")
        return result_shell

    # df_vr2c_processed has UTC timestamps in "Timestamp" or is empty.
    if not df_vr2c_processed.empty: # "Timestamp" column is guaranteed
            logger.info(f"VR2C Summary: df_vr2c_processed head before selecting last_row:\n{df_vr2c_processed[['Timestamp', 'SerialNumber', 'DetectionCount', 'PingCount']].head()}")
            logger.info(f"VR2C Summary: df_vr2c_processed tail before selecting last_row:\n{df_vr2c_processed[['Timestamp', 'SerialNumber', 'DetectionCount', 'PingCount']].tail()}")

            latest_timestamp_obj = df_vr2c_processed["Timestamp"].max()
            if pd.notna(latest_timestamp_obj):
                result_shell["latest_timestamp_str"] = latest_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                result_shell["time_ago_str"] = time_ago(latest_timestamp_obj)

            last_row = df_vr2c_processed.loc[df_vr2c_processed["Timestamp"].idxmax()]
            logger.info(f"VR2C Summary: last_row content:\n{last_row}")
            
            result_shell["values"] = {
                "SerialNumber": last_row.get("SerialNumber"),
                "DetectionCount": last_row.get("DetectionCount"),
                "PingCount": last_row.get("PingCount"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell


    