from .. import mission_core # Use this to call mission_core.load_report etc.
from ..mission_core import get_power_status, generate_power_plot, generate_ctd_plot, get_ctd_status, get_weather_status, generate_weather_plot, get_wave_status, generate_wave_plot, get_ais_summary, get_recent_errors, get_open_meteo_forecast, display_weather_forecast
from rich.console import Console # Keep this
from rich.table import Table
from datetime import datetime, timedelta
import pandas as pd
import argparse
import math
from pathlib import Path

# Define default data sources
DEFAULT_LOCAL_DATA_PATH = Path(r"C:\Users\ty225269\Documents\Python Playground\Data")
DEFAULT_REMOTE_DATA_URL = "http://129.173.20.180:8086/output_realtime_missions/"

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
    try:
        console.print(f"Attempting to load {report_type} for {mission_id} from local path: {DEFAULT_LOCAL_DATA_PATH}...")
        df = mission_core.load_report(report_type, mission_id, base_path=DEFAULT_LOCAL_DATA_PATH)
        console.print(f"[green]Successfully loaded {report_type} from local path.[/green]")
        while True:
            choice = console.input(f"Use local data for {report_type}? (y/n, 'n' to try remote): ").strip().lower()
            if choice == 'y':
                return df
            elif choice == 'n':
                console.print("Opted to try remote URL.")
                break 
            else:
                console.print("[yellow]Invalid choice. Please enter 'y' or 'n'.[/yellow]")
    except FileNotFoundError:
        console.print(f"[yellow]Local file for {report_type} not found. Defaulting to remote URL.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Failed to load {report_type} from local path ({e}). Trying remote URL.[/yellow]")

    # 2. Try remote (if local failed or user chose 'n')
    try:
        console.print(f"Attempting to load {report_type} for {mission_id} from remote URL: {DEFAULT_REMOTE_DATA_URL}...")
        df = mission_core.load_report(report_type, mission_id, base_url=DEFAULT_REMOTE_DATA_URL)
        console.print(f"[green]Successfully loaded {report_type} from remote URL.[/green]")
        return df
    except Exception as e:
        console.print(f"[red]❌ Failed to load {report_type} from remote URL: {e}[/red]")
        return pd.DataFrame() # Return empty DataFrame on failure to avoid None downstream

