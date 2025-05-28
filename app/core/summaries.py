import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from .processors import ( # type: ignore
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df, preprocess_vr2c_df, # type: ignore
    preprocess_fluorometer_df, preprocess_telemetry_df # type: ignore
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
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_power is None or df_power.empty:
        return result_shell

    try:
        # Processor now handles copying and ensures UTC timestamps
        df_power_processed = preprocess_power_df(df_power) 
    except Exception as e:
        logger.warning(f"Error preprocessing power data for summary: {e}")
        return result_shell

    if not df_power_processed.empty: # "Timestamp" column is guaranteed if not empty
            update_info = utils.get_df_latest_update_info(df_power_processed, "Timestamp")
            result_shell.update(update_info) # Adds 'latest_timestamp_str' and 'time_ago_str'
            last_row = df_power_processed.loc[df_power_processed["Timestamp"].idxmax()]
            df_last_24h = df_power_processed[df_power_processed['Timestamp'] > (last_row['Timestamp'] - pd.Timedelta(hours=24))]

            battery_wh = last_row.get("BatteryWattHours")
            battery_percentage = None
            if battery_wh is not None and pd.notna(battery_wh):
                try:
                    battery_percentage_calculated = (float(battery_wh) / BATTERY_MAX_WH) * 100
                    battery_percentage = max(0, min(battery_percentage_calculated, 100))
                except (ValueError, TypeError) as e_calc:
                    logger.warning(f"PowerSummaryDebug: Could not calculate battery percentage for value: {battery_wh}. Error: {e_calc}")
            else:
                logger.info(f"PowerSummaryDebug: Condition NOT met for battery_wh = {battery_wh}. pd.notna(battery_wh) is {pd.notna(battery_wh)}")

            # Get Battery Charge Rate (assuming 'battery_charging_power_w' column from processor)
            battery_charge_rate_w = last_row.get("battery_charging_power_w")

            # Calculate Time to Charge
            time_to_charge_str = "N/A"
            if battery_percentage is not None and pd.notna(battery_percentage) and \
               battery_charge_rate_w is not None and pd.notna(battery_charge_rate_w):
                if battery_charge_rate_w <= 0:
                    time_to_charge_str = "Discharging"
                    if battery_percentage < 10: # Example: 10% threshold
                        time_to_charge_str = "Low & Discharging"
                elif battery_percentage >= 99.5:  # Nearly full
                    time_to_charge_str = "Fully Charged"
                else:
                    energy_needed_wh = (1.0 - (battery_percentage / 100.0)) * BATTERY_MAX_WH
                    if energy_needed_wh < 0: energy_needed_wh = 0

                    if battery_charge_rate_w > 0:
                        time_hours_decimal = energy_needed_wh / battery_charge_rate_w
                        if time_hours_decimal > 200:
                            time_to_charge_str = ">200h"
                        elif time_hours_decimal < 0.0167 and energy_needed_wh > 0:
                            time_to_charge_str = "<1m"
                        elif time_hours_decimal == 0 and energy_needed_wh == 0 and battery_percentage < 99.5:
                            time_to_charge_str = "Stalled"
                        else:
                            hours = int(time_hours_decimal)
                            minutes = int((time_hours_decimal * 60) % 60)
                            time_to_charge_str = f"{hours}h {minutes}m"
                    elif battery_charge_rate_w == 0 and battery_percentage < 99.5:
                        time_to_charge_str = "Stalled (0W)"


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

            # Calculate 24-hour averages
            avg_output_port_power_24hr_w = df_last_24h['output_port_power_w'].mean() if not df_last_24h.empty and 'output_port_power_w' in df_last_24h else None
            avg_solar_input_24hr_w = df_last_24h['SolarInputWatts'].mean() if not df_last_24h.empty and 'SolarInputWatts' in df_last_24h else None


            result_shell["values"] = {
                "BatteryWattHours": battery_wh,
                "SolarInputWatts": last_row.get("SolarInputWatts"),
                "BatteryPercentage": battery_percentage,
                "PowerDrawWatts": last_row.get("PowerDrawWatts"),
                "NetPowerWatts": last_row.get("NetPowerWatts"),
                "BatteryChargeRateW": battery_charge_rate_w,
                "TimeToChargeStr": time_to_charge_str,
                "AvgOutputPortPower24hrW": avg_output_port_power_24hr_w,
                "AvgSolarInput24hrW": avg_solar_input_24hr_w,
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
            # We will now use 'battery_charging_power_w' for the trend
            metric_for_trend = "battery_charging_power_w"
            if metric_for_trend in df_processed.columns:
                pass # logger.debug(f"get_power_mini_trend: {metric_for_trend} head(5):\n{df_processed[metric_for_trend].head()}")

        if df_processed.empty or \
           "Timestamp" not in df_processed.columns or \
           "battery_charging_power_w" not in df_processed.columns:
            logger.debug(f"get_power_mini_trend: Preconditions for trend data not met (empty, or missing Timestamp/{metric_for_trend}). Returning [].")
            return []

        # Determine the 24-hour window for power mini-trend
        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            logger.debug("get_power_mini_trend: Max timestamp is NaT. Returning [].")
            return []
        cutoff_time = max_timestamp - timedelta(hours=24)
        
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")
        
        # Format for charting
        trend_data = []
        for _, row in df_trend.iterrows():
            if pd.notna(row["Timestamp"]) and pd.notna(row["battery_charging_power_w"]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row["battery_charging_power_w"] # Use battery_charging_power_w for the trend value
                })
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
            last_row = df_fluorometer_processed.loc[df_fluorometer_processed["Timestamp"].idxmax()]
            
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

        if df_trend.empty:
            return []

        # Resample to 1-hour average for smoothing
        df_trend_resampled = df_trend.set_index("Timestamp")
        # Ensure the metric_col is numeric before resampling
        if pd.api.types.is_numeric_dtype(df_trend_resampled[metric_col]):
            df_trend_resampled = df_trend_resampled[[metric_col]].resample('1h').mean()
        else:
            logger.warning(f"Fluorometer mini-trend: '{metric_col}' is not numeric, cannot resample. Returning raw trend.")
            df_trend_resampled = df_trend_resampled[[metric_col]].reset_index()

        df_trend_resampled = df_trend_resampled.reset_index().dropna(subset=[metric_col])

        trend_data = []
        for _, row in df_trend_resampled.iterrows():
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

            # Calculate Highest and Lowest Water Temperature from the last 24 hours
            df_last_24h = df_ctd_processed[df_ctd_processed['Timestamp'] > (last_row['Timestamp'] - pd.Timedelta(hours=24))]
            highest_temp_24h = df_last_24h['WaterTemperature'].max() if not df_last_24h.empty and 'WaterTemperature' in df_last_24h else None
            lowest_temp_24h = df_last_24h['WaterTemperature'].min() if not df_last_24h.empty and 'WaterTemperature' in df_last_24h else None
            
            result_shell["values"] = {
                "WaterTemperature": last_row.get("WaterTemperature"),
                "Salinity": last_row.get("Salinity"),
                "Conductivity": last_row.get("Conductivity"),
                "DissolvedOxygen": last_row.get("DissolvedOxygen"),
                "Pressure": last_row.get("Pressure"),
                "HighestWaterTemperature24h": highest_temp_24h,
                "LowestWaterTemperature24h": lowest_temp_24h,
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
        
        if df_trend.empty:
            return []

        # Resample to 1-hour average for smoothing
        df_trend_resampled = df_trend.set_index("Timestamp")
        # Ensure the metric_col is numeric before resampling
        if pd.api.types.is_numeric_dtype(df_trend_resampled[metric_col]):
            df_trend_resampled = df_trend_resampled[[metric_col]].resample('1h').mean()
        else:
            logger.warning(f"CTD mini-trend: '{metric_col}' is not numeric, cannot resample. Returning raw trend.")
            # Fallback to non-resampled if not numeric, though it should be
            df_trend_resampled = df_trend_resampled[[metric_col]].reset_index() # Keep structure consistent

        df_trend_resampled = df_trend_resampled.reset_index().dropna(subset=[metric_col])

        trend_data = []
        for _, row in df_trend_resampled.iterrows():
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

            # Calculate 24-hour High/Low for AirTemperature and BarometricPressure
            df_last_24h = df_weather_processed[df_weather_processed['Timestamp'] > (last_row['Timestamp'] - pd.Timedelta(hours=24))]
            
            air_temp_high_24h = df_last_24h['AirTemperature'].max() if not df_last_24h.empty and 'AirTemperature' in df_last_24h else None
            air_temp_low_24h = df_last_24h['AirTemperature'].min() if not df_last_24h.empty and 'AirTemperature' in df_last_24h else None
            
            pressure_high_24h = df_last_24h['BarometricPressure'].max() if not df_last_24h.empty and 'BarometricPressure' in df_last_24h else None
            pressure_low_24h = df_last_24h['BarometricPressure'].min() if not df_last_24h.empty and 'BarometricPressure' in df_last_24h else None
            
            result_shell["values"] = {
                "AirTemperature": last_row.get("AirTemperature"),
                "WindSpeed": last_row.get("WindSpeed"),
                "WindGust": last_row.get("WindGust"),
                "WindDirection": last_row.get("WindDirection"),
                # GustDirection will use WindDirection as per current processing
                "GustDirection": last_row.get("WindDirection"), 
                "BarometricPressure": last_row.get("BarometricPressure"),
                "AirTemperatureHigh24h": air_temp_high_24h,
                "AirTemperatureLow24h": air_temp_low_24h,
                "PressureHigh24h": pressure_high_24h,
                "PressureLow24h": pressure_low_24h,
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
        
        if df_trend.empty:
            return []

        # Resample to 1-hour average for smoothing
        df_trend_resampled = df_trend.set_index("Timestamp")
        # Ensure the metric_col is numeric before resampling
        if pd.api.types.is_numeric_dtype(df_trend_resampled[metric_col]):
            df_trend_resampled = df_trend_resampled[[metric_col]].resample('1h').mean()
        else:
            logger.warning(f"Weather mini-trend: '{metric_col}' is not numeric, cannot resample. Returning raw trend.")
            df_trend_resampled = df_trend_resampled[[metric_col]].reset_index() 

        df_trend_resampled = df_trend_resampled.reset_index().dropna(subset=[metric_col])
        
        trend_data = []
        for _, row in df_trend_resampled.iterrows():
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

            # Calculate 24-hour average for SignificantWaveHeight
            df_last_24h = df_waves_processed[df_waves_processed['Timestamp'] > (last_row['Timestamp'] - pd.Timedelta(hours=24))]
            avg_wave_height_24h = df_last_24h['SignificantWaveHeight'].mean() if not df_last_24h.empty and 'SignificantWaveHeight' in df_last_24h else None

            # Calculate Wave Amplitude
            significant_wave_height = last_row.get("SignificantWaveHeight")
            wave_amplitude = (significant_wave_height / 2) if significant_wave_height is not None and pd.notna(significant_wave_height) else None
            
            # Filter MeanWaveDirection for outliers
            mean_direction_raw = last_row.get("MeanWaveDirection")
            mean_direction_display_value = "N/A" # Default display
            mean_direction_numeric_value = None # For potential numeric use if valid
            mean_direction_status = "missing" # Default status

            if pd.notna(mean_direction_raw):
                try:
                    val_as_int = int(mean_direction_raw)
                    if val_as_int == 9999 or val_as_int == -9999:
                        mean_direction_display_value = "N/A (Outlier)"
                        mean_direction_status = "outlier"
                    else:
                        mean_direction_display_value = f"{val_as_int:.0f} °" # Format valid number
                        mean_direction_numeric_value = val_as_int
                        mean_direction_status = "valid"
                except ValueError:
                    logger.warning(f"Could not convert MeanWaveDirection '{mean_direction_raw}' to int for outlier check.")
                    mean_direction_display_value = "N/A (Error)" # Indicate a parsing error
                    mean_direction_status = "error"

            result_shell["values"] = {
                "SignificantWaveHeight": significant_wave_height,
                "SignificantWaveHeightAvg24h": avg_wave_height_24h,
                "WavePeriod": last_row.get("WavePeriod"), # Assuming this is PeakPeriod from index.html
                "MeanDirectionDisplay": mean_direction_display_value, # Value for direct display
                "MeanDirectionNumeric": mean_direction_numeric_value, # Actual numeric value if valid, else None
                "MeanDirectionStatus": mean_direction_status, # Status: 'valid', 'outlier', 'missing', 'error'
                "WaveAmplitude": wave_amplitude,
                "SampleGaps": last_row.get("SampleGaps"),
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
        
        if df_trend.empty:
            return []

        # Resample to 1-hour average for smoothing
        df_trend_resampled = df_trend.set_index("Timestamp")
        # Ensure the metric_col is numeric before resampling
        if pd.api.types.is_numeric_dtype(df_trend_resampled[metric_col]):
            df_trend_resampled = df_trend_resampled[[metric_col]].resample('1h').mean()
        else:
            logger.warning(f"Wave mini-trend: '{metric_col}' is not numeric, cannot resample. Returning raw trend.")
            df_trend_resampled = df_trend_resampled[[metric_col]].reset_index()

        df_trend_resampled = df_trend_resampled.reset_index().dropna(subset=[metric_col])
        
        trend_data = []
        for _, row in df_trend_resampled.iterrows():
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
            last_row = df_vr2c_processed.loc[df_vr2c_processed["Timestamp"].idxmax()]
            
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

        if df_trend.empty:
            return []

        # Resample to 1-hour sum for DetectionCount (assuming DC represents discrete events per record)
        # Or .mean() if an average rate is more appropriate.
        df_trend_resampled = df_trend.set_index("Timestamp")
        if pd.api.types.is_numeric_dtype(df_trend_resampled[metric_col]):
            df_trend_resampled = df_trend_resampled[[metric_col]].resample('1h').sum() # Or .mean()
        else:
            logger.warning(f"VR2C mini-trend: '{metric_col}' is not numeric, cannot resample. Returning raw trend.")
            df_trend_resampled = df_trend_resampled[[metric_col]].reset_index()

        df_trend_resampled = df_trend_resampled.reset_index().dropna(subset=[metric_col])

        trend_data = []
        for _, row in df_trend_resampled.iterrows(): # Iterate over resampled data
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col]):
                trend_data.append({
                    "Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'),
                    "value": row[metric_col]
                })
        return trend_data
    except Exception as e:
        logger.warning(f"Error generating VR2C mini-trend: {e}")
        return []

def get_navigation_status(df_telemetry: Optional[pd.DataFrame]) -> Dict:
    result_shell: Dict[str, Any] = {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}
    if df_telemetry is None or df_telemetry.empty:
        return result_shell

    try:
        df_telemetry_processed = preprocess_telemetry_df(df_telemetry)
    except Exception as e:
        logger.warning(f"Error preprocessing Telemetry data for summary: {e}")
        return result_shell

    if not df_telemetry_processed.empty and "Timestamp" in df_telemetry_processed.columns:
        update_info = utils.get_df_latest_update_info(df_telemetry_processed, "Timestamp")
        result_shell.update(update_info)
        last_row = df_telemetry_processed.loc[df_telemetry_processed["Timestamp"].idxmax()]

        # Calculate 24-hour metrics
        df_last_24h = df_telemetry_processed[df_telemetry_processed['Timestamp'] > (last_row['Timestamp'] - pd.Timedelta(hours=24))]

        # Speed Over Ground metrics
        avg_sog_24h = df_last_24h['SpeedOverGround'].mean() if not df_last_24h.empty and 'SpeedOverGround' in df_last_24h.columns and pd.api.types.is_numeric_dtype(df_last_24h['SpeedOverGround']) else None
        
        # Distance Traveled metrics (using 'DistanceToWaypoint' which is processed 'gliderDistance')
        METERS_TO_NAUTICAL_MILES = 0.000539957

        total_distance_mission_meters = df_telemetry_processed['DistanceToWaypoint'].sum() if 'DistanceToWaypoint' in df_telemetry_processed.columns and pd.api.types.is_numeric_dtype(df_telemetry_processed['DistanceToWaypoint']) else 0
        distance_traveled_24h_meters = df_last_24h['DistanceToWaypoint'].sum() if not df_last_24h.empty and 'DistanceToWaypoint' in df_last_24h.columns and pd.api.types.is_numeric_dtype(df_last_24h['DistanceToWaypoint']) else 0

        total_distance_mission_nm = total_distance_mission_meters * METERS_TO_NAUTICAL_MILES if pd.notna(total_distance_mission_meters) else None
        distance_traveled_24h_nm = distance_traveled_24h_meters * METERS_TO_NAUTICAL_MILES if pd.notna(distance_traveled_24h_meters) else None



        result_shell["values"] = {
            "Latitude": last_row.get("Latitude"),
            "Longitude": last_row.get("Longitude"),
            "GliderHeading": last_row.get("GliderHeading"), # Use 'gliderHeading' (processed to GliderHeading)
            "SpeedOverGround": last_row.get("SpeedOverGround"),
            "AvgSpeedOverGround24h": avg_sog_24h, # 24hr average of SOG
            # "TargetWaypoint": last_row.get("TargetWaypoint"), # Removed from direct display per request
            # "DistanceToWaypoint": last_row.get("DistanceToWaypoint"), # This is the *last segment* distance, not what we want for summary here
            
            "TotalDistanceTraveledMissionNM": total_distance_mission_nm, # In Nautical Miles
            "DistanceTraveled24hNM": distance_traveled_24h_nm, # In Nautical Miles
            
            "OceanCurrentSpeed": last_row.get("OceanCurrentSpeed"),
            "OceanCurrentDirection": last_row.get("OceanCurrentDirection"),
            "Timestamp": last_row["Timestamp"].strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(last_row.get("Timestamp")) else "N/A"
        }
    return result_shell

def get_navigation_mini_trend(df_telemetry: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df_telemetry is None or df_telemetry.empty:
        return []
    try:
        df_processed = preprocess_telemetry_df(df_telemetry)
        metric_col = "GliderSpeed" # Primary metric for Navigation mini trend
        if df_processed.empty or "Timestamp" not in df_processed.columns or metric_col not in df_processed.columns:
            return []

        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []
        cutoff_time = max_timestamp - timedelta(hours=24) # 24hrs for navigation trend
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(by="Timestamp")

        if df_trend.empty: return []

        df_trend_resampled = df_trend.set_index("Timestamp")[[metric_col]].resample('1h').mean().reset_index().dropna(subset=[metric_col])

        return [{"Timestamp": row["Timestamp"].strftime('%Y-%m-%dT%H:%M:%S'), "value": row[metric_col]}
                for _, row in df_trend_resampled.iterrows() if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col])]
    except Exception as e:
        logger.warning(f"Error generating navigation mini-trend: {e}")
        return []
    

    