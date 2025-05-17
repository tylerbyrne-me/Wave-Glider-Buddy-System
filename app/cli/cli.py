from mission_core import load_report, get_power_status, generate_power_plot, generate_ctd_plot, get_ctd_status, get_weather_status, generate_weather_plot, get_wave_status, generate_wave_plot, get_ais_summary, get_recent_errors, get_open_meteo_forecast, display_weather_forecast
from rich.console import Console
from rich.table import Table
from datetime import datetime, timedelta
import pandas as pd
import argparse
import math

# Set to None for local, or URL for remote
BASE_URL = None

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

def load_mission_report(report_type, mission_id):
    return load_report(report_type, mission_id, base_url=BASE_URL)

def check_power(mission_id, hours_back=72):
    df_power = load_mission_report("power", mission_id)
    power_status = get_power_status(df_power)
    if not power_status:
        console.print("[red]❌ No power data available[/red]")
        return

    # Display the table
    console.rule("🔌 Power System Status")
    table_data = [
        ("Battery (watt-hours)", power_status["BatteryWattHours"]),
        ("Solar Input (W)", power_status["SolarInputWatts"]),
        ("Output Power (W)", power_status["PowerDrawWatts"]),
        ("Net Power (W)", power_status["NetPower"]),
    ]

    from rich.table import Table
    table = Table()
    for label, _ in table_data:
        table.add_column(label, justify="right")

    table.add_row(*[f"{val:.2f}" if val is not None else "N/A" for _, val in table_data])
    console.print(table)

    if power_status["NetPower"] is not None and power_status["NetPower"] < 0:
        console.print("⚠ Battery is discharging")

    # Generate and report the plot
    plot_path = generate_power_plot(df_power, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Power trend plot saved to {plot_path}[/green]")

def check_ctd(mission_id, hours_back=24):
    df_ctd = load_mission_report("ctd", mission_id)
    status = get_ctd_status(df_ctd)

    if not status:
        console.print("[red]❌ No CTD data available[/red]")
        return

    console.rule("🔬 Latest CTD Reading")
    table = Table(title="Latest CTD Reading")
    table.add_column("Temp (°C)")
    table.add_column("Salinity (PSU)")
    table.add_column("Conductivity (S/m)")
    table.add_column("O₂ (Hz)")
    table.add_column("Depth (m)")

    table.add_row(
        f"{status['Temperature']:.2f}" if status['Temperature'] else "N/A",
        f"{status['Salinity']:.2f}" if status['Salinity'] else "N/A",
        f"{status['Conductivity']:.2f}" if status['Conductivity'] else "N/A",
        f"{status['DissolvedOxygen']:.2f}" if status['DissolvedOxygen'] else "N/A",
        f"{status['Depth']:.1f}" if status['Depth'] else "N/A",
    )

    console.print(table)

    plot_path = generate_ctd_plot(df_ctd, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ CTD trend plot saved to {plot_path}[/green]")

def check_weather(mission_id, hours_back=72):
    df_weather = load_mission_report("weather", mission_id)
    status = get_weather_status(df_weather)

    if not status:
        console.print("[red]❌ No weather data available[/red]")
        return

    console.rule("⛅ Current Weather Conditions")
    table = Table()
    table.add_column("Temp (°C)")
    table.add_column("Wind (kt)")
    table.add_column("Gust (kt)")
    table.add_column("Direction (°)")

    table.add_row(
        f"{status['Temp']:.1f}" if status['Temp'] else "N/A",
        f"{status['WindSpeed']:.1f}" if status['WindSpeed'] else "N/A",
        f"{status['Gust']:.1f}" if status['Gust'] else "N/A",
        f"{int(status['Direction'])}" if status['Direction'] else "N/A",
    )

    console.print(table)

    plot_path = generate_weather_plot(df_weather, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Weather trend plot saved to {plot_path}[/green]")

def check_waves(mission_id, hours_back=72):
    df_waves = load_mission_report("waves", mission_id)
    status = get_wave_status(df_waves)

    if not status:
        console.print("[red]❌ No wave data available[/red]")
        return

    console.rule("🌊 Current Wave Conditions")
    table = Table()
    table.add_column("Wave Height (m)")
    table.add_column("Period (s)")
    table.add_column("Direction (°)")

    table.add_row(
        f"{status['Height']:.2f}" if status["Height"] else "N/A",
        f"{status['Period']:.1f}" if status["Period"] else "N/A",
        f"{status['Direction']:.2f}" if status["Direction"] else "N/A",
    )

    console.print(table)

    plot_path = generate_wave_plot(df_waves, mission_id, hours_back)
    if plot_path:
        console.print(f"[green]✅ Wave trend plot saved to {plot_path}[/green]")

def check_ais(mission_id, hours_back=24):
    df_ais = load_mission_report("ais", mission_id)
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
        age = datetime.now() - vessel["last_seen"]
        last_seen_str = (
            f"{age.days} days ago"
            if age.days > 0
            else f"{age.seconds // 3600} hrs ago"
        )

        table.add_row(
            vessel["name"],
            str(vessel["mmsi"]) if vessel["mmsi"] else "N/A",
            f"{vessel['sog']:.1f}" if vessel["sog"] else "N/A",
            f"{vessel['cog']:.0f}" if vessel["cog"] else "N/A",
            last_seen_str
        )

    console.print(table)

def check_errors(mission_id, hours_back=24):
    df_errors = load_mission_report("errors", mission_id)
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

    # MAKE histogram of historical errors to look at rates and severity to define a limit
    for err in errors[:20]:  # limit to most recent 20
        ts = err.get("timeStamp", None)
        if ts is not None:
            # Convert pandas Timestamp/datetime to formatted string
            ts = pd.to_datetime(ts)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = "N/A"

# Convert boolean to Yes/No with color
    self_corrected = err.get("selfCorrected", None)
    if isinstance(self_corrected, bool):
        severity_str = "[yellow]Yes[/yellow]" if self_corrected else "[red]No[/red]"
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
        str(err.get("vehicleName", "N/A")),
        severity_str,
        str(err.get("error_Message", "N/A")),
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
            df_telemetry = load_report("telemetry", mission_id, base_url=BASE_URL)
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











