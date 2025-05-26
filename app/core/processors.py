import pandas as pd
import numpy as np
import logging # Add logging

logger = logging.getLogger(__name__) # Get a logger for this module

def standardize_timestamp_column(df: pd.DataFrame, preferred: str = "Timestamp") -> pd.DataFrame:
    """Renames the first found common timestamp column"""
    if df.empty:
        return df
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in ["timeStamp", "gliderTimeStamp", "lastLocationFix"]:
            # logger.debug(f"Standardized timestamp column: '{col}' to '{preferred}'.")
            df = df.rename(columns={col: preferred})
            return df
    # logger.debug(f"No standardizable timestamp column found for preferred name '{preferred}'. Columns: {df.columns.tolist()}")
    return df

def _initial_dataframe_setup(df: pd.DataFrame, target_timestamp_col: str) -> pd.DataFrame:
    """
    Handles initial DataFrame checks, timestamp standardization, conversion to UTC, and NaT removal.
    Works on a copy of the input DataFrame.
    Returns an empty DataFrame if input is invalid or processing results in an empty DataFrame.
    """
    if df is None or df.empty:
        # logger.debug(f"Input DataFrame for '{target_timestamp_col}' processing is None or empty.")
        return pd.DataFrame()

    df_processed = df.copy() # Work on a copy to avoid modifying the original DataFrame
    df_processed = standardize_timestamp_column(df_processed, preferred=target_timestamp_col)

    if target_timestamp_col not in df_processed.columns:
        logger.warning(f"Timestamp column '{target_timestamp_col}' not found after standardization for '{target_timestamp_col}' type. Cannot proceed. Columns: {df_processed.columns.tolist()}")
        return pd.DataFrame() # Return empty if timestamp column is essential and not found

    df_processed[target_timestamp_col] = pd.to_datetime(df_processed[target_timestamp_col], errors='coerce', utc=True)
    df_processed = df_processed.dropna(subset=[target_timestamp_col])

    # if df_processed.empty:
        # logger.debug(f"DataFrame became empty after timestamp processing for '{target_timestamp_col}'.")
    return df_processed

def preprocess_power_df(df):
    # The initial checks and timestamp processing are handled by _initial_dataframe_setup
    # df parameter to _initial_dataframe_setup should be the original df from the loader.

    df_processed = _initial_dataframe_setup(df, "Timestamp")
    if df_processed.empty:
        return df_processed

    transformations = [
        ("totalBatteryPower", "BatteryWattHours", 1000),
        ("solarPowerGenerated", "SolarInputWatts", 1000),
        ("outputPortPower", "PowerDrawWatts", 1000)
    ]

    for old_name, new_name, divisor in transformations:
        if old_name in df_processed.columns:
            df_processed[new_name] = pd.to_numeric(df_processed[old_name], errors='coerce') / divisor
            if old_name != new_name and old_name in df_processed.columns: # Check existence before drop
                df_processed = df_processed.drop(columns=[old_name], errors='ignore')
        elif new_name not in df_processed.columns : # Ensure new_name column exists if old_name wasn't there
             df_processed[new_name] = np.nan

    # Handle battery_charging_power_w
    # The raw column from AMPS data is typically 'batteryChargingPower'
    raw_battery_charge_col = 'batteryChargingPower'
    target_battery_charge_col = 'battery_charging_power_w'
    if raw_battery_charge_col in df_processed.columns:
        df_processed[target_battery_charge_col] = pd.to_numeric(df_processed[raw_battery_charge_col], errors='coerce') / 1000.0 # Convert mW to W
        # Optionally drop the raw column if it's different and not needed elsewhere,
        # but ensure it's not one of the columns already processed in transformations.
        if raw_battery_charge_col != target_battery_charge_col and raw_battery_charge_col not in [t[0] for t in transformations if t[1] == raw_battery_charge_col]:
            df_processed = df_processed.drop(columns=[raw_battery_charge_col], errors='ignore')
    elif target_battery_charge_col not in df_processed.columns: # If raw wasn't there, ensure target exists as NaN
        df_processed[target_battery_charge_col] = np.nan

    # Handle output_port_power_w
    # This should be the same data as PowerDrawWatts, which was derived from the raw 'outputPortPower'
    target_output_power_col = 'output_port_power_w'
    if 'PowerDrawWatts' in df_processed.columns:
        df_processed[target_output_power_col] = df_processed['PowerDrawWatts'] # Already numeric
    elif target_output_power_col not in df_processed.columns:
        df_processed[target_output_power_col] = np.nan

    # Calculate NetPowerWatts safely
    solar_watts = pd.to_numeric(df_processed.get("SolarInputWatts"), errors='coerce')
    power_draw = pd.to_numeric(df_processed.get("PowerDrawWatts"), errors='coerce')

    # Check if original columns for calculation existed to decide if NetPower can be calculated
    if "SolarInputWatts" in df_processed.columns and "PowerDrawWatts" in df_processed.columns:
        df_processed["NetPowerWatts"] = solar_watts - power_draw
    else:
        df_processed["NetPowerWatts"] = np.nan

    expected_cols = ["Timestamp", "BatteryWattHours", "SolarInputWatts", "PowerDrawWatts", "NetPowerWatts",
                     target_battery_charge_col, target_output_power_col]
    for col in expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = np.nan
    return df_processed

