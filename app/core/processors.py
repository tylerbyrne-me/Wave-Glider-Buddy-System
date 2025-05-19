import pandas as pd
import numpy as np

def standardize_timestamp_column(df, preferred="Timestamp"):
    """Renames the first found common timestamp column"""
    for col in df.columns:
        lower_col = col.lower()
        if "time" in lower_col or col in ["timeStamp", "gliderTimeStamp", "lastLocationFix"]:
            df = df.rename(columns={col: preferred})
            return df
    return df

def preprocess_power_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        "totalBatteryPower": "BatteryWattHours",
        "solarPowerGenerated": "SolarInputWatts",
        "outputPortPower": "PowerDrawWatts"
    }
    for old_name, new_name in rename_map.items():
        if old_name in df.columns:
            df[new_name] = df[old_name] / 1000
            if old_name != new_name:
                df = df.drop(columns=[old_name], errors='ignore')
        elif new_name not in df.columns and old_name not in df.columns:
            df[new_name] = np.nan

    if "SolarInputWatts" in df.columns and "PowerDrawWatts" in df.columns:
        df["NetPowerWatts"] = df["SolarInputWatts"] - df["PowerDrawWatts"]
    else:
        df["NetPowerWatts"] = np.nan
    return df

def preprocess_ctd_df(df):
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
        'oxygen (freq)': 'DissolvedOxygen',
        'pressure (dbar)': 'Pressure',
    }
    df = df.rename(columns=rename_map)
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df

def preprocess_weather_df(df):
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

def preprocess_wave_df(df):
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

def preprocess_ais_df(df):
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
    if "MMSI" in df.columns:
        temp_mmsi_series = pd.to_numeric(df["MMSI"], errors='coerce')
        if pd.api.types.is_float_dtype(temp_mmsi_series):
            not_whole_number_mask = temp_mmsi_series.notna() & (temp_mmsi_series != np.floor(temp_mmsi_series))
            temp_mmsi_series[not_whole_number_mask] = np.nan
        df["MMSI"] = temp_mmsi_series.astype('Int64')

    for target_col in rename_map.values():
        if target_col not in df.columns:
            if target_col == "MMSI":
                 df[target_col] = pd.Series(dtype='Int64')
            else:
                df[target_col] = np.nan
    return df

def preprocess_error_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = standardize_timestamp_column(df, preferred="Timestamp")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    if df.empty:
        return df

    rename_map = {
        "vehicleName": "VehicleName",
        "selfCorrected": "SelfCorrected",
        "error_Message": "ErrorMessage",
    }
    df = df.rename(columns=rename_map)
    for target_col in rename_map.values():
        if target_col not in df.columns:
            df[target_col] = np.nan
    return df