def check_power(mission_id, hours_back=72):
    df_power = load_data_interactive("power", mission_id)
    power_status = get_power_status(df_power)
    if not power_status:
        console.print("[red]❌ No power data available[/red]")
        return

    # Display the table
    console.rule("🔌 Power System Status")
    table_data = [
        ("Battery (Wh)", power_status.get("BatteryWattHours")),
        ("Solar Input (W)", power_status.get("SolarInputWatts")),
        ("Power Draw (W)", power_status.get("PowerDrawWatts")), # Changed label for clarity
        ("Net Power (W)", power_status.get("NetPowerWatts")),   # Key is NetPowerWatts
    ]

    power_table = Table() # Use a more specific name to avoid conflict if Table is imported at top
    for label, _ in table_data:
        power_table.add_column(label, justify="right")

    power_table.add_row(*[f"{val:.2f}" if val is not None else "N/A" for _, val in table_data])
    console.print(power_table)

    if power_status.get("NetPowerWatts") is not None and power_status["NetPowerWatts"] < 0:
        console.print("⚠ Battery is discharging")

    # Generate and report the plot
    plot_path = generate_power_plot(df_power, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Power trend plot saved to {plot_path}[/green]")

def check_ctd(mission_id, hours_back=24):
    df_ctd = load_data_interactive("ctd", mission_id)
    status = get_ctd_status(df_ctd)

    if not status:
        console.print("[red]❌ No CTD data available[/red]")
        return

    console.rule("🔬 Latest CTD Reading")
    table = Table(title="Latest CTD Reading")
    table.add_column("Water Temp (°C)") # Changed key
    table.add_column("Salinity (PSU)")
    table.add_column("Conductivity (S/m)")
    table.add_column("O₂ (Hz)") # Corresponds to DissolvedOxygen
    table.add_column("Pressure (dbar)") # Changed from Depth to Pressure

    table.add_row(
        f"{status.get('WaterTemperature'):.2f}" if status.get('WaterTemperature') is not None else "N/A",
        f"{status.get('Salinity'):.2f}" if status.get('Salinity') is not None else "N/A",
        f"{status.get('Conductivity'):.2f}" if status.get('Conductivity') is not None else "N/A",
        f"{status.get('DissolvedOxygen'):.2f}" if status.get('DissolvedOxygen') is not None else "N/A", # Assuming this is the desired output
        f"{status.get('Pressure'):.1f}" if status.get('Pressure') is not None else "N/A", # Changed from Depth to Pressure
    )

    console.print(table)

    plot_path = generate_ctd_plot(df_ctd, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ CTD trend plot saved to {plot_path}[/green]")

def check_weather(mission_id, hours_back=72):
    df_weather = load_data_interactive("weather", mission_id)
    status = get_weather_status(df_weather)

    if not status:
        console.print("[red]❌ No weather data available[/red]")
        return

    console.rule("⛅ Current Weather Conditions")
    table = Table()
    table.add_column("Air Temp (°C)") # Changed key
    table.add_column("Wind (kt)")
    table.add_column("Gust (kt)")
    table.add_column("Direction (°)")

    table.add_row(
        f"{status.get('AirTemperature'):.1f}" if status.get('AirTemperature') is not None else "N/A",
        f"{status.get('WindSpeed'):.1f}" if status.get('WindSpeed') is not None else "N/A",
        f"{status.get('WindGust'):.1f}" if status.get('WindGust') is not None else "N/A",
        f"{int(status.get('WindDirection'))}" if status.get('WindDirection') is not None else "N/A",
    )

    console.print(table)

    plot_path = generate_weather_plot(df_weather, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Weather trend plot saved to {plot_path}[/green]")

def check_waves(mission_id, hours_back=72):
    df_waves = load_data_interactive("waves", mission_id)
    status = get_wave_status(df_waves)

    if not status:
        console.print("[red]❌ No wave data available[/red]")
        return

    console.rule("🌊 Current Wave Conditions")
    table = Table()
    table.add_column("Sig. Wave Height (m)") # Changed key
    table.add_column("Period (s)")
    table.add_column("Mean Direction (°)") # Changed key

    table.add_row(
        f"{status.get('SignificantWaveHeight'):.2f}" if status.get("SignificantWaveHeight") is not None else "N/A",
        f"{status.get('WavePeriod'):.1f}" if status.get("WavePeriod") is not None else "N/A",
        f"{status.get('MeanWaveDirection'):.0f}" if status.get("MeanWaveDirection") is not None else "N/A", # .0f for direction
    )

    console.print(table)

    plot_path = generate_wave_plot(df_waves, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Wave trend plot saved to {plot_path}[/green]")

def check_ais(mission_id, hours_back=24):
    df_ais = load_data_interactive("ais", mission_id)
    vessels = get_ais_summary(df_ais, max_age_hours=hours_back)

    console.rule("🛥️ Nearby Vessels (AIS)")

    if not vessels:
        console.print("[yellow]⚠ No recent AIS data[/yellow]")
        return

    table = Table()
    table.add_column("Ship")
    table.add_column("MMSI", justify="right")
    table.add_column("SOG (kt)", justify="right")
    table.add_column("COG (°)", justify="right")
    table.add_column("Last Seen")

    for vessel in vessels:
        age = datetime.now() - vessel["LastSeenTimestamp"] # Changed key
        last_seen_str = (
            f"{age.days} days ago"
            if age.days > 0
            else f"{age.seconds // 3600} hrs ago"
        )

        table.add_row(
            vessel.get("ShipName", "Unknown"),
            str(vessel.get("MMSI")) if vessel.get("MMSI") is not None else "N/A",
            f"{vessel.get('SpeedOverGround'):.1f}" if vessel.get("SpeedOverGround") is not None else "N/A",
            f"{vessel.get('CourseOverGround'):.0f}" if vessel.get("CourseOverGround") is not None else "N/A",
            last_seen_str
        )
    console.print(table)

def check_errors(mission_id, hours_back=24):
    df_errors = load_data_interactive("errors", mission_id)
    errors = get_recent_errors(df_errors, max_age_hours=hours_back)

    console.rule("⚠️ Recent System Errors")

    if not errors:
        console.print("[green]✅ No recent errors in last 24 hours[/green]")
        return

    table = Table()
    table.add_column("Time")
    table.add_column("System")
    table.add_column("Self Corrected")
    table.add_column("Message")

    for err in errors[:20]:  # limit to most recent 20
        ts = err.get("Timestamp", None) # Changed key
        if ts is not None:
            # Convert pandas Timestamp/datetime to formatted string
            ts = pd.to_datetime(ts)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = "N/A"

        # Convert boolean to Yes/No with color - This block was incorrectly indented
        self_corrected = err.get("SelfCorrected", None) # Changed key
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
            str(err.get("VehicleName", "N/A")), # Changed key
            severity_str,
            str(err.get("ErrorMessage", "N/A")), # Changed key
        )
    console.print(table)

def check_forecast(lat, lon):
    forecast_data = get_open_meteo_forecast(lat, lon)
    if forecast_data:
        display_weather_forecast(forecast_data)
    else:
        console.print("[red]❌ Unable to retrieve weather forecast[/red]")

def check_forecast_with_inference(mission_id, lat=None, lon=None):
    if lat is None or lon is None:
        try:
            df_telemetry = load_data_interactive("telemetry", mission_id)
            if df_telemetry is None or df_telemetry.empty:
                console.print(f"[red]❌ Telemetry data for {mission_id} could not be loaded. Cannot infer location.[/red]")
                return


            df_telemetry["lastLocationFix"] = pd.to_datetime(df_telemetry["lastLocationFix"], errors="coerce")
            df_telemetry = df_telemetry.dropna(subset=["lastLocationFix"])

            latest = df_telemetry.sort_values("lastLocationFix", ascending=False).iloc[0]
            lat = latest.get("latitude") or latest.get("Latitude")
            lon = latest.get("longitude") or latest.get("Longitude")

            if pd.isna(lat) or pd.isna(lon):
                raise ValueError("Missing lat/lon values")

            console.print(f"[cyan]📍 Using telemetry position: {lat:.3f}, {lon:.3f}[/cyan]")

        except Exception as e:
            console.print(f"[red]❌ Unable to infer lat/lon from telemetry: {e}[/red]")
            return

    check_forecast(lat, lon)

if __name__ == "__main__":
    main()
