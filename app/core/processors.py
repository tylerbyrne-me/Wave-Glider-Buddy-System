import logging  # Add logging
from typing import Dict, List
 
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)  # Get a logger for this module


def standardize_timestamp_column(
    df: pd.DataFrame, preferred: str = "Timestamp"
) -> pd.DataFrame:
    """Renames the first found common timestamp column"""
    if df.empty:
        return df
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in [
            "timeStamp",
            "gliderTimeStamp",
            "lastLocationFix",
        ]:
            # logger.debug(f"Standardized timestamp column: '{col}' to '{preferred}'.")
            df = df.rename(columns={col: preferred})
            return df
    # logger.debug(
    # f"No standardizable timestamp column found for preferred name
    # '{preferred}'. Columns: {df.columns.tolist()}"
    # )
    return df


def _initial_dataframe_setup(
    df: pd.DataFrame, target_timestamp_col: str
) -> pd.DataFrame:
    """
    Handles initial DataFrame checks, timestamp standardization, conversion to UTC, and NaT removal.
    Works on a copy of the input DataFrame.
    Returns an empty DataFrame if input is invalid or processing results in an empty DataFrame.
    """
    if df is None or df.empty:
        # logger.debug(
        #     f"Input DataFrame for '{target_timestamp_col}' processing is None or empty."
        # )
        return pd.DataFrame()

    df_processed = df.copy()  # Work on a copy to avoid modifying the original DataFrame
    df_processed = standardize_timestamp_column(
        df_processed, preferred=target_timestamp_col
    )

    if target_timestamp_col not in df_processed.columns:
        logger.warning(
            f"Timestamp column '{target_timestamp_col}' not found after "
            f"standardization for '{target_timestamp_col}' type. Cannot proceed. Columns: {df_processed.columns.tolist()}"
        )
        return (
            pd.DataFrame()
        )  # Return empty if timestamp column is essential and not found

    df_processed[target_timestamp_col] = pd.to_datetime(
        df_processed[target_timestamp_col], errors="coerce", utc=True
    )
    df_processed = df_processed.dropna(subset=[target_timestamp_col])

    # if df_processed.empty:
    # logger.debug(
    #     f"DataFrame became empty after timestamp processing for '{target_timestamp_col}'."
    # )
    return df_processed

