import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from .processors import ( # type: ignore
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df, preprocess_vr2c_df,
    preprocess_fluorometer_df
)
from . import utils # Import the utils module
from typing import Optional, List, Dict, Any
import logging
import httpx

#MINI_TREND_POINTS = 30 # Number of data points for mini-trend graphs
BATTERY_MAX_WH = 2775.0 # MAX BATTERY, ASSUMES 1CCU AND 2APU EACH AT 925WATTHOUR

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



def get_power_status(df_power: Optional[pd.DataFrame], df_solar: Optional[pd.DataFrame] = None) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"} # Add Panel Powers
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
            update_info = utils.get_df_latest_update_info(df_power_processed, "Timestamp")
            result_shell.update(update_info) # Adds 'latest_timestamp_str' and 'time_ago_str'
            last_row = df_power_processed.loc[df_power_processed["Timestamp"].idxmax()]

            battery_wh = last_row.get("BatteryWattHours")
            battery_percentage = None
            logger.info(f"PowerSummaryDebug: Initial battery_wh = {battery_wh}, type = {type(battery_wh)}")
            if battery_wh is not None and pd.notna(battery_wh):
                logger.info(f"PowerSummaryDebug: Condition met for battery_wh = {battery_wh}")
                try:
                    battery_percentage_calculated = (float(battery_wh) / BATTERY_MAX_WH) * 100
                    battery_percentage = max(0, min(battery_percentage_calculated, 100))
                    logger.info(f"PowerSummaryDebug: Calculated battery_percentage = {battery_percentage}")
                except (ValueError, TypeError) as e_calc:
                    logger.warning(f"PowerSummaryDebug: Could not calculate battery percentage for value: {battery_wh}. Error: {e_calc}")
            else:
                logger.info(f"PowerSummaryDebug: Condition NOT met for battery_wh = {battery_wh}. pd.notna(battery_wh) is {pd.notna(battery_wh)}")

            # Initialize panel power values
            panel1_power = None
            panel2_power = None
            panel4_power = None

            if df_solar is not None and not df_solar.empty:
                try:
                    # Assuming preprocess_solar_df is available and imported
                    from .processors import preprocess_solar_df # Ensure import
                    df_solar_processed = preprocess_solar_df(df_solar)
                    if not df_solar_processed.empty and "Timestamp" in df_solar_processed.columns:
                        # Find solar data closest to the power data's last_row timestamp
                        # Using merge_asof for robust closest timestamp matching
                        df_power_ts = pd.DataFrame({'Timestamp': [last_row["Timestamp"]]})
                        merged_df = pd.merge_asof(
                            df_power_ts.sort_values('Timestamp'),
                            df_solar_processed.sort_values('Timestamp'),
                            on='Timestamp',
                            direction='nearest', # Find nearest, or 'backward' for latest not after
                            tolerance=pd.Timedelta(hours=1) # Optional: only consider if within 1 hour
                        )
                        if not merged_df.empty and not merged_df.iloc[0].isnull().all():
                            last_solar_row = merged_df.iloc[0]
                            panel1_power = last_solar_row.get("Panel1Power")
                            panel2_power = last_solar_row.get("Panel2Power") # from panelPower3
                            panel4_power = last_solar_row.get("Panel4Power")
                except Exception as e_solar:
                    logger.warning(f"Error processing solar data for power summary: {e_solar}")

            result_shell["values"] = {
                "BatteryWattHours": battery_wh,
                "SolarInputWatts": last_row.get("SolarInputWatts"),
                "BatteryPercentage": battery_percentage, # Add the calculated percentage
                "PowerDrawWatts": last_row.get("PowerDrawWatts"), # Keep existing
                "NetPowerWatts": last_row.get("NetPowerWatts"),   # Keep existing
                "Panel1Power": panel1_power,
                "Panel2Power": panel2_power,
                "Panel4Power": panel4_power,
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A" # type: ignore
            }
    return result_shell

def get_power_mini_trend(df_power: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    logger.debug(f"get_power_mini_trend called. df_power is None: {df_power is None}, df_power is empty: {df_power.empty if df_power is not None else 'N/A'}")
    if df_power is None or df_power.empty:
        return []
    try:
        df_processed = preprocess_power_df(df_power)
        logger.debug(f"get_power_mini_trend: df_processed is empty: {df_processed.empty}")
        if not df_processed.empty:
            logger.debug(f"get_power_mini_trend: df_processed columns: {df_processed.columns.tolist()}")
            logger.debug(f"get_power_mini_trend: 'Timestamp' in df_processed: {'Timestamp' in df_processed.columns}")
            logger.debug(f"get_power_mini_trend: 'NetPowerWatts' in df_processed: {'NetPowerWatts' in df_processed.columns}")
            if "NetPowerWatts" in df_processed.columns:
                logger.debug(f"get_power_mini_trend: NetPowerWatts head(5):\n{df_processed['NetPowerWatts'].head()}")

        if df_processed.empty or "Timestamp" not in df_processed.columns or "NetPowerWatts" not in df_processed.columns:
            logger.debug("get_power_mini_trend: Preconditions for trend data not met (empty, or missing Timestamp/NetPowerWatts). Returning [].")
            return []

        # Determine the 3-hour window
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            logger.debug("get_power_mini_trend: Max timestamp is NaT. Returning [].")
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) # 24hrs for power
        
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")
        
        logger.debug(f"get_power_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")
        
        # Format for charting
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row["NetPowerWatts"]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row["NetPowerWatts"]
                })
        logger.debug(f"get_power_mini_trend: Generated trend_data (length {len(trend_data)}): {str(trend_data[:5])[:200]}...") # Log first 5 points, truncated
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating power mini-trend: {e}", exc_info=True)
        return []

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
            update_info = utils.get_df_latest_update_info(df_fluorometer_processed, "Timestamp")
            result_shell.update(update_info)
            # The logging for head/tail can remain if useful for debugging specific sensor data
            logger.info(f"Fluorometer Summary: df_fluorometer_processed head before selecting last_row:\n{df_fluorometer_processed[['Timestamp', 'C1_Avg', 'C2_Avg', 'C3_Avg', 'Temperature_Fluor']].head()}")
            logger.info(f"Fluorometer Summary: df_fluorometer_processed tail before selecting last_row:\n{df_fluorometer_processed[['Timestamp', 'C1_Avg', 'C2_Avg', 'C3_Avg', 'Temperature_Fluor']].tail()}")
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

