# Wave Glider Buddy System

The Wave Glider Buddy System is a web application designed to monitor and visualize data from Wave Glider missions. It provides a dynamic dashboard interface, with globally scaled UI elements for denser information display (emulating ~67% browser zoom), to display various sensor readings, data trends, and relevant forecasts, helping users stay informed about ongoing and past missions.

## High-Order Logic


The system operates by:
1.  Fetching mission data from configured remote servers or local file paths.
2.  Prioritizing data from `output_realtime_missions` for active missions and `output_past_missions` for completed ones.
3.  Processing and summarizing the raw data for various sensor types (Power, CTD, Weather, Waves, AIS, Errors).
4.  Displaying key status indicators and recent values on a web-based dashboard, with important alerts like AIS contacts and system errors highlighted.
5.  Generating interactive charts (using Chart.js on the frontend) to visualize data trends over time.
6.  Fetching and displaying weather forecasts relevant to the mission's location (inferred from telemetry if not provided).
7.  Implementing a caching mechanism to improve performance and reduce load on data sources, with specific strategies for real-time (time-based expiry) and static/past data.
    *   Data processing ensures consistent UTC timestamps and robust handling of various data formats.
8.  Proactively refreshing the cache for active real-time missions using a background scheduler.
9.  Allowing users to manually trigger a full data refresh.
10. Storing user accounts persistently in an SQLite database, with default users created on first run if the database is empty.
11. Automatically refreshing the dashboard page for missions designated as "real-time" to provide users with up-to-date information.
12. Fetching distinct general weather forecasts (temperature, precipitation, wind) and marine-specific forecasts (waves, currents), with location inferred from telemetry if not provided.
    *   General weather forecast is displayed in the "Weather" sensor detail view.
    *   Marine forecast is displayed in the "Waves" sensor detail view.
## Core Features
*   **Mission Forms (Initial Implementation):**
    *   Ability to define form structures (schemas) with sections and various item types (checkbox, text input, text area, auto-filled values).
    *   Dedicated HTML page for filling out forms.
    *   API endpoints to serve form templates (with basic auto-fill for some fields like battery percentage) and accept form submissions.
    *   Submitted forms can be stored in a local JSON file (`data_store/submitted_forms.json`) or an SQLite database (`data_store/forms.sqlite`) for development/testing.
        *   This is configurable via `FORMS_STORAGE_MODE` and `SQLITE_DATABASE_URL` in `.env`.
    *   Accessible via a "Create Report" button on the main dashboard.

*   **User Authentication and Role-Based Access:**
    *   Secure login system using JWT (JSON Web Tokens).
    *   User accounts are stored persistently in an SQLite database.
    *   Two-tier user hierarchy:
        *   **Admin Users:** Full access to all missions (real-time and past), ability to register new users, and manage existing user accounts.
        *   **Pilot Users:** Access restricted to designated active real-time missions.
    *   Client-side logic dynamically populates mission lists and UI elements (e.g., "Register New User" button) based on the authenticated user's role.
    *   Protected API endpoints requiring valid authentication tokens.
*   **Admin-Controlled User Registration:**
    *   New users are registered by an administrator through a dedicated registration page accessible only to admins.
    *   Registered users default to the 'pilot' role.
    *   Registration includes username, email, and password. User data is stored in the SQLite database.
*   **Admin User Management:**
    *   A dedicated "User Management" page accessible only to administrators.
    *   Admins can view all registered users.
    *   Admins can edit user details (full name, email).
    *   Admins can change user roles (admin to pilot, pilot to admin).
    *   Admins can change user passwords.
    *   Admins can disable or enable user accounts.