def _apply_common_processing(
    df: pd.DataFrame,
    timestamp_col: str,
    rename_map: Dict[str, str],
    numeric_cols: List[str],
) -> pd.DataFrame:
    """
    Applies a common sequence of preprocessing steps: timestamp setup, renaming, and numeric conversion.
    """
    df_processed = _initial_dataframe_setup(df, timestamp_col)
    if df_processed.empty:
        # To ensure schema consistency even for empty dataframes, add expected columns
        expected_cols = [timestamp_col] + list(rename_map.values())
        for col in expected_cols:
            if col not in df_processed.columns:
                if col == timestamp_col:
                    df_processed[col] = pd.Series(dtype="datetime64[ns, UTC]")
                else:
                    df_processed[col] = np.nan
        return df_processed

    df_processed = df_processed.rename(columns=rename_map)

    all_expected_cols = [timestamp_col] + list(rename_map.values())

    for col in all_expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = np.nan

        if col in numeric_cols:
            df_processed[col] = pd.to_numeric(
                df_processed[col], errors="coerce"
            )

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
        ("outputPortPower", "PowerDrawWatts", 1000),
    ]

    for old_name, new_name, divisor in transformations:
        if old_name in df_processed.columns:
            df_processed[new_name] = (
                pd.to_numeric(df_processed[old_name], errors="coerce") / divisor
            )
            if (
                old_name != new_name and old_name in df_processed.columns
            ):  # Check existence before drop
                df_processed = df_processed.drop(columns=[old_name], errors="ignore")
        elif (
            new_name not in df_processed.columns
        ):  # Ensure new_name column exists if old_name wasn't there
            df_processed[new_name] = np.nan

    # Handle battery_charging_power_w
    # The raw column from AMPS data is typically 'batteryChargingPower'
    raw_battery_charge_col = "batteryChargingPower"
    target_battery_charge_col = "battery_charging_power_w"
    if raw_battery_charge_col in df_processed.columns:
        df_processed[target_battery_charge_col] = (
            pd.to_numeric(df_processed[raw_battery_charge_col], errors="coerce")
            / 1000.0
        )
        # Optionally drop raw column if different and not needed elsewhere,
        # but ensure it's not one of the columns already processed in transformations.
        if (
            raw_battery_charge_col != target_battery_charge_col
            and raw_battery_charge_col
            not in [t[0] for t in transformations if t[1] == raw_battery_charge_col]
        ):
            df_processed = df_processed.drop(
                columns=[raw_battery_charge_col], errors="ignore"
            )
    elif (
        target_battery_charge_col not in df_processed.columns
    ):  # If raw wasn't there, ensure target exists as NaN
        df_processed[target_battery_charge_col] = np.nan

    # Handle output_port_power_w
    # This should be the same data as PowerDrawWatts, which was derived from
    # the raw 'outputPortPower'
    target_output_power_col = "output_port_power_w"
    if "PowerDrawWatts" in df_processed.columns:
        df_processed[target_output_power_col] = df_processed[
            "PowerDrawWatts"
        ]  # Already numeric
    elif target_output_power_col not in df_processed.columns:
        df_processed[target_output_power_col] = np.nan

    # Calculate NetPowerWatts safely
    solar_watts = pd.to_numeric(df_processed.get("SolarInputWatts"), errors="coerce")
    power_draw = pd.to_numeric(df_processed.get("PowerDrawWatts"), errors="coerce")

    # Check if original columns for calculation existed to decide if NetPower
    # can be calculated
    if (
        "SolarInputWatts" in df_processed.columns
        and "PowerDrawWatts" in df_processed.columns
    ):
        df_processed["NetPowerWatts"] = solar_watts - power_draw
    else:
        df_processed["NetPowerWatts"] = np.nan

    expected_cols = [
        "Timestamp",
        "BatteryWattHours",
        "SolarInputWatts",
        "PowerDrawWatts",
        "NetPowerWatts",
        target_battery_charge_col,
        target_output_power_col,
    ]
    for col in expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = np.nan
    return df_processed


