# Wave Glider Buddy System

A comprehensive web application designed to support Wave Glider missions by providing real-time data dashboards, pilot scheduling, mission planning, and administrative tools.

## High-Order Logic


The system operates by:
1.  Providing a central **Home Page Hub** with a dynamic, tabbed interface for active mission overviews, goals, and operational notes.
1.  Fetching mission data from configured remote servers or local file paths.
2.  Prioritizing data from `output_realtime_missions` for active missions and `output_past_missions` for completed ones.
3.  Defaults to displaying the first mission from the configured active real-time list on initial load. If no active missions are set, it falls back to the first available mission.
4.  Processing and summarizing the raw data for various sensor types (Power, CTD, Weather, Waves, AIS, Errors).
5.  Managing a daily shift schedule for pilots, with the ability to link submitted PIC Handoff forms directly to the shifts during which they were completed.
6.  Managing station metadata (ID, serial number, modem address, etc.) through dedicated API endpoints, with a CLI tool for bulk import from CSV files.
7.  Tracking and displaying the offload status of WG-VM4 stations, indicating which have been recently serviced and which require attention.
8.  Displaying key status indicators and recent values on a web-based dashboard, with important alerts like AIS contacts and system errors highlighted.
9.  Generating interactive charts (using Chart.js on the frontend) to visualize data trends over time.
10. Fetching and displaying weather forecasts relevant to the mission's location (inferred from telemetry if not provided). This includes both a general weather forecast and a marine-specific forecast.
11. Implementing a caching mechanism to improve performance and reduce load on data sources, with specific strategies for real-time (time-based expiry) and static/past data. Data processing ensures consistent UTC timestamps and robust handling of various data formats.
12. Proactively refreshing the cache for active real-time missions using a background scheduler (APScheduler).
13. Allowing users to manually trigger a full data refresh from the main dashboard.
14. Storing user accounts, pay periods, and timesheets persistently in an SQLite database.
15. Automatically refreshing the dashboard page for missions designated as "real-time" to provide users with up-to-date information.
16. Providing a reporting page for administrators to generate and download monthly timesheet summaries as CSV files, complete with a bar chart visualizing hours per pilot.
## Core Features
*   **Mission Forms & Station Logs:**
    *   **Home Page Hub**: A central landing page featuring a dynamic, tabbed interface for active mission overviews. Users can quickly view mission goals and add operational notes.
    *   **Enhanced Authentication**: Implemented a robust `HttpOnly` cookie-based authentication system to seamlessly support both server-rendered pages and client-side API calls, resolving previous login redirect loops.
    *   **New API Endpoints**: Added dedicated, lightweight API endpoints to efficiently populate summary panels (Upcoming Shifts, Timesheet Status) on the home page.
    *   **Dynamic DOM Updates**: Refactored JavaScript to dynamically add, update, and delete mission goals and notes without requiring a full page reload, providing a smoother user experience.
*   **Real-time Mission Dashboard:**
    *   Interactive data visualization for a wide range of sensor reports, including Power, CTD, Weather, Waves, AIS, and more.
*   **Shift Scheduling:**
    *   A full-featured, interactive calendar for managing pilot shifts, unavailability, and LRI block-out periods. Schedule data can be exported to ICS or CSV.
    *   Ability to define form structures (schemas) with sections and various item types (checkbox, text input, text area, auto-filled values).
    *   Dedicated HTML page for filling out forms.
    *   API endpoints to serve form templates (with basic auto-fill for some fields like battery percentage) and accept form submissions.
    *   Submitted forms are stored persistently in the SQLite database.
    *   **Enhanced PIC Handoff Navigation:** The main navigation includes a "PIC Handoff" dropdown with quick links to:
        *   Submit a new PIC Handoff for the currently selected mission.
        *   View all of the current user's past PIC Handoff submissions.
        *   Forms (e.g., PIC Handoff) opened from the dashboard now open in a new browser tab, allowing the main dashboard to remain open.
        *   View all PIC Handoffs submitted across all missions in the last 24 hours.
    *   **WG-VM4 Offload Log:** A specialized form integrated into the WG-VM4 sensor detail view, allowing users to search for station metadata and log offload parameters and results.
*   **Station Metadata Management:**
    *   Dedicated API endpoints (`/api/station_metadata/`) for creating, updating, and retrieving detailed station metadata (ID, serial number, modem address, depth, notes, last offload timestamp, last offload by glider, etc.).
    *   These endpoints are protected and require admin privileges for creation/updates.
    *   A command-line interface (CLI) tool (`app/cli/station_cli.py`) for bulk importing station metadata from CSV files, facilitating easy setup and updates of station information.
    *   Admins can also upload a CSV of station metadata directly through the "Station Offload Status" page UI.