def get_fluorometer_mini_trend(df_fluorometer: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_fluorometer is None or df_fluorometer.empty:
        return []
    try:
        df_processed = preprocess_fluorometer_df(df_fluorometer)
        # Using C1_Avg as the primary metric for the mini trend
        metric_col = "C1_Avg" 
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []
        
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) # 24hrs for chl
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        logger.debug(f"get_fluorometer_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")

        trend_data = []
        
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating fluorometer mini-trend: {e}")
        return []

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
            update_info = utils.get_df_latest_update_info(df_ctd_processed, "Timestamp")
            result_shell.update(update_info)
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

def get_ctd_mini_trend(df_ctd: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_ctd is None or df_ctd.empty:
        return []
    try:
        df_processed = preprocess_ctd_df(df_ctd)
        metric_col = "WaterTemperature" # Primary metric for CTD mini trend
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []
        
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) # 24hrs for ctd
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        logger.debug(f"get_ctd_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")

        
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating CTD mini-trend: {e}")
        return []

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
            update_info = utils.get_df_latest_update_info(df_weather_processed, "Timestamp")
            result_shell.update(update_info)
            last_row = df_weather_processed.loc[df_weather_processed["Timestamp"].idxmax()]
            
            result_shell["values"] = {
                "AirTemperature": last_row.get("AirTemperature"),
                "WindSpeed": last_row.get("WindSpeed"),
                "WindGust": last_row.get("WindGust"),
                "WindDirection": last_row.get("WindDirection"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_weather_mini_trend(df_weather: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_weather is None or df_weather.empty:
        return []
    try:
        df_processed = preprocess_weather_df(df_weather)
        metric_col = "WindSpeed" # Primary metric for Weather mini trend
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []
        
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) # 24hrs for weather
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        logger.debug(f"get_weather_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")

        
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating weather mini-trend: {e}")
        return []

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
            update_info = utils.get_df_latest_update_info(df_waves_processed, "Timestamp")
            result_shell.update(update_info)
            last_row = df_waves_processed.loc[df_waves_processed["Timestamp"].idxmax()]
            
            result_shell["values"] = {
                "SignificantWaveHeight": last_row.get("SignificantWaveHeight"),
                "WavePeriod": last_row.get("WavePeriod"), # Assuming this is PeakPeriod from index.html
                "MeanDirection": last_row.get("MeanWaveDirection"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_wave_mini_trend(df_waves: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_waves is None or df_waves.empty:
        return []
    try:
        df_processed = preprocess_wave_df(df_waves)
        metric_col = "SignificantWaveHeight" # Primary metric for Wave mini trend
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []
        
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=48) #48hrs for waves
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        logger.debug(f"get_wave_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")

        
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating wave mini-trend: {e}")
        return []

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
            update_info = utils.get_df_latest_update_info(df_vr2c_processed, "Timestamp")
            result_shell.update(update_info)
            logger.info(f"VR2C Summary: df_vr2c_processed head before selecting last_row:\n{df_vr2c_processed[['Timestamp', 'SerialNumber', 'DetectionCount', 'PingCount']].head()}")
            logger.info(f"VR2C Summary: df_vr2c_processed tail before selecting last_row:\n{df_vr2c_processed[['Timestamp', 'SerialNumber', 'DetectionCount', 'PingCount']].tail()}")
            last_row = df_vr2c_processed.loc[df_vr2c_processed["Timestamp"].idxmax()]
            logger.info(f"VR2C Summary: last_row content:\n{last_row}")
            
            result_shell["values"] = {
                "SerialNumber": last_row.get("SerialNumber"),
                "DetectionCount": last_row.get("DetectionCount"),
                "PingCount": last_row.get("PingCount"),
                "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
            }
    return result_shell

def get_vr2c_mini_trend(df_vr2c: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_vr2c is None or df_vr2c.empty:
        return []
    try:
        df_processed = preprocess_vr2c_df(df_vr2c)
        metric_col = "DetectionCount" # Primary metric for VR2C mini trend
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []
        
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) #24hrs for vr2c
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        logger.debug(f"get_vr2c_mini_trend: df_trend shape after 3-hour filter: {df_trend.shape}")

        
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating VR2C mini-trend: {e}")
        return []


    

    