def preprocess_ctd_df(df):
    timestamp_col = "Timestamp"
    rename_map = {
        "temperature (degC)": "WaterTemperature",
        "salinity (PSU)": "Salinity",
        "conductivity (S/m)": "Conductivity",
        "oxygen (freq)": "DissolvedOxygen",
        "pressure (dbar)": "Pressure",
    }
    numeric_cols = list(rename_map.values())
    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_weather_df(df):
    timestamp_col = "Timestamp"
    rename_map = {
        "avgTemp(C)": "AirTemperature",
        "avgWindSpeed(kt)": "WindSpeed",
        "gustSpeed(kt)": "WindGust",
        "avgWindDir(deg)": "WindDirection",
        "avgPress(mbar)": "BarometricPressure",
    }
    numeric_cols = list(rename_map.values())
    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_wave_df(df):
    timestamp_col = "Timestamp"
    rename_map = {
        "hs (m)": "SignificantWaveHeight",
        "tp (s)": "WavePeriod",
        "dp (deg)": "MeanWaveDirection",
        "sample Gaps": "SampleGaps",
    }
    numeric_cols = list(rename_map.values())
    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_wave_spectrum_dfs(
    df_freq: pd.DataFrame, df_energy: pd.DataFrame
) -> list[dict]:
    """
    Processes frequency and energy spectrum DataFrames, aligns them by timestamp,
    and combines the spectrum data into a list of dictionaries.

    Args:
        df_freq: DataFrame from GPS Waves Frequency Spectrum.csv
        df_energy: DataFrame from GPS Waves Energy Spectrum.csv

    Returns: A list of dictionaries, where each dictionary represents a
        spectrum at a specific timestamp:
        [{'timestamp': ..., 'freq': [...], 'efth': [...]}, ...]
    """
    if df_freq is None or df_freq.empty:
        logger.warning(
            "Frequency spectrum DataFrame is None or empty for spectrum processing."
        )
        return []
    if df_energy is None or df_energy.empty:
        logger.warning(
            "Energy spectrum DataFrame is None or empty for spectrum processing."
        )
        return []

    # Standardize timestamps in both DataFrames.
    # The raw CSVs use "timeStamp", _initial_dataframe_setup will rename it to
    # "Timestamp".
    df_freq_processed = _initial_dataframe_setup(df_freq, "Timestamp")
    df_energy_processed = _initial_dataframe_setup(df_energy, "Timestamp")

    if df_freq_processed.empty or df_energy_processed.empty:
        logger.warning(
            "One or both spectrum DataFrames are empty after timestamp processing."
        )
        return []

    # Merge the two DataFrames on Timestamp
    # Use an inner merge to keep only timestamps present in both files
    merged_df = pd.merge(
        df_freq_processed,
        df_energy_processed,
        on=[
            "Timestamp",
            "latitude",
            "longitude",
        ],  # Merge on common identifying columns
        suffixes=(
            "_freq",
            "_energy",
        ),  # Suffixes for other potentially overlapping columns like 'spectrum Size'
    )

    if merged_df.empty:
        logger.warning(
            "No matching timestamps (and lat/lon) found between frequency and "
            "energy spectrum files."
        )
        return []

    spectral_records = []
    # Identify value columns (e.g., 'value01_freq', 'value01_energy')
    # Assuming columns are named value01, value02, ..., valueNN
    freq_val_cols = sorted(
        [
            col
            for col in merged_df.columns
            if col.startswith("value") and col.endswith("_freq")
        ],
        key=lambda x: int(x.split("value")[1].split("_")[0]),
    )
    energy_val_cols = sorted(
        [
            col
            for col in merged_df.columns
            if col.startswith("value") and col.endswith("_energy")
        ],
        key=lambda x: int(x.split("value")[1].split("_")[0]),
    )

    for index, row in merged_df.iterrows():
        timestamp = row["Timestamp"]
        # Extract numeric values, handling potential NaNs
        freq_values = pd.to_numeric(row[freq_val_cols], errors="coerce").tolist()
        energy_values = pd.to_numeric(row[energy_val_cols], errors="coerce").tolist()

        # Only add record if both frequency and energy lists are non-empty and
        # have the same length
        if freq_values and energy_values and len(freq_values) == len(energy_values):
            spectral_records.append(
                {"timestamp": timestamp, "freq": freq_values, "efth": energy_values}
            )

    return spectral_records


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
        "aisClass": "AISClass",
        "shipCargoType": "ShipCargoType",
        "heading": "Heading",
        "navigationStatus": "NavigationStatus",
        "callSign": "CallSign",
        "destination": "Destination",
        "eta": "ETA",
        "length": "Length",
        "breadth": "Breadth",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "imoNumber": "IMONumber",
        "dimension": "Dimension",
        "rateOfTurn": "RateOfTurn",
    }
    df_processed = df_processed.rename(columns=rename_map)

    # Specific MMSI handling
    if "MMSI" in df_processed.columns:
        temp_mmsi_series = pd.to_numeric(df_processed["MMSI"], errors="coerce")
        if pd.api.types.is_float_dtype(temp_mmsi_series):
            not_whole_number_mask = temp_mmsi_series.notna() & (
                temp_mmsi_series != np.floor(temp_mmsi_series)
            )
            temp_mmsi_series[not_whole_number_mask] = np.nan
        df_processed["MMSI"] = temp_mmsi_series.astype(
            "Int64"
        )  # Use nullable integer type

    expected_final_cols = [timestamp_col] + list(rename_map.values())
    numeric_cols = ["SpeedOverGround", "CourseOverGround", "Heading", "NavigationStatus", 
                   "Length", "Breadth", "Latitude", "Longitude", "IMONumber", "Dimension", "RateOfTurn"]
    
    for target_col in expected_final_cols:
        if target_col not in df_processed.columns:
            if target_col == "MMSI":
                df_processed[target_col] = pd.Series(dtype="Int64")
            elif target_col == "ShipCargoType":
                df_processed[target_col] = pd.Series(dtype="Int64")
            else:
                df_processed[target_col] = np.nan
        elif target_col in numeric_cols:
            df_processed[target_col] = pd.to_numeric(
                df_processed[target_col], errors="coerce"
            )
        # ShipName, AISClass, CallSign, Destination, ETA are strings
        # MMSI, ShipCargoType are Int64, LastSeenTimestamp is datetime
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
    if (
        "Error Message" in df_processed.columns
        and "error_Message" not in df_processed.columns
    ):
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
        # Ensure even an empty DF from initial setup has the expected columns
        # if it's returned early
        for col in [timestamp_col, "SerialNumber", "DetectionCount", "PingCount"]:
            if col not in df_processed.columns:
                df_processed[col] = (
                    np.nan
                    if col != timestamp_col
                    else pd.Series(dtype="datetime64[ns, UTC]")
                )
        return df_processed

    # Ensure 'status String' column exists
    if "status String" not in df_processed.columns:
        logger.warning("VR2C Preprocessing: 'status String' column not found.")
        df_processed["SerialNumber"] = np.nan  # Can be object/string
        df_processed["DetectionCount"] = np.nan  # Numeric
        df_processed["PingCount"] = np.nan  # Numeric
    else:
        # Function to parse the status string
        def parse_status_string(status_str):
            if pd.isna(status_str):
                return pd.Series(
                    [np.nan, np.nan, np.nan],
                    index=["SerialNumber", "DetectionCount", "PingCount"],
                )

            parts = str(status_str).split(",")
            serial = parts[0].strip() if len(parts) > 0 else np.nan
            dc_str = next(
                (p.split("=")[1].strip() for p in parts if "DC=" in p), np.nan
            )
            pc_str = next(
                (p.split("=")[1].strip() for p in parts if "PC=" in p), np.nan
            )

            dc = pd.to_numeric(dc_str, errors="coerce")
            pc = pd.to_numeric(pc_str, errors="coerce")
            return pd.Series(
                [serial, dc, pc], index=["SerialNumber", "DetectionCount", "PingCount"]
            )

        # Apply the parsing function
        parsed_data = df_processed["status String"].apply(parse_status_string)
        # logger.info(
        #     f"VR2C Preprocessing: Parsed data from 'status String' (first 5 rows):\n{parsed_data.head()}"
        # )
        df_processed = pd.concat([df_processed, parsed_data], axis=1)

        # Ensure types after parsing and concat
        df_processed["DetectionCount"] = pd.to_numeric(
            df_processed.get("DetectionCount"), errors="coerce"
        )
        df_processed["PingCount"] = pd.to_numeric(
            df_processed.get("PingCount"), errors="coerce"
        )
        # logger.info(
        #     f"VR2C Preprocessing: After to_numeric (first 5 rows of DC, PC):\nDetectionCount:\n{df_processed['DetectionCount'].head()}\nPingCount:\n{df_processed['PingCount'].head()}"
        # )

        if (
            "SerialNumber" in df_processed.columns
            and df_processed["SerialNumber"].dtype == float
            and df_processed["SerialNumber"].isna().all()
        ):
            logger.warning(
                "VR2C Preprocessing: SerialNumber column is all NaN after parsing."
            )
        # SerialNumber can remain as object/string

    # Ensure all expected columns are present
    expected_cols = [timestamp_col, "SerialNumber", "DetectionCount", "PingCount"]
    for col in expected_cols:
        if col not in df_processed.columns:
            df_processed[col] = (
                np.nan
            )
            # Default to NaN, specific types handled above/below
            if col == "DetectionCount" or col == "PingCount":
                df_processed[col] = pd.to_numeric(df_processed[col], errors="coerce")

    return df_processed