def preprocess_ctd_df(df):
    timestamp_col = "Timestamp"
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        return df_processed

    rename_map = {
        'temperature (degC)': 'WaterTemperature',
        'salinity (PSU)': 'Salinity',
        'conductivity (S/m)': 'Conductivity',
        'oxygen (freq)': 'DissolvedOxygen',
        'pressure (dbar)': 'Pressure',
    }
    df_processed = df_processed.rename(columns=rename_map)
    
    expected_final_cols = [timestamp_col] + list(rename_map.values())
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            df_processed[target_col] = np.nan
        elif target_col != timestamp_col: # Convert data columns to numeric
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
    return df_processed

def preprocess_weather_df(df):
    timestamp_col = "Timestamp"
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        return df_processed

    rename_map = {
        "avgTemp(C)": "AirTemperature",
        "avgWindSpeed(kt)": "WindSpeed",
        "gustSpeed(kt)": "WindGust",
        "avgWindDir(deg)": "WindDirection",
        "avgPress(mbar)": "BarometricPressure", # Changed to use avgPress(mbar) from CSV
    }
    df_processed = df_processed.rename(columns=rename_map)

    expected_final_cols = [timestamp_col] + list(rename_map.values())
    
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            df_processed[target_col] = np.nan
        elif target_col != timestamp_col:
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
    return df_processed

def preprocess_wave_df(df):
    timestamp_col = "Timestamp"
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        return df_processed

    rename_map = {
        "hs (m)": "SignificantWaveHeight",
        "tp (s)": "WavePeriod",
        "dp (deg)": "MeanWaveDirection",
        "sample Gaps": "SampleGaps", # Corrected to match CSV header "sample Gaps"
    }
    df_processed = df_processed.rename(columns=rename_map)

    expected_final_cols = [timestamp_col] + list(rename_map.values())
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            df_processed[target_col] = np.nan
        elif target_col != timestamp_col:
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
    return df_processed

