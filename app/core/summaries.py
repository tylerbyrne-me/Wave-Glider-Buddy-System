import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


import pandas as pd

from . import utils  # Import the utils module
from .processors import preprocess_telemetry_df  # type: ignore
from .processors import preprocess_wg_vm4_df  # type: ignore
from .processors import (preprocess_ais_df, preprocess_ctd_df,  # type: ignore
                         preprocess_error_df, preprocess_fluorometer_df,
                         preprocess_power_df, preprocess_vr2c_df,
                         preprocess_wave_df, preprocess_weather_df)

# MINI_TREND_POINTS = 30 # Number of data points for mini-trend graphs
BATTERY_MAX_WH = 2775.0  # MAX BATTERY,
# ASSUMES 1CCU AND 2APU EACH AT 925WATTHOUR

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

def _get_common_status_data(
    df: Optional[pd.DataFrame],
    preprocessor: callable,
    trend_name: str, # For logging and error messages
) -> Tuple[Dict[str, Any], Optional[pd.DataFrame], Optional[pd.Series]]:
    """
    Helper to perform common initial steps for status functions.
    Initializes result_shell, preprocesses DataFrame, updates latest timestamp info,
    and extracts the last row.

    Returns: (result_shell, df_processed, last_row)
    """
    result_shell: Dict[str, Any] = {
        "values": None,
        "latest_timestamp_str": "N/A",
        "time_ago_str": "N/A",
    }
    if df is None or df.empty:
        return result_shell, None, None

    try:
        df_processed = preprocessor(df)
    except Exception as e:
        logger.warning(f"Error preprocessing {trend_name} data for summary: {e}", exc_info=True)
        return result_shell, None, None

    if not df_processed.empty and "Timestamp" in df_processed.columns:
        update_info = utils.get_df_latest_update_info(df_processed, "Timestamp")
        result_shell.update(update_info)
        last_row = df_processed.loc[df_processed["Timestamp"].idxmax()]
        return result_shell, df_processed, last_row
    else:
        return result_shell, None, None

def _generate_mini_trend(
    df: Optional[pd.DataFrame],
    preprocessor: callable,
    metric_col: str,
    hours_back: int,
    trend_name: str,
    resample_interval: Optional[str] = "1h",
    resample_method: str = "mean",
) -> List[Dict[str, Any]]:
    """
    Generic helper to generate time-series data for mini-trend charts.

    Args:
        df: The input DataFrame.
        preprocessor: The preprocessing function to apply to the DataFrame.
        metric_col: The name of the column to use for the trend value.
        hours_back: The number of hours to look back for the trend data.
        trend_name: The name of the trend for logging purposes.
        resample_interval: The resampling interval (e.g., "1h"). If None, no resampling is done.
        resample_method: The resampling method ('mean' or 'sum').

    Returns:
        A list of dictionaries formatted for charting.
    """
    if df is None or df.empty:
        return []
    try:
        df_processed = preprocessor(df)
        if (
            df_processed.empty
            or "Timestamp" not in df_processed.columns
            or metric_col not in df_processed.columns
        ):
            return []

        max_timestamp = df_processed["Timestamp"].max()
        if pd.isna(max_timestamp):
            return []

        cutoff_time = max_timestamp - timedelta(hours=hours_back)
        df_trend = df_processed[df_processed["Timestamp"] > cutoff_time].sort_values(
            by="Timestamp"
        )

        if df_trend.empty:
            return []

        df_to_format = df_trend  # Default to non-resampled data

        if resample_interval:
            df_trend_indexed = df_trend.set_index("Timestamp")

            if not pd.api.types.is_numeric_dtype(df_trend_indexed[metric_col]):
                logger.warning(
                    f"{trend_name} mini-trend: '{metric_col}' is not numeric, cannot resample."
                )
            else:
                resampler = df_trend_indexed[[metric_col]].resample(resample_interval)
                if resample_method == "sum":
                    df_resampled = resampler.sum()
                else:  # default to mean
                    df_resampled = resampler.mean()

                df_to_format = df_resampled.reset_index().dropna(subset=[metric_col])

        return [
            {"Timestamp": row["Timestamp"].isoformat(), "value": row[metric_col]}
            for _, row in df_to_format.iterrows()
            if pd.notna(row["Timestamp"]) and pd.notna(row[metric_col])
        ]
    except Exception as e:
        logger.warning(f"Error generating {trend_name} mini-trend: {e}", exc_info=True)
        return []