def preprocess_fluorometer_df(df):
    timestamp_col = "Timestamp"
    rename_map = {
        "latitude": "Latitude",
        "longitude": "Longitude",
        "c1Avg": "C1_Avg",
        "c2Avg": "C2_Avg",
        "c3Avg": "C3_Avg",
        "temp": "Temperature_Fluor",
    }
    numeric_cols = list(rename_map.values())
    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_solar_df(df: pd.DataFrame) -> pd.DataFrame:
    timestamp_col = "Timestamp"
    rename_map = {
        "panelPower1": "Panel1Power",
        "panelPower3": "Panel2Power",  # As per request: panelPower3 is labeled Panel 2
        "panelPower4": "Panel4Power",
    }
    numeric_cols = list(rename_map.values())
    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_telemetry_df(df: pd.DataFrame) -> pd.DataFrame:
    timestamp_col = "Timestamp"  # Standardized name, will come from 'lastLocationFix' or 'gliderTimeStamp'
    # The raw CSV uses "lastLocationFix" and "gliderTimeStamp". # noqa

    # _initial_dataframe_setup will try to standardize one of them to "Timestamp".
    # We'll prioritize 'lastLocationFix' if both are present and become 'Timestamp'. # noqa
    rename_map = {
        "latitude": "Latitude",
        "longitude": "Longitude",
        "gliderHeading": "GliderHeading",
        "gliderSpeed": "GliderSpeed",
        "targetWayPoint": "TargetWaypoint",
        "gliderDistance": "DistanceToWaypoint",
        "speedOverGround": "SpeedOverGround",
        "oceanCurrent": "OceanCurrentSpeed",
        "oceanCurrentDirection": "OceanCurrentDirection",
        "headingFloatDegrees": "HeadingFloatDegrees",  # Often the more accurate heading
        "desiredBearingDegrees": "DesiredBearingDegrees",  # Added
        "headingSubDegrees": "HeadingSubDegrees",  # Added
    }

    numeric_cols_to_ensure = [
        "Latitude",
        "Longitude",
        "GliderHeading",
        "GliderSpeed",
        "DistanceToWaypoint",
        "SpeedOverGround",
        "OceanCurrentSpeed",
        "OceanCurrentDirection",
        "HeadingFloatDegrees",
        "DesiredBearingDegrees",
        "HeadingSubDegrees",  # Added
    ]

    df_processed = _apply_common_processing(
        df, timestamp_col, rename_map, numeric_cols_to_ensure
    )
    if df_processed.empty:
        return df_processed

    # Prioritize 'HeadingFloatDegrees' for 'GliderHeading' if 'gliderHeading'
    # is NaN or missing
    if "GliderHeading" in df_processed.columns and "HeadingFloatDegrees" in df_processed.columns:
        df_processed["GliderHeading"] = df_processed["GliderHeading"].fillna(
            df_processed["HeadingFloatDegrees"]
        )

    return df_processed

