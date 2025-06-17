import argparse
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from rich.console import Console  # Keep this
from rich.table import Table

from ..config import settings  # Import settings
from ..core import forecast, loaders, plotting, summaries
# Specific plotting functions are still useful to import directly if only they are used from plotting
from ..core.plotting import (generate_ctd_plot, generate_power_plot,
                             generate_wave_plot, generate_weather_plot)

# Define default data sources
DEFAULT_LOCAL_DATA_PATH = Path(r"C:\Users\ty225269\Documents\Python Playground\Data")
# base URL
DEFAULT_REMOTE_DATA_BASE_URL = "http://129.173.20.180:8086/output_realtime_missions/"

parser = argparse.ArgumentParser(description="Wave Glider System Check")
parser.add_argument("--mission", required=True, help="Mission ID (e.g., m204)")
parser.add_argument("--hours", type=int, default=72, help="Lookback period in hours")
parser.add_argument("--forecast", action="store_true", help="Include weather forecast")
parser.add_argument("--lat", type=float, help="Manual latitude for forecast")
parser.add_argument("--lon", type=float, help="Manual longitude for forecast")
parser.add_argument("--summary", action="store_true", help="Print system summary")

args = parser.parse_args()

console = Console()


def main():
    if args.summary:
        check_power(args.mission, args.hours)
        check_ctd(args.mission, args.hours)
        check_weather(args.mission, args.hours)
        check_waves(args.mission, args.hours)
        check_ais(args.mission, args.hours)
        check_errors(args.mission, args.hours)

    if args.forecast:
        check_forecast_with_inference(args.mission, args.lat, args.lon)


def load_data_interactive(report_type: str, mission_id: str):
    """
    Attempts to load data:
    1. Tries local path.
    2. If local found, prompts user to use it or try remote.
    3. If local not found or user opts for remote, tries remote URL.
    """
    # 1. Try local
    df_local = None
    try:
        console.print(
            f"Attempting to load {report_type} for {mission_id} from local path: {DEFAULT_LOCAL_DATA_PATH}..."
        )
        df_local = loaders.load_report(
            report_type, mission_id, base_path=DEFAULT_LOCAL_DATA_PATH
        )
        console.print(
            f"[green]Successfully loaded {report_type} from local path.[/green]"
        )
        while True:
            choice = (
                console.input(
                    f"Use local data for {report_type}? (y/n, 'n' to try remote): "
                )
                .strip()
                .lower()
            )
            if choice == "y":
                return df_local
            elif choice == "n":
                console.print("Opted to try remote URL.")
                break  # proceed to remote load
            else:
                console.print(
                    "[yellow]Invalid choice. Please enter 'y' or 'n'.[/yellow]"
                )
        # If user chose 'n', df_local will be discarded and we proceed to remote
    except FileNotFoundError:
        console.print(
            f"[yellow]Local file for {report_type} not found. Defaulting to remote URL.[/yellow]"
        )
        # Proceed to remote load
    except Exception as e:
        console.print(
            f"[yellow]Failed to load {report_type} from local path ({e}). Trying remote URL.[/yellow]"
        )
        # Proceed to remote load

    # 2. Try remote (if local failed, not found, or user chose 'n')
    try:
        # Determine the actual folder name for the remote server
        remote_folder_name = settings.remote_mission_folder_map.get(
            mission_id, mission_id
        )
        console.print(
            f"Attempting to load {report_type} for mission '{mission_id}' (remote folder: '{remote_folder_name}') from base URL: {DEFAULT_REMOTE_DATA_BASE_URL}..."
        )
        df_remote = loaders.load_report(
            report_type,
            mission_id=remote_folder_name,
            base_url=DEFAULT_REMOTE_DATA_BASE_URL,
        )
        console.print(
            f"[green]Successfully loaded {report_type} from remote URL.[/green]"
        )
        return df_remote
    except Exception as e:
        console.print(
            f"[red]❌ Failed to load {report_type} from remote URL: {e}[/red]"
        )
        return (
            pd.DataFrame()
        )  # Return empty DataFrame on failure to avoid None downstream