def get_power_status(
    df_power: Optional[pd.DataFrame], df_solar: Optional[pd.DataFrame] = None
) -> Dict:
    """Returns a summary dict for power status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_power_processed, last_row = _get_common_status_data(
            df_power, preprocess_power_df, "Power"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_power_status should be at this indentation level:
        df_last_24h = df_power_processed[
            df_power_processed["Timestamp"]
            > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]

        battery_wh = last_row.get("BatteryWattHours")
        battery_percentage = None
        if battery_wh is not None and pd.notna(battery_wh):
            try:
                battery_percentage_calculated = (
                    float(battery_wh) / BATTERY_MAX_WH
                ) * 100
                battery_percentage = max(0, min(battery_percentage_calculated, 100))
            except (ValueError, TypeError) as e_calc:
                logger.warning(
                    f"PowerSummaryDebug: Could not calculate battery percentage "
                    f"for value: {battery_wh}. Error: {e_calc}"
                )
        else:
            logger.info(
                f"PowerSummaryDebug: Condition NOT met for battery_wh = "
                f"{battery_wh}. pd.notna(battery_wh) is {pd.notna(battery_wh)}"
            )

        # Get Battery Charge Rate (assuming 'battery_charging_power_w' column from processor)
        battery_charge_rate_w = last_row.get("battery_charging_power_w")

        # Calculate Time to Charge
        time_to_charge_str = "N/A"
        if (
            battery_percentage is not None
            and pd.notna(battery_percentage)
            and battery_charge_rate_w is not None
            and pd.notna(battery_charge_rate_w)
        ):
            if battery_charge_rate_w <= 0:
                time_to_charge_str = "Discharging"
                if battery_percentage < 10:  # Example: 10% threshold
                    time_to_charge_str = "Low & Discharging"
            elif battery_percentage >= 99.5:
                # Nearly full
                time_to_charge_str = "Fully Charged"
            else:
                energy_needed_wh = (1.0 - (battery_percentage / 100.0)) * BATTERY_MAX_WH
                if energy_needed_wh < 0:
                    energy_needed_wh = 0

                if battery_charge_rate_w > 0:
                    time_hours_decimal = energy_needed_wh / battery_charge_rate_w
                    if time_hours_decimal > 200:
                        time_to_charge_str = ">200h"
                    elif time_hours_decimal < 0.0167 and energy_needed_wh > 0:
                        # Less than 1 minute
                        time_to_charge_str = "<1m" # noqa
                    elif (
                        time_hours_decimal == 0
                        and energy_needed_wh == 0
                        and battery_percentage < 99.5
                    ):
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
                from .processors import preprocess_solar_df  # Ensure import

                df_solar_processed = preprocess_solar_df(df_solar)
                if (
                    not df_solar_processed.empty
                    and "Timestamp" in df_solar_processed.columns
                ):
                    # Find solar data closest to the power data's last_row timestamp
                    # Using merge_asof for robust closest timestamp matching
                    df_power_ts = pd.DataFrame({"Timestamp": [last_row["Timestamp"]]})
                    merged_df = pd.merge_asof(
                        df_power_ts.sort_values("Timestamp"),
                        df_solar_processed.sort_values("Timestamp"),
                        on="Timestamp",
                        direction="nearest",
                        # Optional: only consider if within 1 hour
                        tolerance=pd.Timedelta(hours=1),
                    )
                    if not merged_df.empty and not merged_df.iloc[0].isnull().all():
                        last_solar_row = merged_df.iloc[0]
                        panel1_power = last_solar_row.get("Panel1Power")
                        panel2_power = last_solar_row.get(
                            "Panel2Power"
                        )  # from panelPower3
                        panel4_power = last_solar_row.get("Panel4Power")
            except Exception as e_solar:
                logger.warning(
                    f"Error processing solar data for power summary: {e_solar}"
                )

        # Calculate 24-hour averages
        avg_output_port_power_24hr_w = (
            df_last_24h["output_port_power_w"].mean()
            if not df_last_24h.empty and "output_port_power_w" in df_last_24h
            else None
        )
        avg_solar_input_24hr_w = (
            df_last_24h["SolarInputWatts"].mean()
            if not df_last_24h.empty and "SolarInputWatts" in df_last_24h
            else None
        )

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
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_power_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_power_mini_trend(df_power: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the power summary card."""
    return _generate_mini_trend(
        df=df_power,
        preprocessor=preprocess_power_df,
        metric_col="battery_charging_power_w",
        hours_back=24,
        trend_name="Power",
        resample_interval=None,  # Power trend does not resample
    )