*   **Dynamic Dashboard Interface:**
    *   Redesigned dashboard with a left-hand navigation panel displaying summary "cards" for each sensor/data type.
    *   Each summary card includes key metrics and a compact mini-trend chart for at-a-glance status (Power: Charge Rate; CTD: Water Temp; Weather: Wind Speed; Waves: Sig. Wave Height; VR2C: Detection Count; Fluorometer: C1 Avg).
    *   Each summary card includes key metrics and a compact mini-trend chart for at-a-glance status (Power: Charge Rate; CTD: Water Temp; Weather: Wind Speed; Waves: Sig. Wave Height; VR2C: Detection Count; Fluorometer: C1 Avg).
        *   Mini-chart data for CTD, Weather, Waves, and Fluorometer is smoothed using a 1-hour average.
        *   The "Errors" mini-summary card now displays the last 1-2 error messages directly in the mini-chart placeholder area, with a correctly positioned red exclamation mark indicator for active errors.
    *   Clicking a summary card dynamically loads its detailed view (expanded summary data and large trend chart) into the main content area.
    *   The active summary card is highlighted with a subtle, dark-mode friendly style.
    *   Mini-summary cards are formatted with the mini-chart on the left and title/summary text on the right for a clean, consistent layout, including cards without charts (AIS, Errors) which use placeholders for alignment.
*   **Enhanced Power Monitoring:**
    *   Power mini-summary card displays Battery Percentage and "Net" (which is the Battery Charge Rate, formatted to one decimal place).
    *   Integration of "Amps Solar Input Port Report.csv" for detailed solar panel performance.
    *   The detailed Power view now features:
        *   A "Task Manager" style three-column layout:
            *   Column 1: Battery %, Charge Rate (W), Time to Full.
            *   Column 2: Battery Capacity (Wh), Avg Output (24h).
            *   Column 3: Current Solar Input, 24h Avg Solar Input, Panel 1, Panel 2, Panel 3 inputs.
        *   A primary chart for main power trends (e.g., Battery Wh, Power Draw).
        *   A secondary chart dedicated to solar performance, displaying individual panel power (Panel 1, Panel 2 from `panelPower3`, Panel 4) and Total Solar Input, utilizing dual y-axes for clarity and improved x-axis alignment.
*   **Comprehensive Data Display:** Visualizes Power, CTD, Weather Sensor, Wave, AIS, Vehicle Error, VR2C, and Fluorometer data.
    *   **CTD Module:**
        *   Redesigned main summary area into a two-column layout:
            *   Column 1: Water Temperature, Conductivity, Salinity (large font).
            *   Column 2: List of Dissolved Oxygen, 24h High/Low Water Temp, Pressure.
        *   Added a second main chart: Water Temperature (Y1 Left, more transparent), Conductivity (Y Right, more transparent), and Dissolved Oxygen (Y2 Left, hidden axis, opaque).
    *   **Weather Module:**
        *   Redesigned main summary area into a three-column layout:
            *   Column 1: Wind Speed, Wind Direction (large font).
            *   Column 2: Gust Speed, Gust Direction (large font).
            *   Column 3: List of Last Air Temp, 24h High/Low Air Temp, Last Pressure, 24h High/Low Pressure.
        *   Ensured correct mapping of `avgPress(mbar)` for pressure data.
    *   **Waves Module:**
        *   Redesigned main summary area into a three-column layout:
            *   Column 1: Wave Height (Hs), 24h Avg Hs (large font).
            *   Column 2: Wave Direction (Dp) (large font) with a minimalist arrow indicator (no label) for wave propagation direction.
            *   Column 3: List of Wave Amplitude (A), Period (Tp), and color-coded Sample Gaps (0-2: default, 2-10: yellow, >10: red).
        *   Added new main charts:
            *   Wave Height vs. Wave Direction.
            *   Wave Amplitude (Left Y-axis).
            *   Wave Amplitude (Right Y-axis).
    *   Also includes support for VR2C-MRx Acoustic Receiver and C3 Fluorometer data.