def check_power(mission_id, hours_back=72):
    df_power = load_data_interactive("power", mission_id)
    power_status = summaries.get_power_status(df_power)
    if not power_status:
        console.print("[red]❌ No power data available[/red]")
        return

    # Display the table
    console.rule("🔌 Power System Status")
    table_data = [
        ("Battery (Wh)", power_status.get("BatteryWattHours")),
        ("Solar Input (W)", power_status.get("SolarInputWatts")),
        (
            "Power Draw (W)",
            power_status.get("PowerDrawWatts"),
        ),  # Changed label for clarity
        ("Net Power (W)", power_status.get("NetPowerWatts")),  # Key is NetPowerWatts
    ]

    power_table = (
        Table()
    )  # Use a more specific name to avoid conflict if Table is imported at top
    for label, _ in table_data:
        power_table.add_column(label, justify="right")

    power_table.add_row(
        *[f"{val:.2f}" if val is not None else "N/A" for _, val in table_data]
    )
    console.print(power_table)

    if (
        power_status.get("NetPowerWatts") is not None
        and power_status["NetPowerWatts"] < 0
    ):
        console.print("⚠ Battery is discharging")

    # Generate and report the plot
    plot_path = generate_power_plot(df_power, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Power trend plot saved to {plot_path}[/green]")


def check_ctd(mission_id, hours_back=24):
    df_ctd = load_data_interactive("ctd", mission_id)
    status = summaries.get_ctd_status(df_ctd)

    if not status:
        console.print("[red]❌ No CTD data available[/red]")
        return

    console.rule("🔬 Latest CTD Reading")
    table = Table(title="Latest CTD Reading")
    table.add_column("Water Temp (°C)")  # Changed key
    table.add_column("Salinity (PSU)")
    table.add_column("Conductivity (S/m)")
    table.add_column("O₂ (Hz)")  # Corresponds to DissolvedOxygen
    table.add_column("Pressure (dbar)")  # Changed from Depth to Pressure

    table.add_row(
        (
            f"{status.get('WaterTemperature'):.2f}"
            if status.get("WaterTemperature") is not None
            else "N/A"
        ),
        (
            f"{status.get('Salinity'):.2f}"
            if status.get("Salinity") is not None
            else "N/A"
        ),
        (
            f"{status.get('Conductivity'):.2f}"
            if status.get("Conductivity") is not None
            else "N/A"
        ),
        (
            f"{status.get('DissolvedOxygen'):.2f}"
            if status.get("DissolvedOxygen") is not None
            else "N/A"
        ),  # Assuming this is the desired output
        (
            f"{status.get('Pressure'):.1f}"
            if status.get("Pressure") is not None
            else "N/A"
        ),  # Changed from Depth to Pressure
    )

    console.print(table)

    plot_path = generate_ctd_plot(df_ctd, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ CTD trend plot saved to {plot_path}[/green]")


def check_weather(mission_id, hours_back=72):
    df_weather = load_data_interactive("weather", mission_id)
    status = summaries.get_weather_status(df_weather)

    if not status:
        console.print("[red]❌ No weather data available[/red]")
        return

    console.rule("⛅ Current Weather Conditions")
    table = Table()
    table.add_column("Air Temp (°C)")  # Changed key
    table.add_column("Wind (kt)")
    table.add_column("Gust (kt)")
    table.add_column("Direction (°)")

    table.add_row(
        (
            f"{status.get('AirTemperature'):.1f}"
            if status.get("AirTemperature") is not None
            else "N/A"
        ),
        (
            f"{status.get('WindSpeed'):.1f}"
            if status.get("WindSpeed") is not None
            else "N/A"
        ),
        (
            f"{status.get('WindGust'):.1f}"
            if status.get("WindGust") is not None
            else "N/A"
        ),
        (
            f"{int(status.get('WindDirection'))}"
            if status.get("WindDirection") is not None
            else "N/A"
        ),
    )

    console.print(table)

    plot_path = generate_weather_plot(df_weather, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Weather trend plot saved to {plot_path}[/green]")


def check_waves(mission_id, hours_back=72):
    df_waves = load_data_interactive("waves", mission_id)
    status = summaries.get_wave_status(df_waves)

    if not status:
        console.print("[red]❌ No wave data available[/red]")
        return

    console.rule("🌊 Current Wave Conditions")
    table = Table()
    table.add_column("Sig. Wave Height (m)")  # Changed key
    table.add_column("Period (s)")
    table.add_column("Mean Direction (°)")  # Changed key

    table.add_row(
        (
            f"{status.get('SignificantWaveHeight'):.2f}"
            if status.get("SignificantWaveHeight") is not None
            else "N/A"
        ),
        (
            f"{status.get('WavePeriod'):.1f}"
            if status.get("WavePeriod") is not None
            else "N/A"
        ),
        (
            f"{status.get('MeanWaveDirection'):.0f}"
            if status.get("MeanWaveDirection") is not None
            else "N/A"
        ),  # .0f for direction
    )

    console.print(table)

    plot_path = generate_wave_plot(df_waves, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Wave trend plot saved to {plot_path}[/green]")


def check_ais(mission_id, hours_back=24):
    df_ais = load_data_interactive("ais", mission_id)
    vessels = summaries.get_ais_summary(df_ais, max_age_hours=hours_back)

    if not vessels:
        console.print("[yellow]⚠ No recent AIS data[/yellow]")
        return

    console.rule("🛥️ Nearby Vessels (AIS)")
    table = Table()
    table.add_column("Ship")
    table.add_column("MMSI", justify="right")
    table.add_column("SOG (kt)", justify="right")
    table.add_column("COG (°)", justify="right")
    table.add_column("Last Seen")

    for vessel in vessels:
        age = datetime.now() - vessel["LastSeenTimestamp"]  # Changed key
        last_seen_str = (
            f"{age.days} days ago" if age.days > 0 else f"{age.seconds // 3600} hrs ago"
        )

        table.add_row(
            vessel.get("ShipName", "Unknown"),
            str(vessel.get("MMSI")) if vessel.get("MMSI") is not None else "N/A",
            (
                f"{vessel.get('SpeedOverGround'):.1f}"
                if vessel.get("SpeedOverGround") is not None
                else "N/A"
            ),
            (
                f"{vessel.get('CourseOverGround'):.0f}"
                if vessel.get("CourseOverGround") is not None
                else "N/A"
            ),
            last_seen_str,
        )
    console.print(table)


def check_errors(mission_id, hours_back=24):
    df_errors = load_data_interactive("errors", mission_id)
    errors = summaries.get_recent_errors(df_errors, max_age_hours=hours_back)

    if not errors:
        console.print("[green]✅ No recent errors in last 24 hours[/green]")
        return

    console.rule("⚠️ Recent System Errors")
    table = Table()
    table.add_column("Time")
    table.add_column("System")
    table.add_column("Self Corrected")
    table.add_column("Message")

    for err in errors[:20]:  # limit to most recent 20
        ts = err.get("Timestamp", None)  # Changed key
        if ts is not None:
            # Convert pandas Timestamp/datetime to formatted string
            ts = pd.to_datetime(ts)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = "N/A"

        # Convert boolean to Yes/No with color - This block was incorrectly indented
        self_corrected = err.get("SelfCorrected", None)  # Changed key
        if isinstance(self_corrected, bool):
            severity_str = "[yellow]Yes[/yellow]"
        else:
            # Handle "TRUE"/"FALSE" string case (from CSV)
            sc_str = str(self_corrected).strip().upper()
            if sc_str == "TRUE":
                severity_str = "[yellow]Yes[/yellow]"
            elif sc_str == "FALSE":
                severity_str = "[red]No[/red]"
            else:
                severity_str = "N/A"

        table.add_row(
            ts_str,
            str(err.get("VehicleName", "N/A")),  # Changed key
            severity_str,
            str(err.get("ErrorMessage", "N/A")),  # Changed key
        )
    console.print(table)


def display_cli_forecast(forecast_data_json):
    """Helper to display forecast using Rich, specific to CLI."""
    if not forecast_data_json:
        console.print("[red]❌ Unable to retrieve weather forecast data[/red]")
        return

    hourly = forecast_data_json.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get(
        "windspeed_10m", []
    )  # Assuming API returns m/s, convert if needed or adjust label
    precip = hourly.get("precipitation", [])

    if not times:
        console.print(
            "[yellow]⚠ Forecast data received but no time points found.[/yellow]"
        )
        return

    table = Table(title="48-hour Weather Forecast")
    table.add_column("Time")
    table.add_column("Temp (°C)")
    table.add_column("Wind (m/s)")  # Or convert to kt and change label
    table.add_column("Precip (mm)")
    display_limit = 48
    for i in range(min(len(times), display_limit)):
        table.add_row(
            times[i], f"{temps[i]:.1f}", f"{winds[i]:.1f}", f"{precip[i]:.1f}"
        )
    console.print(table)


def check_forecast(lat, lon):
    forecast_data_json = forecast.get_open_meteo_forecast(lat, lon)
    display_cli_forecast(forecast_data_json)


def check_forecast_with_inference(mission_id, lat=None, lon=None):
    if lat is None or lon is None:
        try:
            df_telemetry = load_data_interactive("telemetry", mission_id)
            if df_telemetry is None or df_telemetry.empty:
                console.print(
                    f"[red]❌ Telemetry data for {mission_id} could not be loaded. Cannot infer location.[/red]"
                )
                return

            df_telemetry["lastLocationFix"] = pd.to_datetime(
                df_telemetry["lastLocationFix"], errors="coerce"
            )
            df_telemetry = df_telemetry.dropna(subset=["lastLocationFix"])

            latest = df_telemetry.sort_values("lastLocationFix", ascending=False).iloc[
                0
            ]
            lat = latest.get("latitude") or latest.get("Latitude")
            lon = latest.get("longitude") or latest.get("Longitude")

            if pd.isna(lat) or pd.isna(lon):
                raise ValueError("Missing lat/lon values")

            console.print(
                f"[cyan]📍 Using telemetry position: {lat:.3f}, {lon:.3f}[/cyan]"
            )

        except Exception as e:
            console.print(f"[red]❌ Unable to infer lat/lon from telemetry: {e}[/red]")
            return

    check_forecast(lat, lon)


if __name__ == "__main__":
    main()