def preprocess_wg_vm4_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocesses the WG-VM4 data.
    Placeholder: Standardizes timestamp and ensures essential columns.
    """
    timestamp_col = "Timestamp"
    rename_map = {
        "serial Number": "SerialNumber",
        "channel[0] Detection Count": "Channel0DetectionCount",
        "channel[1] Detection Count": "Channel1DetectionCount",
    }
    numeric_cols = ["Channel0DetectionCount", "Channel1DetectionCount"]

    return _apply_common_processing(df, timestamp_col, rename_map, numeric_cols)


def preprocess_wg_vm4_info_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocesses the WG-VM4 info data for payload parsing.
    
    Args:
        df: Raw DataFrame from WG-VM4 info CSV
        
    Returns:
        Processed DataFrame ready for payload parsing
    """
    if df.empty:
        return df
    
    # Standardize column names
    rename_map = {
        "timeStamp": "timeStamp",
        "latitude": "latitude", 
        "longitude": "longitude",
        "payload Data": "payload_data"  # Remove space for easier access
    }
    
    df_processed = df.rename(columns=rename_map)
    
    # Ensure timestamp is datetime
    if 'timeStamp' in df_processed.columns:
        df_processed['timeStamp'] = pd.to_datetime(df_processed['timeStamp'])
    
    # Ensure numeric columns are properly typed
    numeric_cols = ['latitude', 'longitude']
    for col in numeric_cols:
        if col in df_processed.columns:
            df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
    
    # Ensure payload data is string
    if 'payload_data' in df_processed.columns:
        df_processed['payload_data'] = df_processed['payload_data'].astype(str)
    
    return df_processed