def preprocess_ais_df(df):
    timestamp_col = "LastSeenTimestamp"
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        return df_processed

    rename_map = {
        "shipName": "ShipName",
        "mmsi": "MMSI",
        "speedOverGround": "SpeedOverGround",
        "courseOverGround": "CourseOverGround",
    }
    df_processed = df_processed.rename(columns=rename_map)

    # Specific MMSI handling
    if "MMSI" in df_processed.columns:
        temp_mmsi_series = pd.to_numeric(df_processed["MMSI"], errors='coerce')
        if pd.api.types.is_float_dtype(temp_mmsi_series):
            not_whole_number_mask = temp_mmsi_series.notna() & (temp_mmsi_series != np.floor(temp_mmsi_series))
            temp_mmsi_series[not_whole_number_mask] = np.nan
        df_processed["MMSI"] = temp_mmsi_series.astype('Int64') # Use nullable integer type

    expected_final_cols = [timestamp_col] + list(rename_map.values())
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            if target_col == "MMSI":
                  df_processed[target_col] = pd.Series(dtype='Int64')
            else:
                df_processed[target_col] = np.nan
        elif target_col in ["SpeedOverGround", "CourseOverGround"]:
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
        # ShipName is string, MMSI is Int64, LastSeenTimestamp is datetime
    return df_processed

def preprocess_error_df(df):
    timestamp_col = "Timestamp"
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        return df_processed

    rename_map = {
        "vehicleName": "VehicleName",
        "selfCorrected": "SelfCorrected",
        "error_Message": "ErrorMessage",
    }
     # Handle potential space in "Error Message" from CSV
    if "Error Message" in df_processed.columns and "error_Message" not in df_processed.columns:
        df_processed = df_processed.rename(columns={"Error Message": "error_Message"})

    df_processed = df_processed.rename(columns=rename_map)

    expected_final_cols = [timestamp_col] + list(rename_map.values())
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            df_processed[target_col] = np.nan
        # VehicleName, ErrorMessage are likely strings.
        # SelfCorrected could be boolean-like; convert if necessary, e.g.:
        # elif target_col == "SelfCorrected":
        #     df_processed[target_col] = df_processed[target_col].astype(bool) # Or map specific strings to bool
    return df_processed

def preprocess_vr2c_df(df):
    timestamp_col = "Timestamp"
    # logger.info(f"VR2C Preprocessing: Initial df columns: {df.columns.tolist()}")
    
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        # Ensure even an empty DF from initial setup has the expected columns if it's returned early
        for col in [timestamp_col, 'SerialNumber', 'DetectionCount', 'PingCount']:
            if col not in df_processed.columns:
                 df_processed[col] = np.nan if col != timestamp_col else pd.Series(dtype='datetime64[ns, UTC]')
        return df_processed

    # Ensure 'status String' column exists
    if 'status String' not in df_processed.columns:
        logger.warning("VR2C Preprocessing: 'status String' column not found.")
        df_processed['SerialNumber'] = np.nan # Can be object/string
        df_processed['DetectionCount'] = np.nan # Numeric
        df_processed['PingCount'] = np.nan # Numeric
    else:
        # Function to parse the status string
        def parse_status_string(status_str):
            if pd.isna(status_str):
                return pd.Series([np.nan, np.nan, np.nan], index=['SerialNumber', 'DetectionCount', 'PingCount'])
            
            parts = str(status_str).split(',')
            serial = parts[0].strip() if len(parts) > 0 else np.nan
            dc_str = next((p.split('=')[1].strip() for p in parts if 'DC=' in p), np.nan)
            pc_str = next((p.split('=')[1].strip() for p in parts if 'PC=' in p), np.nan)
            
            dc = pd.to_numeric(dc_str, errors='coerce')
            pc = pd.to_numeric(pc_str, errors='coerce')
            return pd.Series([serial, dc, pc], index=['SerialNumber', 'DetectionCount', 'PingCount'])
        
        # Apply the parsing function
        parsed_data = df_processed['status String'].apply(parse_status_string)
        # logger.info(f"VR2C Preprocessing: Parsed data from 'status String' (first 5 rows):\n{parsed_data.head()}")
        df_processed = pd.concat([df_processed, parsed_data], axis=1)

        # Ensure types after parsing and concat
        df_processed['DetectionCount'] = pd.to_numeric(df_processed.get('DetectionCount'), errors='coerce')
        df_processed['PingCount'] = pd.to_numeric(df_processed.get('PingCount'), errors='coerce')
        # logger.info(f"VR2C Preprocessing: After to_numeric (first 5 rows of DC, PC):\nDetectionCount:\n{df_processed['DetectionCount'].head()}\nPingCount:\n{df_processed['PingCount'].head()}")
        
        if 'SerialNumber' in df_processed.columns and df_processed['SerialNumber'].dtype == float and df_processed['SerialNumber'].isna().all():
            logger.warning("VR2C Preprocessing: SerialNumber column is all NaN after parsing.")
        # SerialNumber can remain as object/string

    # Ensure all expected columns are present
    expected_cols = [timestamp_col, 'SerialNumber', 'DetectionCount', 'PingCount']
    for col in expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = np.nan # Default to NaN, specific types handled above/below
            if col == 'DetectionCount' or col == 'PingCount':
                df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
            
    return df_processed