def get_fluorometer_status(df_fluorometer: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for fluorometer status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_fluorometer_processed, last_row = _get_common_status_data(
            df_fluorometer, preprocess_fluorometer_df, "Fluorometer"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_fluorometer_status should be at this indentation level:
        result_shell["values"] = {
                "C1_Avg": last_row.get("C1_Avg"),
                "C2_Avg": last_row.get("C2_Avg"),
                "C3_Avg": last_row.get("C3_Avg"),
                "Temperature_Fluor": last_row.get("Temperature_Fluor"),
                "Latitude": last_row.get("Latitude"),
                "Longitude": last_row.get("Longitude"),
                "Timestamp": (
                    last_row["Timestamp"].isoformat()
                    if pd.notna(last_row.get("Timestamp"))
                    else "N/A"
                ),
            }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_fluorometer_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_fluorometer_mini_trend(
    df_fluorometer: Optional[pd.DataFrame],
) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the fluorometer summary card."""
    return _generate_mini_trend(
        df=df_fluorometer,
        preprocessor=preprocess_fluorometer_df,
        metric_col="C1_Avg",
        hours_back=24,
        trend_name="Fluorometer",
    )


def get_ctd_status(df_ctd: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for CTD status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_ctd_processed, last_row = _get_common_status_data(
            df_ctd, preprocess_ctd_df, "CTD"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_ctd_status should be at this indentation level:
        # Calculate Highest and Lowest Water Temperature from the last 24 hours
        df_last_24h = df_ctd_processed[
            df_ctd_processed["Timestamp"]
            > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]
        highest_temp_24h = (
            df_last_24h["WaterTemperature"].max()
            if not df_last_24h.empty and "WaterTemperature" in df_last_24h
            else None
        )
        lowest_temp_24h = (
            df_last_24h["WaterTemperature"].min()
            if not df_last_24h.empty and "WaterTemperature" in df_last_24h
            else None
        )

        result_shell["values"] = {
            "WaterTemperature": last_row.get("WaterTemperature"),
            "Salinity": last_row.get("Salinity"),
            "Conductivity": last_row.get("Conductivity"),
            "DissolvedOxygen": last_row.get("DissolvedOxygen"),
            "Pressure": last_row.get("Pressure"),
            "HighestWaterTemperature24h": highest_temp_24h,
            "LowestWaterTemperature24h": lowest_temp_24h,
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_ctd_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_ctd_mini_trend(df_ctd: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the CTD summary card."""
    return _generate_mini_trend(
        df=df_ctd,
        preprocessor=preprocess_ctd_df,
        metric_col="WaterTemperature",
        hours_back=24,
        trend_name="CTD",
    )


def get_weather_status(df_weather: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for weather status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_weather_processed, last_row = _get_common_status_data(
            df_weather, preprocess_weather_df, "Weather"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_weather_status should be at this indentation level:
        # Calculate 24-hour High/Low for AirTemperature and BarometricPressure
        df_last_24h = df_weather_processed[
            df_weather_processed["Timestamp"]
            > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]

        air_temp_high_24h = (
            df_last_24h["AirTemperature"].max()
            if not df_last_24h.empty and "AirTemperature" in df_last_24h
            else None
        )
        air_temp_low_24h = (
            df_last_24h["AirTemperature"].min()
            if not df_last_24h.empty and "AirTemperature" in df_last_24h
            else None
        )

        pressure_high_24h = (
            df_last_24h["BarometricPressure"].max()
            if not df_last_24h.empty and "BarometricPressure" in df_last_24h
            else None
        )
        pressure_low_24h = (
            df_last_24h["BarometricPressure"].min()
            if not df_last_24h.empty and "BarometricPressure" in df_last_24h
            else None
        )

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
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_weather_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_weather_mini_trend(df_weather: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the weather summary card."""
    return _generate_mini_trend(
        df=df_weather,
        preprocessor=preprocess_weather_df,
        metric_col="WindSpeed",
        hours_back=24,
        trend_name="Weather",
    )


def get_wave_status(df_waves: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for wave status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_waves_processed, last_row = _get_common_status_data(
            df_waves, preprocess_wave_df, "Wave"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_wave_status should be at this indentation level:
        # Calculate 24-hour average for SignificantWaveHeight
        df_last_24h = df_waves_processed[
            df_waves_processed["Timestamp"]
            > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]
        avg_wave_height_24h = (
            df_last_24h["SignificantWaveHeight"].mean()
            if not df_last_24h.empty and "SignificantWaveHeight" in df_last_24h
            else None
        )

        # Calculate Wave Amplitude
        significant_wave_height = last_row.get("SignificantWaveHeight")
        wave_amplitude = (
            (significant_wave_height / 2)
            if significant_wave_height is not None
            and pd.notna(significant_wave_height)
            else None
        )

        # Filter MeanWaveDirection for outliers
        mean_direction_raw = last_row.get("MeanWaveDirection")
        mean_direction_display_value = "N/A"  # Default display
        mean_direction_numeric_value = None  # For potential numeric use if valid
        mean_direction_status = "missing"  # Default status

        if pd.notna(mean_direction_raw):
            try:
                val_as_int = int(mean_direction_raw)
                if val_as_int == 9999 or val_as_int == -9999:
                    mean_direction_display_value = "N/A (Outlier)"
                    mean_direction_status = "outlier"
                else:
                    mean_direction_display_value = (
                        f"{val_as_int:.0f} °"  # Format valid number
                    )
                    mean_direction_numeric_value = val_as_int
                    mean_direction_status = "valid"
            except ValueError:
                logger.warning(
                    f"Could not convert MeanWaveDirection "
                    f"'{mean_direction_raw}' to int for outlier check."
                )
                # Indicate a parsing error
                mean_direction_display_value = "N/A (Error)"
                mean_direction_status = "error"

        result_shell["values"] = {
            "SignificantWaveHeight": significant_wave_height,
            "SignificantWaveHeightAvg24h": avg_wave_height_24h,
            "WavePeriod": last_row.get("WavePeriod"),
            "MeanDirectionDisplay": mean_direction_display_value,
            "MeanDirectionNumeric": mean_direction_numeric_value,
            "MeanDirectionStatus": mean_direction_status,
            "WaveAmplitude": wave_amplitude,
            "SampleGaps": last_row.get("SampleGaps"),
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_wave_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_wave_mini_trend(df_waves: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the wave summary card."""
    return _generate_mini_trend(
        df=df_waves,
        preprocessor=preprocess_wave_df,
        metric_col="SignificantWaveHeight",
        hours_back=48,
        trend_name="Wave",
    )


def get_ais_summary(ais_df, max_age_hours=24):
    # Preprocessor ensures "LastSeenTimestamp" is datetime64[ns, UTC] or df is empty
    # It also handles copying.
    df_ais_processed = preprocess_ais_df(
        ais_df if ais_df is not None else pd.DataFrame()
    )
    if df_ais_processed.empty:
        return []

    # Timestamps in df_ais_processed["LastSeenTimestamp"] are UTC datetime objects.
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    # Direct comparison with UTC datetime objects
    recent = df_ais_processed[df_ais_processed["LastSeenTimestamp"] > cutoff_time]
    if recent.empty:
        return []

    # MMSI is Int64 or pd.NA from processor.
    if (
        "MMSI" not in recent.columns or recent["MMSI"].isna().all()
    ):  # Use .isna() for nullable integers
        logger.debug("AIS summary: No recent vessels with valid MMSI found.")

    # Get the latest record for each MMSI, dropping rows where MMSI is NA before grouping
    latest_by_mmsi = (
        recent.dropna(subset=["MMSI"])
        .sort_values("LastSeenTimestamp", ascending=False)
        .groupby("MMSI")
        .first()
        .reset_index()
    )
    
    # Import vessel categories here to avoid circular imports
    from .vessel_categories import get_vessel_category, is_hazardous_vessel, get_ais_class_info
    
    vessels = []
    for _, row in latest_by_mmsi.iterrows():
        # Get vessel category information
        ship_cargo_type = row.get("ShipCargoType")
        category, group, color = get_vessel_category(ship_cargo_type)
        is_hazardous = is_hazardous_vessel(ship_cargo_type)
        
        # Get AIS class information
        ais_class = row.get("AISClass")
        ais_class_display, ais_class_color = get_ais_class_info(ais_class)
        
        vessel = {
            "ShipName": row.get("ShipName", "Unknown"),
            "MMSI": (
                int(row["MMSI"]) if pd.notna(row["MMSI"]) else None
            ),  # Convert Int64 to standard int or None
            "SpeedOverGround": row.get("SpeedOverGround"),
            "CourseOverGround": row.get("CourseOverGround"),
            "LastSeenTimestamp": row[
                "LastSeenTimestamp"
            ],  # This is already a datetime object
            # Enhanced fields
            "AISClass": ais_class,
            "AISClassDisplay": ais_class_display,
            "AISClassColor": ais_class_color,
            "ShipCargoType": ship_cargo_type,
            "Category": category,
            "Group": group,
            "CategoryColor": color,
            "IsHazardous": is_hazardous,
            "Heading": row.get("Heading"),
            "NavigationStatus": row.get("NavigationStatus"),
            "CallSign": row.get("CallSign"),
            "Destination": row.get("Destination"),
            "ETA": row.get("ETA"),
            "Length": row.get("Length"),
            "Breadth": row.get("Breadth"),
            "Latitude": row.get("Latitude"),
            "Longitude": row.get("Longitude"),
            "IMONumber": row.get("IMONumber"),
            "Dimension": row.get("Dimension"),
            "RateOfTurn": row.get("RateOfTurn"),
        }
        vessels.append(vessel)
    return sorted(vessels, key=lambda v: v["LastSeenTimestamp"], reverse=True)


def get_ais_summary_stats(ais_df, max_age_hours=24):
    """
    Get AIS summary statistics for dashboard display.
    
    Args:
        ais_df: AIS DataFrame
        max_age_hours: Maximum age of data to include
        
    Returns:
        Dictionary with summary statistics
    """
    vessels = get_ais_summary(ais_df, max_age_hours)
    
    if not vessels:
        return {
            "total_vessels": 0,
            "class_a_count": 0,
            "class_b_count": 0,
            "hazardous_count": 0,
            "category_breakdown": {},
            "group_breakdown": {},
            "recent_activity": []
        }
    
    # Import vessel categories here to avoid circular imports
    from .vessel_categories import get_vessel_summary_stats
    
    stats = get_vessel_summary_stats(vessels)
    
    # Add recent activity (last 3 vessels)
    stats["recent_activity"] = vessels[:3]
    
    return stats


def get_recent_errors(error_df, max_age_hours=24):
    # Preprocessor ensures "Timestamp" is datetime64[ns, UTC] or df is empty
    df_error_processed = preprocess_error_df(
        error_df if error_df is not None else pd.DataFrame()
    )
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
    """Returns a summary dict for VR2C status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_vr2c_processed, last_row = _get_common_status_data(
            df_vr2c, preprocess_vr2c_df, "VR2C"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_vr2c_status should be at this indentation level:
        result_shell["values"] = {
                "SerialNumber": last_row.get("SerialNumber"),
                "DetectionCount": last_row.get("DetectionCount"),
                "PingCount": last_row.get("PingCount"),
                "Timestamp": (
                    last_row["Timestamp"].isoformat()
                    if pd.notna(last_row.get("Timestamp"))
                    else "N/A"
                ),
            }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_vr2c_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_vr2c_mini_trend(df_vr2c: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the VR2C summary card."""
    return _generate_mini_trend(
        df=df_vr2c,
        preprocessor=preprocess_vr2c_df,
        metric_col="DetectionCount",
        hours_back=24,
        trend_name="VR2C",
        resample_method="sum",
    )


def get_navigation_status(df_telemetry: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for navigation status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_telemetry_processed, last_row = _get_common_status_data(
            df_telemetry, preprocess_telemetry_df, "Navigation"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_navigation_status should be at this indentation level:
        # Calculate 24-hour metrics
        df_last_24h = df_telemetry_processed[
            df_telemetry_processed["Timestamp"]
            > (last_row["Timestamp"] - pd.Timedelta(hours=24))
        ]

        # Speed Over Ground metrics
        avg_sog_24h = (
            df_last_24h["SpeedOverGround"].mean()
            if not df_last_24h.empty
            and "SpeedOverGround" in df_last_24h.columns
            and pd.api.types.is_numeric_dtype(df_last_24h["SpeedOverGround"])
            else None
        )

        # Distance Traveled metrics (using 'DistanceToWaypoint' which is processed 'gliderDistance')
        METERS_TO_NAUTICAL_MILES = 0.000539957

        total_distance_mission_meters = (
            df_telemetry_processed["DistanceToWaypoint"].sum()
            if "DistanceToWaypoint" in df_telemetry_processed.columns
            and pd.api.types.is_numeric_dtype(
                df_telemetry_processed["DistanceToWaypoint"]
            )
            else 0
        )
        distance_traveled_24h_meters = (
            df_last_24h["DistanceToWaypoint"].sum()
            if not df_last_24h.empty
            and "DistanceToWaypoint" in df_last_24h.columns
            and pd.api.types.is_numeric_dtype(df_last_24h["DistanceToWaypoint"])
            else 0
        )

        total_distance_mission_nm = (
            total_distance_mission_meters * METERS_TO_NAUTICAL_MILES
            if pd.notna(total_distance_mission_meters)
            else None
        )
        distance_traveled_24h_nm = (
            distance_traveled_24h_meters * METERS_TO_NAUTICAL_MILES
            if pd.notna(distance_traveled_24h_meters)
            else None
        )

        result_shell["values"] = {
            "Latitude": last_row.get("Latitude"),
            "Longitude": last_row.get("Longitude"),
            "GliderHeading": last_row.get("GliderHeading"),
            "SpeedOverGround": last_row.get("SpeedOverGround"),
            "AvgSpeedOverGround24h": avg_sog_24h,
            "TotalDistanceTraveledMissionNM": total_distance_mission_nm,
            "DistanceTraveled24hNM": distance_traveled_24h_nm,
            "OceanCurrentSpeed": last_row.get("OceanCurrentSpeed"),
            "OceanCurrentDirection": last_row.get("OceanCurrentDirection"),
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_navigation_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_navigation_mini_trend(
    df_telemetry: Optional[pd.DataFrame],
) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the navigation summary card."""
    return _generate_mini_trend(
        df=df_telemetry,
        preprocessor=preprocess_telemetry_df,
        metric_col="GliderSpeed",
        hours_back=24,
        trend_name="Navigation",
    )


def get_wg_vm4_status(df_wg_vm4: Optional[pd.DataFrame]) -> Dict:
    """Returns a summary dict for WG-VM4 status. Returns safe defaults and logs errors if data is missing or malformed."""
    try:
        result_shell, df_wg_vm4_processed, last_row = _get_common_status_data(
            df_wg_vm4, preprocess_wg_vm4_df, "WG-VM4"
        )
        if last_row is None:
            return result_shell

        # All subsequent logic for get_wg_vm4_status should be at this indentation level:
        result_shell["values"] = {
            "SerialNumber": last_row.get("SerialNumber"),
            "Channel0DetectionCount": last_row.get("Channel0DetectionCount"),
            "Channel1DetectionCount": last_row.get("Channel1DetectionCount"),
            # Add other relevant fields as placeholders or once decided
            "PlaceholderField1": "N/A",
            "PlaceholderField2": "N/A",
            "Timestamp": (
                last_row["Timestamp"].isoformat()
                if pd.notna(last_row.get("Timestamp"))
                else "N/A"
            ),
        }
        return result_shell
    except Exception as e:
        logger.warning(f"Error in get_wg_vm4_status: {e}", exc_info=True)
        return {"values": None, "latest_timestamp_str": "N/A", "time_ago_str": "N/A"}


def get_wg_vm4_mini_trend(df_wg_vm4: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    """Generates the mini-trend data for the WG-VM4 summary card."""
    return _generate_mini_trend(
        df=df_wg_vm4,
        preprocessor=preprocess_wg_vm4_df,
        metric_col="Channel0DetectionCount",
        hours_back=24,
        trend_name="WG-VM4",
        resample_method="sum",
    )
