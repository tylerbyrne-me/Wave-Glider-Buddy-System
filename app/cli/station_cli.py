# app/cli/cli.py
import json
import os
from pathlib import Path

import httpx  # For making API calls to our own app
import pandas as pd
import typer
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

# --- SECURITY: All credentials and URLs must come from environment variables ---
# Base API URL - can be overridden via CLI_ADMIN_API_URL environment variable
BASE_API_URL = os.getenv("CLI_ADMIN_API_URL", "http://localhost:8000/api")

# Admin credentials - MUST be set in environment variables
ADMIN_USERNAME = os.getenv("CLI_ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("CLI_ADMIN_PASSWORD")

app_cli = typer.Typer(help="Wave Glider Buddy System Command Line Interface.")
console = Console()


def get_admin_token():
    """
    Helper to get an admin token.
    SECURITY: Credentials must be provided via environment variables.
    """
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        console.print(
            "[bold red]Error: CLI_ADMIN_USERNAME and CLI_ADMIN_PASSWORD environment variables must be set.[/bold red]"
        )
        console.print(
            "[yellow]Please set these in your .env file or environment before running CLI commands.[/yellow]"
        )
        return None
    
    try:
        token_url = BASE_API_URL.replace(
            "/api", "/token"
        )  # Token endpoint is at the app root
        console.print(
            f"Attempting to get admin token from: [cyan]{token_url}[/cyan] for user [yellow]{ADMIN_USERNAME}[/yellow]"
        )
        response = httpx.post(
            token_url, data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        response.raise_for_status()
        token_data = response.json()
        console.print("[green]Successfully obtained admin token.[/green]")
        return token_data["access_token"]
    except httpx.HTTPStatusError as e:
        console.print(
            f"[bold red]HTTP Error getting admin token: {e.response.status_code} - {e.response.text}[/bold red]"
        )
    except httpx.RequestError as e:
        console.print(f"[bold red]Request Error getting admin token: {e}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Unexpected error getting admin token: {e}[/bold red]")
    return None


@app_cli.command()
def import_station_metadata(
    csv_file: Annotated[
        Path,
        typer.Option(
            help="Path to the CSV file containing station metadata.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
):
    """
    Imports station metadata from a CSV file into the database via the API.
    Expected CSV headers: station_id,serial_number,modem_address,bottom_depth_m,waypoint_number,last_offload_by_glider,station_settings,notes
    """
    console.print(
        f"Attempting to import station metadata from: [cyan]{csv_file}[/cyan]"
    )

    try:
        df = pd.read_csv(
            csv_file, dtype=str
        )  # Read all as string initially to preserve formatting like leading zeros
    except Exception as e:
        console.print(f"[bold red]Error reading CSV file '{csv_file}': {e}[/bold red]")
        raise typer.Exit(code=1)

    expected_headers = [
        "station_id",
        "serial_number",
        "modem_address",
        "bottom_depth_m",
        "waypoint_number",
        "last_offload_by_glider",
        "station_settings",
        "notes",
    ]

    if "station_id" not in df.columns:
        console.print(
            f"[bold red]CSV file must contain a 'station_id' column.[/bold red]"
        )
        raise typer.Exit(code=1)

    admin_token = get_admin_token()
    if not admin_token:
        console.print(
            "[bold red]Could not authenticate as admin. Aborting import.[/bold red]"
        )
        raise typer.Exit(code=1)

    api_headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    }
    success_count = 0
    fail_count = 0
    skipped_count = 0

    # Use a session for multiple requests
    with httpx.Client(
        base_url=BASE_API_URL, headers=api_headers, timeout=20.0
    ) as client:
        for index, row in df.iterrows():
            station_id = row.get("station_id")
            if pd.isna(station_id) or not str(station_id).strip():
                console.print(
                    f"[yellow]Skipping row {index+2} due to missing or empty station_id.[/yellow]"
                )
                skipped_count += 1
                continue

            payload = {"station_id": str(station_id).strip()}  # station_id is mandatory

            for header in expected_headers:
                if header == "station_id":  # Already handled
                    continue
                if header in row and pd.notna(row[header]):
                    value = str(row[header]).strip()
                    if not value:  # Skip empty strings after stripping
                        continue

                    if header == "modem_address":
                        try:
                            payload[header] = int(value)
                        except ValueError:
                            console.print(
                                f"[yellow]Warning for station '{station_id}': Invalid modem_address '{value}'. Skipping field.[/yellow]"
                            )
                    elif header == "bottom_depth_m":
                        try:
                            payload[header] = float(value)
                        except ValueError:
                            console.print(
                                f"[yellow]Warning for station '{station_id}': Invalid bottom_depth_m '{value}'. Skipping field.[/yellow]"
                            )
                    else:
                        payload[header] = value

            # Correctly construct the URL for logging and ensure the post path is relative
            target_path = "station_metadata/"
            full_post_url = (
                f"{str(client.base_url).rstrip('/')}/{target_path.lstrip('/')}"
            )
            console.print(
                f"Processing station: [blue]{station_id}[/blue], Payload: {payload}"
            )
            console.print(f"  Attempting POST to: [cyan]{full_post_url}[/cyan]")
            try:
                response = client.post(target_path, json=payload)  # Use relative path
                if response.status_code == 201:  # Created
                    console.print(
                        f"  [green]Successfully CREATED station: {station_id}[/green]"
                    )
                    success_count += 1
                elif (
                    response.status_code == 200
                ):  # OK (likely updated if your POST also handles updates)
                    console.print(
                        f"  [green]Successfully UPDATED station: {station_id}[/green]"
                    )
                    success_count += 1
                else:
                    error_detail = "Unknown error"
                    try:
                        error_detail = response.json().get("detail", response.text)
                    except json.JSONDecodeError:
                        error_detail = response.text
                    console.print(
                        f"  [red]Failed for station '{station_id}': {response.status_code} - {error_detail}[/red]"
                    )
                    fail_count += 1
            except httpx.RequestError as e_req:
                console.print(
                    f"  [red]Request error for station '{station_id}': {e_req}[/red]"
                )
                fail_count += 1
            except Exception as e_gen:
                console.print(
                    f"  [red]Generic error processing station '{station_id}': {e_gen}[/red]"
                )
                fail_count += 1

    console.print(f"\n[bold blue]Import complete.[/bold blue]")
    console.print(
        f"  Successfully processed (created/updated): [green]{success_count}[/green]"
    )
    console.print(f"  Failed: [red]{fail_count}[/red]")
    console.print(f"  Skipped (missing station_id): [yellow]{skipped_count}[/yellow]")


@app_cli.command()
def hello(name: str = "World"):
    """A simple test command."""
    console.print(f"Hello {name} from the Wave Glider Buddy CLI!")


if __name__ == "__main__":
    # This allows running the CLI directly using `python -m app.cli.station_cli import-station-metadata ...`
    # Make sure your project structure allows this import path.
    # You might need to adjust PYTHONPATH or run from the project root.
    app_cli()