*   **Trend Analysis:** Interactive charts for key metrics (e.g., battery levels, water temperature, wind speed, wave height) over the last 72 hours (configurable).
*   **Enhanced Alert Display:** AIS and Errors sections are collapsible and will auto-expand or show visual indicators (❗) when new or relevant data is present.
*   **Weather Forecasts:** Integrates with the Open-Meteo API to provide:
    *   **General Weather Forecast:** Displayed in the "Weather" detail view, showing air temperature, precipitation, and wind conditions. Location is inferred from telemetry if not explicitly provided.
    *   **Marine Forecast:** Displayed in the "Waves" detail view, showing wave height, period, direction, and ocean current data. Location is inferred from telemetry if not explicitly provided.
*   **Multi-Mission Support:** Allows users to select and view data for different configured missions.
*   **Flexible Data Sourcing:** Can load data from remote HTTP servers or local file systems.
*   **Robust Data Processing:** Standardized timestamp handling (UTC throughout), consistent column naming, and improved handling of missing or malformed data across different sensor types.
*   **Intelligent Caching:**
    *   In-memory caching of processed data to speed up load times.
    *   Time-based expiration for data from active, real-time missions (e.g., every 15-60 minutes).
    *   Longer-term caching for static past mission data and local files.
*   **Background Cache Refresh:** A scheduled background task (using APScheduler) proactively updates the cache for designated active real-time missions.
*   **User-Triggered Refresh:** A "Refresh Data" button allows users to bypass the cache and fetch the latest data on demand.
*   **Auto-Page Refresh:** For missions marked as "real-time," the webpage automatically refreshes every 5 minutes to display potentially new data, with a visible countdown timer.
*   **UTC Timestamps & Logging:** Consistent use of UTC for timestamps and detailed logging to both console and a persistent `app.log` file for easier debugging and monitoring.
*   **Code Quality:** Removed numerous debugging `print`/`logger` statements and `console.log` calls from Python backend (summaries, processors, app, loaders) and JavaScript (dashboard).

## Technology Stack

*   **Backend:**
    *   Python 3.12+
    *   FastAPI (for the web framework and API)
    *   Uvicorn (as the ASGI server, can be run with Gunicorn for production)
    *   Passlib with bcrypt (for password hashing)
    *   python-jose (for JWT creation and validation)
    *   Pandas (for data manipulation and analysis)
    *   httpx (for HTTP client requests to data sources and APIs)
    *   APScheduler (for background cache refresh tasks)
    *   SQLModel (for database interaction with SQLite)
    *   Pydantic (for settings management)
*   **Frontend:**
    *   HTML5 (structured with Jinja2 templating)
    *   CSS3 (styled with Bootstrap 5 and custom CSS)
    *   JavaScript (for dynamic content, Chart.js for plotting, authentication handling)

## Project Structure Overview

```
.
├── app/                     # Core backend application
│   ├── core/                # Core logic modules (loaders, processors, summaries, forecast, etc.)
│   │   ├── __init__.py
│   │   ├── forecast.py
│   │   ├── loaders.py
│   │   ├── plotting.py      # (If server-side plot generation is used, e.g., for CLI)
│   │   ├── processors.py
│   │   ├── summaries.py
│   │   └── utils.py
│   │   └── security.py      # JWT and password hashing utilities
│   ├── cli/                 # Command-line interface components
│   │   └── cli.py           
│   ├── __init__.py
│   ├── app.py               # Main FastAPI application instance
│   ├── config.py            # Application settings management
│   ├── db.py                # Database engine and session management
│   └── auth_utils.py        # User authentication helper functions and dependencies
├── web/                     # Frontend files
│   ├── static/              # Static assets
│   │   ├── css/
│   │   │   └── custom.css
│   │   └── js/
│   │       ├── dashboard.js
│   │       ├── auth.js      # Client-side authentication logic
│   │       ├── mission_form.js
│   │       ├── view_forms.js
│   │       └── admin_user_management.js # JS for admin user management page
│   └── templates/           # HTML templates (Jinja2)
│       ├── index.html, login.html, register.html, mission_form.html, view_forms.html
│       └── admin_user_management.html # Admin user management page
├── .env                     # (Optional) Environment variables for configuration
├── app.log                  # Application log file (path configurable via .env)
└── README.md                # This file
```

## Setup and Running