*   **Station Offload Status Page:**
    *   Provides an "at-a-glance" view for all users, showing which WG-VM4 stations have been offloaded and which remain to be offloaded.
    *   Displays status as "Awaiting Offload", "Offloaded", "Failed Offload", or "Skipped".
    *   Uses color-coding for quick status identification.
    *   Includes functionality to sort by various columns and filter the station list.
    *   Allows admin users to download the station offload status list as a CSV file.
        *   The CSV can be filtered by the current search term.
        *   Admins can also download CSVs for specific station groups (e.g., CBS*, NCAT*) directly from a dropdown menu.
        *   The downloaded CSV includes comprehensive details from the latest offload log for each station (arrival date, VRL file name, offload success, notes, etc.).
    *   Allows authenticated users to click on a station ID to open a modal for:
        *   Editing core station information (serial number, modem address, settings, notes, display status override).
        *   **Dynamic Forms Engine**: A system for creating and submitting mission-specific forms, such as PIC Handoffs and WG-VM4 Offload Logs.
        *   Logging new offload attempts with detailed parameters (arrival/departure dates, VRL file name, success status, notes/file size).
*   **User Authentication and Role-Based Access:**
    *   Secure login system using JWT (JSON Web Tokens).
    *   User accounts are stored persistently in an SQLite database.
    *   Two-tier user hierarchy:
        *   **Admin Users:** Full access to all missions (real-time and past), ability to register new users, and manage existing user accounts.
        *   **Pilot Users:** Access restricted to designated active real-time missions.
    *   Client-side logic dynamically populates mission lists and UI elements (e.g., "Register New User" button) based on the authenticated user's role.
    *   Protected API endpoints requiring valid authentication tokens.
    *   **User & Announcement Management**: Secure, role-based access control (Admin, Pilot) and a system for posting and acknowledging site-wide announcements.
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
*   **Daily Shift Schedule & PIC Handoff Integration:**
    *   Provides an interactive schedule view with multiple display options (month, week, day, list) and intuitive navigation. Utilizes the FullCalendar JavaScript library for rendering.
    *   Shift assignments are stored persistently in the SQLite database, linked to user accounts.
    *   Users can only unassign themselves from their own shifts, while admins can manage all shifts.
    *   Shift events are displayed in a minimalist, color-coded format (by user), with full details (including pilot's name) available on click.
    *   User unavailability periods are clearly marked as all-day blocks, color-coded by user role.
    *   **PIC Handoff Linking:** Clicking on a shift in the schedule displays any PIC Handoff forms submitted during that shift's timeframe, providing direct contextual access for incoming pilots.
    *   **Schedule Downloads:** Users can download the schedule for a selected date range as an `.ics` (iCalendar) or `.csv` file, scoped to "All Users" or just their own shifts.
    *   **Visual Cues:** The schedule highlights the current day, uses user-specific colors for shifts, and intelligently manages event display in the month view for readability.
*   **Payroll and Timesheet Management:**
    *   **Timesheet & Payroll System**: Enables pilots to submit timesheets based on their scheduled hours. Provides an administrative interface for reviewing, approve, and generating payroll reports.
    *   Administrators can create and manage pay periods (e.g., "June 1-15, 2025").
    *   Pilots can automatically calculate their total shift hours for any open pay period.
    *   A streamlined submission process allows pilots to submit their calculated hours with optional notes.
    *   Admins have a dedicated interface to review all submitted timesheets for a selected pay period.
    *   Admins can approve, reject, or adjust hours for any submission, providing required feedback via reviewer notes.
    *   **Resubmission Workflow:** If a timesheet is rejected, the pilot is notified of the reason on their home page and can correct and resubmit their timesheet for the same period.
    *   **Home Page Status:** A "My Timesheet Status" panel on the home page provides pilots with real-time visibility into the status (Submitted, Approved, Rejected) of their recent submissions.
    *   Admins can export all timesheet data for a pay period to a CSV file for external processing.
*   **Dynamic Dashboard Interface:**
    *   Redesigned dashboard with a left-hand navigation panel displaying summary "cards" for each sensor/data type.
    *   Each summary card includes key metrics and a compact mini-trend chart for at-a-glance status (Power: Charge Rate; CTD: Water Temp; Weather: Wind Speed; Waves: Sig. Wave Height; VR2C: Detection Count; Fluorometer: C1 Avg).
    *   Includes a summary card for WG-VM4 with key metrics (Serial Number, Channel 0 Detections) and a mini-trend chart (Channel 0 Detections).
        *   Mini-chart data for CTD, Weather, Waves, and Fluorometer is smoothed using a 1-hour average.
        *   The "Errors" mini-summary card now displays the last 1-2 error messages directly in the mini-chart placeholder area, with a correctly positioned red exclamation mark indicator for active errors.
    *   Clicking a summary card dynamically loads its detailed view (expanded summary data and large trend chart) into the main content area.
    *   The active summary card is highlighted with a subtle, dark-mode friendly style.
    *   Mini-summary cards are formatted with the mini-chart on the left and title/summary text on the right for a clean, consistent layout, including cards without charts (AIS, Errors) which use placeholders for alignment.
*   **WG-VM4 Sensor Integration:**
    *   Support for processing and displaying data from WG-VM4 acoustic receiver sensors.
    *   The WG-VM4 detail view includes a summary of health data, a trend chart for detection counts, and an integrated form for logging station offload operations.
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
*   **Comprehensive Data Display:** Visualizes Power, CTD, Weather Sensor, Wave, AIS, Vehicle Error, VR2C, Fluorometer, and WG-VM4 data.
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
*   **Reporting & Analytics:**
    *   A dedicated "Reports" page for administrators.
    *   Generate and download a CSV summary of all approved timesheets for a selected month.
    *   View a bar chart visualizing the total hours worked by each pilot for the selected month.
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
    *   ics (for iCalendar file generation)
    *   httpx (for HTTP client requests to data sources and APIs)
    *   APScheduler (for background cache refresh tasks)
    *   SQLModel (for database interaction with SQLite)
    *   Pydantic (for settings management)
*   **Frontend:**
    *   **Frontend**: Jinja2, HTML5, CSS3, JavaScript, Bootstrap 5
    *   **Database Migrations**: Alembic
    *   HTML5 (structured with Jinja2 templating)
    *   CSS3 (styled with Bootstrap 5 and custom CSS)
    *   JavaScript (for dynamic content, Chart.js for plotting, FullCalendar.js for scheduling, authentication handling)

## Project Structure Overview

```
.
├── alembic/                 # Database migration scripts
│   ├── versions/
│   └── env.py
├── app/                     # Core backend application
│   ├── __init__.py
│   ├── app.py               # Main FastAPI application instance
│   ├── auth_utils.py        # User authentication helper functions
│   ├── config.py            # Application settings management
│   ├── db.py                # Database engine and session management
│   ├── cli/                 # Command-line interface components
│   │   ├── cli.py
│   │   └── station_cli.py
│   ├── core/                # Core logic and data models
│   │   ├── __init__.py
│   │   ├── crud/
│   │   │   └── station_metadata_crud.py
│   │   ├── forecast.py
│   │   ├── loaders.py
│   │   ├── models.py
│   │   ├── plotting.py
│   │   ├── processors.py
│   │   ├── security.py
│   │   ├── summaries.py
│   │   └── utils.py
│   ├── forms/               # Form definitions
│   │   └── form_definitions.py
│   └── routers/             # APIRouters for modularizing API endpoints
│       └── station_metadata_router.py
├── web/                     # Frontend files
│   ├── static/              # Static assets (CSS, JS, etc.)
│   │   ├── css/
│   │   │   ├── custom.css
│   │   │   └── themes.css
│   │   ├── fullcalendar/    # FullCalendar library files
│   │   │   └── main.min.js
│   │   └── js/   
│   │        ├── admin_announcements.js
│   │        ├── admin_pay_periods.js
│   │        ├── admin_reports.js
│   │        ├── admin_user_management.js
│   │        ├── admin_view_timesheets.js
│   │        ├── auth.js
│   │        ├── home.js
│   │        ├── dashboard.js
│   │        ├── mission_form.js
│   │        ├── my_timesheets.js
│   │        ├── my_pic_handoffs.js
│   │        ├── payroll_submit.js
│   │        ├── schedule.js
│   │        ├── view_forms.js
│   │        ├── view_pic_handoffs.js
│   │        ├── view_station_status.js
│   │        └── wg_vm4.js
│   └── templates/           # HTML templates (Jinja2)
│       ├── email/
│       │   └── timesheet_status_update.html
│       ├── admin_announcements.html     
│       ├── admin_pay_periods.html
│       ├── admin_reports.html
│       ├── admin_user_management.html
│       ├── admin_view_timesheets.html
│       ├── _banner.html
│       ├── _form_details_modal.html
│       ├── payroll_submit.html   # Payroll-related pages
│       ├── base.html
│       ├── home.html
│       ├── index.html
│       ├── login.html
│       ├── mission_form.html
│       ├── my_timesheets.html
│       ├── my_pic_handoffs.html
│       ├── register.html
│       ├── schedule.html
│       ├── view_forms.html
│       ├── view_pic_handoffs.html
│       └── view_station_status.html
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
        LOCAL_DATA_BASE_PATH="/path/to/your/local/data" # Or "C:/path/to/data" on Windows
        ACTIVE_REALTIME_MISSIONS='["mission1", "mission2"]' # JSON string format for lists
        # --- SECURITY CRITICAL: JWT SECRET KEY ---
        # The JWT_SECRET_KEY is used to sign and verify authentication tokens.
        # It MUST be a strong, random, and secret value in production.
        # DO NOT use the default value from config.py in production.
        # Generate a secure key, for example, using Python:
        #   python -c "import secrets; print(secrets.token_hex(32))"
        # Then, add it to your .env file:
        JWT_SECRET_KEY="your_generated_strong_random_secret_key_here"
        # ---
        ```
    *   **Note:** If your `.env` file contains sensitive information (like API keys or database credentials not meant for public knowledge), ensure it is listed in your `.gitignore` file to prevent accidental commits.
    *   On the first run, or if the `data_store/app_data.sqlite` file is deleted, the application will create the SQLite database and populate it with default users (adminuser, pilotuser, pilot_rt_only).

6.  **Database Initialization & Migrations:**
    This project uses **Alembic** for database migrations.
    *   **First-time Setup:**
        1.  Install Alembic: `pip install alembic`
        2.  Initialize Alembic in the project root: `alembic init alembic`
        3.  Configure `alembic.ini` to point to your database.
        4.  Configure `alembic/env.py` to recognize your SQLModel models (see the provided `env.py` for an example).
    *   **Creating a New Migration:** When you change your `app/core/models.py` (e.g., add a new table or column), generate a new migration script:
        ```bash
        alembic revision --autogenerate -m "A short message describing the change"
        ```
    *   **Applying Migrations:** To apply all pending migrations to your database (both locally and on the server):
        ```bash
        alembic upgrade head
        ```
    *   **Important:** Always commit your generated migration scripts (in `alembic/versions/`) to version control. **Do not commit your `.sqlite` database file.**
    *   Ensure the `data_store` directory exists in the project root, or the application will attempt to create it. The SQLite database file (`app_data.sqlite`) will be created inside `data_store`.

7.  **Running the Application (Development):**
    Navigate to the project root directory (the one containing the `app` folder) and run:
    ```bash
    uvicorn app.app:app --reload --host 0.0.0.0 --port 8000
    ```
    *   `--reload`: Enables auto-reloading on code changes.
    *   `--host 0.0.0.0`: Makes the app accessible on your local network.
    *   `--port 8000`: Specifies the port.

8.  **Running the Application (Server/Production-like):**
    For a more robust setup on a server (especially Linux), use Gunicorn to manage Uvicorn workers:
    ```bash
    gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.app:app -b 0.0.0.0:8000
    ```
    Consider running this as a systemd service for persistence (see deployment notes/scripts for details).

8.  **Accessing the Application:**
    Open your web browser and navigate to `http://localhost:8000` (or `http://<your_server_ip>:8000` if running on a server and accessing from another machine).

## Logging

*   Log messages are output to both the console and the `app.log` file in the project root.
*   Timestamps in logs are in UTC.
*   Log level is set to INFO by default.

*   The `app.log` file is configured in `.env` and will be created if it doesn't exist.

## Development & Dependencies

This project uses `pip-tools` to manage dependencies.

- To add a new dependency, add it to `requirements.in` and run `pip-compile`.
- To install/update dependencies, run `pip-sync`.

This ensures that the `requirements.txt` file is always consistent with the project's needs.


*   **Advanced Cache Management:** Implement LRU (Least Recently Used) or TTL (Time To Live) cache eviction strategies using libraries like `cachetools` to manage memory usage more effectively.
*   **Security Hardening:** Consider implementing refresh tokens for longer-lived sessions with short-lived access tokens, comprehensive security headers (CSP, XSS protection, etc.), and robust rate limiting on sensitive endpoints.
*   **Advanced Authentication Features:** Consider enhancements like Two-Factor Authentication (2FA) or integration with OAuth providers if higher security or single sign-on capabilities are desired.
*   **Database Migrations:** Implement a database migration strategy (e.g., using Alembic with SQLModel) if the database schema (especially for `UserInDB`, `SubmittedForm`, or station metadata) is expected to evolve after initial deployment with data.
*   **UI/UX Enhancements:** More granular refresh controls, customizable dashboards, etc.
*   **Error Handling & Resilience:** Further improvements to error handling and reporting.
*   **Password Security:**
    *   While Passlib with bcrypt provides strong hashing, for extremely high-security environments, consider policies around password complexity, rotation, and lockout mechanisms (though these are often application-level logic on top of hashing).
    *   Ensure the environment where the application runs (including the database file) is secured to prevent unauthorized access to the hashed passwords.

---

## Acknowledgements

*   Weather forecast data generated using ICON Wave forecast from the German Weather Service DWD via the <a href="https://open-meteo.com/" target="_blank">Open-Meteo.com</a> API.
*   Coding assistance and suggestions provided by Google's Gemini models.