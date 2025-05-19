"""
Core application logic for data loading, processing, summarization, and plotting.
"""
from .loaders import load_report
from .processors import (
    preprocess_power_df, preprocess_ctd_df, preprocess_weather_df,
    preprocess_wave_df, preprocess_ais_df, preprocess_error_df,
    standardize_timestamp_column
)
from .summaries import get_power_status, get_ctd_status, get_weather_status, get_wave_status, get_ais_summary, get_recent_errors
from .plotting import ensure_plots_dir, generate_power_plot, generate_ctd_plot, generate_weather_plot, generate_wave_plot
from .forecast import get_open_meteo_forecast