1.  **Prerequisites:**
    *   Python 3.12 or higher.
    *   A Conda environment is recommended for managing dependencies.

2.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd Wave-Glider-Buddy-System
    ```

3.  **Create and Activate Conda Environment:**
    ```bash
    conda create --name gliderenv python=3.12
    conda activate gliderenv
    ```

4.  **Install Dependencies:**
    It's assumed you have a `requirements.txt` file (if not, create one based on your imports: `fastapi`, `uvicorn[standard]`, `pandas`, `numpy`, `httpx`, `apscheduler`, `pydantic-settings`, `python-dotenv`).
    Key dependencies include:
    ```bash
    pip install fastapi uvicorn[standard] pandas numpy httpx apscheduler pydantic-settings python-dotenv "passlib[bcrypt]" python-jose sqlmodel
    ```
5.  **Configuration:**
    *   Review and update `app/config.py` for default settings.
    *   For server deployments or to override defaults, create a `.env` file in the project root directory (next to `app/`) with necessary environment variables (e.g., `LOCAL_DATA_BASE_PATH`, `REMOTE_DATA_URL`, `ACTIVE_REALTIME_MISSIONS`). Example:
        ```env
        LOCAL_DATA_BASE_PATH="/path/to/your/local/data"
        ACTIVE_REALTIME_MISSIONS='["mission1", "mission2"]' # JSON string format for lists
        ```
    *   On the first run, or if the `data_store/app_data.sqlite` file is deleted, the application will create the SQLite database and populate it with default users (adminuser, pilotuser, pilot_rt_only).

6.  **Database Initialization:**
    *   Ensure the `data_store` directory exists in the project root, or the application will attempt to create it. The SQLite database file (`app_data.sqlite`) will be created inside `data_store`.

6.  **Running the Application (Development):**
    Navigate to the project root directory (the one containing the `app` folder) and run:
    ```bash
    uvicorn app.app:app --reload --host 0.0.0.0 --port 8000
    ```
    *   `--reload`: Enables auto-reloading on code changes.
    *   `--host 0.0.0.0`: Makes the app accessible on your local network.
    *   `--port 8000`: Specifies the port.

7.  **Running the Application (Server/Production-like):**
    For a more robust setup on a server (especially Linux), use Gunicorn to manage Uvicorn workers:
    ```bash
    gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.app:app -b 0.0.0.0:8000
    ```
    Consider running this as a systemd service for persistence (see deployment notes/scripts for details).

8.  **Accessing the Application:**
    Open your web browser and navigate to `http://localhost:8000` (or `http://<server_ip>:8000` if running on a server and accessing from another machine).

## Logging

*   Log messages are output to both the console and the `app.log` file in the project root.
*   Timestamps in logs are in UTC.
*   Log level is set to INFO by default.

## Future Considerations


*   **Advanced Cache Management:** Implement LRU (Least Recently Used) or TTL (Time To Live) cache eviction strategies using libraries like `cachetools` to manage memory usage more effectively.
*   **User Authentication/Authorization:** If the application needs to be secured.
*   **Database Migrations:** Implement a database migration strategy (e.g., using Alembic with SQLModel) if the database schema (especially for `UserInDB` or `SubmittedForm`) is expected to change after initial deployment with data.
*   **UI/UX Enhancements:** More granular refresh controls, customizable dashboards, etc.
*   **Error Handling & Resilience:** Further improvements to error handling and reporting.
*   **Password Security:**
    *   While Passlib with bcrypt provides strong hashing, for extremely high-security environments, consider policies around password complexity, rotation, and lockout mechanisms (though these are often application-level logic on top of hashing).
    *   Ensure the environment where the application runs (including the database file) is secured to prevent unauthorized access to the hashed passwords.

---

## Acknowledgements

*   Weather forecast data generated using ICON Wave forecast from the German Weather Service DWD via the <a href="https://open-meteo.com/" target="_blank">Open-Meteo.com</a> API.
*   Coding assistance and suggestions provided by Google's Gemini models.