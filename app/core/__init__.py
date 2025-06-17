"""
Core application logic for data loading, processing, summarization, and plotting.
"""
from .loaders import load_report
from .processors import (
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df, preprocess_wg_vm4_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df, preprocess_solar_df,
    standardize_timestamp_column
)
from .summaries import (
    get_power_status, get_ctd_status, get_weather_status, get_wave_status, get_ais_summary,
    get_recent_errors, get_vr2c_status, get_fluorometer_status, get_navigation_status, get_wg_vm4_status
)
from .forecast import get_general_meteo_forecast, get_marine_meteo_forecast # Updated import
from . import models # Ensure models are importable if needed directly from core