def preprocess_fluorometer_df(df):
    timestamp_col = "Timestamp"
    # logger.info(f"Fluorometer Preprocessing: Initial df columns: {df.columns.tolist()}")

    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        # Ensure even an empty DF from initial setup has the expected columns
        for col in [timestamp_col, "Latitude", "Longitude", "C1_Avg", "C2_Avg", "C3_Avg", "Temperature_Fluor"]:
            if col not in df_processed.columns:
                df_processed[col] = np.nan if col != timestamp_col else pd.Series(dtype='datetime64[ns, UTC]')
        return df_processed
    rename_map = {
        "latitude": "Latitude", # Standardize capitalization
        "longitude": "Longitude", # Standardize capitalization
        "c1Avg": "C1_Avg",
        "c2Avg": "C2_Avg",
        "c3Avg": "C3_Avg",
        "temp": "Temperature_Fluor" # To avoid conflict with other temp sensors if any
    }
    df_processed = df_processed.rename(columns=rename_map)
    # logger.info(f"Fluorometer Preprocessing: df columns after rename: {df_processed.columns.tolist()}")

    # Ensure all target columns exist, fill with NaN if not, and convert to numeric
    expected_final_cols = [timestamp_col, "Latitude", "Longitude", "C1_Avg", "C2_Avg", "C3_Avg", "Temperature_Fluor"]
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            logger.warning(f"Fluorometer Preprocessing: Target column '{target_col}' not found after rename. Adding as NaN.")
            df_processed[target_col] = np.nan
        
        if target_col != timestamp_col: # Convert data columns to numeric
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
            
    # logger.info(f"Fluorometer Preprocessing: After to_numeric (first 5 rows of C1_Avg, Temp):\nC1_Avg:\n{df_processed['C1_Avg'].head() if 'C1_Avg' in df_processed.columns else 'N/A'}\nTemperature_Fluor:\n{df_processed['Temperature_Fluor'].head() if 'Temperature_Fluor' in df_processed.columns else 'N/A'}")
    return df_processed

def preprocess_solar_df(df: pd.DataFrame) -> pd.DataFrame:
    timestamp_col = "Timestamp" # Standardized name
    # Note: The raw CSV uses "timeStamp" which _initial_dataframe_setup will handle
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        # Ensure even an empty DF has the expected columns
        for col in [timestamp_col, "Panel1Power", "Panel2Power", "Panel4Power"]: # Panel3Power is intentionally Panel2Power
            if col not in df_processed.columns:
                 df_processed[col] = np.nan if col != timestamp_col else pd.Series(dtype='datetime64[ns, UTC]')
        return df_processed

    rename_map = {
        "panelPower1": "Panel1Power",
        "panelPower3": "Panel2Power", # As per request: panelPower3 is labeled Panel 2
        "panelPower4": "Panel4Power"
    }
    df_processed = df_processed.rename(columns=rename_map)

    expected_final_cols = [timestamp_col, "Panel1Power", "Panel2Power", "Panel4Power"]
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            df_processed[target_col] = np.nan
        elif target_col != timestamp_col: # Convert data columns to numeric
            df_processed[target_col] = pd.to_numeric(df_processed[target_col], errors='coerce')
    return df_processed