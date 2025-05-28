document.addEventListener('DOMContentLoaded', function() {
    const missionId = document.body.dataset.missionId;
    const hoursBack = 72; // update as need in hours
    const missionSelector = document.getElementById('missionSelector');
    const isRealtimeMission = document.body.dataset.isRealtime === 'true';
    const urlParams = new URLSearchParams(window.location.search);

    let powerChartInstance = null;
    let ctdChartInstance = null;
    let weatherSensorChartInstance = null;
    let waveChartInstance = null;
    let vr2cChartInstance = null;
    let ctdProfileChartInstance = null; // Instance for the new CTD profile chart
    let solarPanelChartInstance = null; // Instance for the new solar panel chart
    let fluorometerChartInstance = null;
    let waveHeightDirectionChartInstance = null; // Keep this for Hs vs Dp
    // Remove amplitude chart instances
    let waveSpectrumChartInstance = null; // Instance for the new Wave Spectrum chart
    let navigationChartInstance = null; // Instance for the new Navigation chart
    let navigationCurrentChartInstance = null; // Instance for Ocean Current chart
    let navigationHeadingDiffChartInstance = null; // Instance for Heading Difference chart

    // Define colors for dark mode charts
    const miniChartInstances = {};

    const chartTextColor = 'rgba(255, 255, 255, 0.8)';
    const chartGridColor = 'rgba(255, 255, 255, 0.1)';
    const miniChartLineColor = 'rgba(150, 180, 255, 0.8)'; // A neutral light blue for mini charts

    // Centralized Chart Colors
    const CHART_COLORS = {
        POWER_BATTERY: 'rgba(54, 162, 235, 1)',
        POWER_SOLAR: 'rgba(255, 159, 64, 1)',
        POWER_DRAW: 'rgba(255, 99, 132, 1)',
        CTD_TEMP: 'rgba(0, 191, 255, 1)',
        CTD_SALINITY: 'rgba(255, 105, 180, 1)',
        CTD_CONDUCTIVITY: 'rgba(123, 104, 238, 1)', // Medium Slate Blue
        CTD_DO: 'rgba(60, 179, 113, 1)', // Medium Sea Green (re-use from weather)
        WEATHER_AIR_TEMP: 'rgba(255, 99, 71, 1)',
        WEATHER_WIND_SPEED: 'rgba(60, 179, 113, 1)',
        WAVES_SIG_HEIGHT: 'rgba(255, 206, 86, 1)',
        WAVES_PERIOD: 'rgba(153, 102, 255, 1)',
        VR2C_DETECTION: 'rgba(75, 192, 192, 1)', // Teal
        WAVE_SPECTRUM: 'rgba(255, 99, 132, 1)', // A distinct color for the spectrum line
        FLUORO_C_AVG_PRIMARY: 'rgba(75, 192, 192, 1)', // Teal for C1_Avg
        SOLAR_PANEL_1: 'rgba(255, 215, 0, 1)', // Gold
        SOLAR_PANEL_2: 'rgba(173, 216, 230, 1)', // Light Blue
        SOLAR_PANEL_4: 'rgba(144, 238, 144, 1)', // Light Green
        FLUORO_TEMP: 'rgba(255, 99, 132, 1)', // Red for Fluorometer Temp
        NAV_SPEED: 'rgba(138, 43, 226, 1)', // BlueViolet for Glider Speed
        NAV_SOG: 'rgba(0, 128, 0, 0.7)',   // Green (slightly transparent) for SOG
        NAV_HEADING: 'rgba(255, 140, 0, 1)', // DarkOrange for Heading
        OCEAN_CURRENT_SPEED: 'rgba(30, 144, 255, 1)', // DodgerBlue
        OCEAN_CURRENT_DIRECTION: 'rgba(255, 69, 0, 1)', // OrangeRed
        HEADING_DIFF: 'rgba(218, 112, 214, 1)' // Orchid
    };

    const currentSource = urlParams.get('source') || 'remote';
    const currentLocalPath = urlParams.get('local_path') || '';
    // auotrefresh timer and countdown
    const autoRefreshIntervalMinutes = 5;
    let countdownTimer = null;

    function updateUtcClock() {
        const clockElement = document.getElementById('utcClock');
        if (clockElement) {
            const now = new Date();
            const utcString = now.toLocaleTimeString('en-US', {
                timeZone: 'UTC',
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            clockElement.textContent = `Current UTC Time: ${utcString}`;
        }
    }

    function startCountdownTimer() {
        const countdownElement = document.getElementById('refreshCountdown');
        if (!countdownElement) return;

        let remainingSeconds = autoRefreshIntervalMinutes * 60;
        countdownElement.style.display = 'block'; // Show the countdown element

        function updateCountdownDisplay() {
            const minutes = Math.floor(remainingSeconds / 60);
            const seconds = remainingSeconds % 60;
            const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            countdownElement.textContent = `Next refresh in ${display}`;

            if (remainingSeconds <= 0) {
                clearInterval(countdownTimer); // Stop the countdown
            } else {
                remainingSeconds--;
            }
        }
        updateCountdownDisplay();
        countdownTimer = setInterval(updateCountdownDisplay, 1000);
    }

    if (missionSelector) {
                missionSelector.addEventListener('change', function() {
            const newMissionId = this.value;
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('mission', newMissionId);
            window.location.href = currentUrl.toString();
        });
    }

    const dataSourceModal = document.getElementById('dataSourceModal');
    if (dataSourceModal) {
        const localPathInputGroup = document.getElementById('localPathInputGroup');
        const customLocalPathInput = document.getElementById('customLocalPath');
        const applyDataSourceBtn = document.getElementById('applyDataSource');

        document.querySelectorAll('input[name="dataSourceOption"]').forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.value === 'local') {
                    localPathInputGroup.style.display = 'block';
                } else {
                    localPathInputGroup.style.display = 'none';
                }
            });
        });

        applyDataSourceBtn.addEventListener('click', function() {
            const selectedSource = document.querySelector('input[name="dataSourceOption"]:checked').value;
            let newLocalPath = '';
            if (selectedSource === 'local') {
                newLocalPath = customLocalPathInput.value.trim();
            }

            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('source', selectedSource);
            if (newLocalPath) {
                currentUrl.searchParams.set('local_path', newLocalPath);
            } else {
                currentUrl.searchParams.delete('local_path');
            }
            const modalInstance = bootstrap.Modal.getInstance(dataSourceModal);
            if (modalInstance) {
                modalInstance.hide();
            }
            setTimeout(() => { window.location.href = currentUrl.toString(); }, 150);
        });
    }

    if (isRealtimeMission) {
        // console.log(`This is a real-time mission page (${missionId}). Auto-refresh enabled for every ${autoRefreshIntervalMinutes} minutes.`);
        startCountdownTimer(); 

        setTimeout(function() {
            if (!document.querySelector('.modal.show')) {
                window.location.reload(true); 
            }
        }, autoRefreshIntervalMinutes * 60 * 1000);
    }

    function displayGlobalError(message) {
        const errorDiv = document.getElementById('generalErrorDisplay');
        errorDiv.textContent = message || 'An error occurred. Please check console or try again later.';
        errorDiv.style.display = 'block';
    }
    // Refresh Data Button Logic
    /**
     * Fetches chart data from the API for a given report type and mission.
     * @param {string} reportType - The type of report (e.g., 'power', 'ctd').
     * @param {string} mission - The mission ID.
     * @param {number} hours - The number of hours back to fetch data for.
     * @returns {Promise<Array<Object>|null>} A promise that resolves with the chart data array or null if fetching fails.
     */
    async function fetchChartData(reportType, mission, hours) {
        const chartCanvas = document.getElementById(`${reportType}Chart`); 
        const spinner = chartCanvas ? chartCanvas.parentElement.querySelector('.chart-spinner') : null;
        if (spinner) spinner.style.display = 'block';

        try {
            let apiUrl = `/api/data/${reportType}/${mission}?hours_back=${hours}`;
            apiUrl += `&source=${currentSource}`;
            if (currentSource === 'local' && currentLocalPath) {
                apiUrl += `&local_path=${encodeURIComponent(currentLocalPath)}`;
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                apiUrl += `&refresh=true`;
            }
            const response = await fetch(apiUrl);
            if (!response.ok) {
                const errorText = await response.text();
                const errorMessage = `Error fetching ${reportType} data: ${response.statusText}. Server: ${errorText}`;
                console.error(errorMessage);
                displayGlobalError(`Failed to load ${reportType} chart data.`);
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Network error fetching ${reportType} data:`, error);
            displayGlobalError(`Network error while fetching ${reportType} chart data.`);
            return null;
        } finally {
            if (spinner) spinner.style.display = 'none';
        }
    }

    /**
     * Renders the LARGE Power Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderPowerChart(chartData) {
        // console.log('Attempting to render Power Chart. Data received:', chartData);
        const ctx = document.getElementById('powerChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none'; // Hide spinner before rendering or showing "no data"


        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Power Chart.');
            // Display a message on the canvas if no data
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No power trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (powerChartInstance) { powerChartInstance.destroy(); powerChartInstance = null; }
            return;
        }

        const datasets = [];
        // Dynamically add datasets based on available data
        if (chartData.some(d => d.BatteryWattHours !== null && d.BatteryWattHours !== undefined)) {
            datasets.push({
                label: 'Battery (Wh)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.BatteryWattHours })),
                borderColor: CHART_COLORS.POWER_BATTERY,
                yAxisID: 'yBattery', // Assign to new right-hand Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.PowerDrawWatts !== null && d.PowerDrawWatts !== undefined)) {
            datasets.push({
                label: 'Power Draw (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.PowerDrawWatts })),
                borderColor: CHART_COLORS.POWER_DRAW,
                yAxisID: 'ySolar', // Share with Solar Input
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Power Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable power data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (powerChartInstance) { powerChartInstance.destroy(); powerChartInstance = null; }
            return;
        }

        if (powerChartInstance) {
            powerChartInstance.destroy(); // Clear previous chart if any
        }

        powerChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, // Keep responsive
                maintainAspectRatio: false, // Keep aspect ratio false
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    ySolar: { type: 'linear', position: 'left', title: { display: true, text: 'Watts (W)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yBattery: { type: 'linear', position: 'right', title: { display: true, text: 'Watt-hours (Wh)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } } // New axis for Battery
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the CTD Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderCtdChart(chartData) { // This function was missing in the previous diff
        // console.log('Attempting to render CTD Chart. Data received:', chartData);
        const ctx = document.getElementById('ctdChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for CTD Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No CTD trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdChartInstance) { ctdChartInstance.destroy(); ctdChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.WaterTemperature !== null && d.WaterTemperature !== undefined)) {
            datasets.push({
                label: 'Water Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WaterTemperature })),
                borderColor: CHART_COLORS.CTD_TEMP,
                yAxisID: 'yTemp', // Assign to a specific Y axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Salinity !== null && d.Salinity !== undefined)) {
            datasets.push({
                label: 'Salinity (PSU)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Salinity })),
                borderColor: CHART_COLORS.CTD_SALINITY,
                yAxisID: 'ySalinity', // Assign to a different Y axis
                tension: 0.1, fill: false
            });
        }
        // Add other CTD metrics (Conductivity, DissolvedOxygen, Pressure) similarly, potentially on new axes or separate charts

        if (datasets.length === 0) {
            // console.warn('CTD Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable CTD data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdChartInstance) { ctdChartInstance.destroy(); ctdChartInstance = null; }
            return;
        }

        if (ctdChartInstance) {
            ctdChartInstance.destroy();
        }

        ctdChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                                responsive: true, // Keep responsive
                maintainAspectRatio: false, // Keep aspect ratio false
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    ySalinity: { type: 'linear', position: 'right', title: { display: true, text: 'Salinity (PSU)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } } // Secondary axis for Salinity
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the CTD chart on page load
    fetchChartData('ctd', missionId, hoursBack).then(data => {
        renderCtdChart(data); // Existing chart for Temp & Salinity
        renderCtdProfileChart(data); // New chart for Temp, Conductivity, DO
    });
    // Fetch and render the Weather Sensor chart on page load
    fetchChartData('weather', missionId, hoursBack).then(data => {
        renderWeatherSensorChart(data);
    });

    // Fetch Power and Solar data concurrently, then render their charts
    Promise.all([
        fetchChartData('power', missionId, hoursBack),
        fetchChartData('solar', missionId, hoursBack)
    ]).then(([powerData, solarData]) => {
        renderPowerChart(powerData); // Renders power chart (now without total solar)
        renderSolarPanelChart(solarData, powerData); // Pass both solar (individual) and power (for total solar) data
    }).catch(error => {
        // If Navigation is the default active view, this initial fetch might need adjustment
        // For now, assuming Power or another non-Telemetry chart is default.
        // If Navigation is default, its data should be fetched here too.
        fetchChartData('telemetry', missionId, hoursBack).then(data => {
            renderNavigationChart(data);
            renderNavigationCurrentChart(data);
            renderNavigationHeadingDiffChart(data);
        });
        console.error("Error fetching initial power or solar data for combined rendering:", error);
        // Fallback: render charts with null to show "no data" messages
        renderPowerChart(null);
        renderSolarPanelChart(null, null);
    });
    
    /**
     * Renders the second CTD Chart (Profile Details) using Chart.js.
     * Plots Water Temperature (left Y1), Conductivity (right Y), Dissolved Oxygen (left Y2, hidden).
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderCtdProfileChart(chartData) {
        // console.log('Attempting to render CTD Profile Chart. Data received:', chartData);
        const canvas = document.getElementById('ctdProfileChart');
        if (!canvas) {
            console.error("Canvas element 'ctdProfileChart' not found.");
            return;
        }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for CTD Profile Chart.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No CTD profile data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); ctdProfileChartInstance = null; }
            return;
        }

        const datasets = [];
        // Water Temperature (Left Y-axis 1, more transparent)
        if (chartData.some(d => d.WaterTemperature !== null && d.WaterTemperature !== undefined)) {
            datasets.push({
                label: 'Water Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WaterTemperature })),
                borderColor: CHART_COLORS.CTD_TEMP.replace('1)', '0.2)'), // Make Water Temp more transparent
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        // Conductivity (Right Y-axis, now more transparent)
        if (chartData.some(d => d.Conductivity !== null && d.Conductivity !== undefined)) {
            datasets.push({
                label: 'Conductivity (S/m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Conductivity })),
                borderColor: CHART_COLORS.CTD_CONDUCTIVITY.replace('1)', '0.2)'), // Make Conductivity more transparent
                yAxisID: 'yCond',
                tension: 0.1, fill: false
            });
        }
        // Dissolved Oxygen (Left Y-axis 2, hidden, now less transparent relative to others)
        if (chartData.some(d => d.DissolvedOxygen !== null && d.DissolvedOxygen !== undefined)) {
            datasets.push({
                label: 'DO (Hz)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.DissolvedOxygen })),
                borderColor: CHART_COLORS.CTD_DO, // Use original alpha (1.0), making it the most opaque
                yAxisID: 'yDO',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('CTD Profile Chart: No valid datasets could be formed.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable CTD profile data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); ctdProfileChartInstance = null; }
            return;
        }

        if (ctdProfileChartInstance) { ctdProfileChartInstance.destroy(); }

        ctdProfileChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yCond: { type: 'linear', position: 'right', title: { display: true, text: 'Conductivity (S/m)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } },
                    yDO: { type: 'linear', position: 'left', display: false, grid: { drawOnChartArea: false } } // Hidden Y-axis for DO
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    function renderWeatherSensorChart(chartData) { // This function was missing in the previous diff
        // console.log('Attempting to render Weather Chart. Data received:', chartData);
        const ctx = document.getElementById('weatherSensorChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Weather Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No weather sensor trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (weatherSensorChartInstance) { weatherSensorChartInstance.destroy(); weatherSensorChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.AirTemperature !== null && d.AirTemperature !== undefined)) {
            datasets.push({
                label: 'Air Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.AirTemperature })),
                borderColor: CHART_COLORS.WEATHER_AIR_TEMP,
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindSpeed !== null && d.WindSpeed !== undefined)) {
            datasets.push({
                label: 'Wind Speed (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindSpeed })),
                borderColor: CHART_COLORS.WEATHER_WIND_SPEED,
                yAxisID: 'yWind',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindGust !== null && d.WindGust !== undefined)) {
            datasets.push({
                label: 'Wind Gust (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindGust })),
                borderColor: CHART_COLORS.WEATHER_WIND_SPEED.replace('1)', '0.7)'), // Lighter version of wind speed
                borderDash: [5, 5], // Dashed line for gusts
                yAxisID: 'yWind', // Share axis with WindSpeed
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Weather Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable weather data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (weatherSensorChartInstance) { weatherSensorChartInstance.destroy(); weatherSensorChartInstance = null; }
            return;
        }

        if (weatherSensorChartInstance) {
            weatherSensorChartInstance.destroy();
        }

        weatherSensorChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yWind: { type: 'linear', position: 'right', title: { display: true, text: 'Wind (kt)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false, color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Fetches weather forecast data from the API.
     * @param {string} mission - The mission ID.
     */
    // --- Weather Forecast ---
    async function fetchForecastData(mission) {
        try {
            const initialForecastArea = document.getElementById('forecastInitial');
            // Spinner management removed for forecast
            if (initialForecastArea) initialForecastArea.style.display = 'none'; // Ensure content area is hidden

            let forecastApiUrl = `/api/forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            forecastParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            // Pass refresh parameter to forecast API if present in main page URL
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            const response = await fetch(`${forecastApiUrl}?${forecastParams.toString()}`);
            if (!response.ok) {
                const errorText = await response.text();
                const errorMessage = `Error fetching forecast data: ${response.statusText}. Server: ${errorText}`;
                console.error(errorMessage);
                displayGlobalError('Failed to load weather forecast.');
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Network error fetching forecast data:`, error);
            displayGlobalError('Network error while fetching weather forecast.');
            return null;
        } finally {
            // Spinner management removed for forecast
        }
    }

    // WMO Weather code descriptions (simplified)
    // Source: https://open-meteo.com/en/docs (Weather WMO Code Table)
    const WMO_WEATHER_CODES = {
        0: 'Clear sky',
        1: 'Mainly clear',
        2: 'Partly cloudy',
        3: 'Overcast',
        45: 'Fog',
        48: 'Depositing rime fog',
        51: 'Light drizzle',
        53: 'Moderate drizzle',
        55: 'Dense drizzle',
        56: 'Light freezing drizzle',
        57: 'Dense freezing drizzle',
        61: 'Slight rain',
        63: 'Moderate rain',
        65: 'Heavy rain',
        66: 'Light freezing rain',
        67: 'Heavy freezing rain',
        71: 'Slight snow fall',
        73: 'Moderate snow fall',
        75: 'Heavy snow fall',
        77: 'Snow grains',
        80: 'Slight rain showers',
        81: 'Moderate rain showers',
        82: 'Violent rain showers',
        85: 'Slight snow showers',
        86: 'Heavy snow showers',
        95: 'Thunderstorm', // Slight or moderate
        96: 'Thunderstorm with slight hail',
        99: 'Thunderstorm with heavy hail',
    };

    function getWeatherDescription(code) {
        return WMO_WEATHER_CODES[code] || 'Unknown';
    }

    /**
     * Renders the weather forecast table.
     * @param {Object|null} forecastData - The forecast data object fetched from the API.
     */

    function renderForecast(forecastData) {
        const initialContainer = document.getElementById('forecastInitial');
        const extendedContainer = document.getElementById('forecastExtendedContent');
        const toggleButton = document.getElementById('toggleForecastBtn');
        // Spinner management removed for forecast

        if (!forecastData || !forecastData.hourly || !forecastData.hourly.time || forecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Forecast data is currently unavailable.</p>';
            if (extendedContainer) extendedContainer.innerHTML = '';
            if (toggleButton) toggleButton.style.display = 'none';
        } else {
            // Add a title indicating the forecast type
            let forecastTitle = 'Weather Forecast';
 // The 'forecast_type' is added by our backend wrapper in forecast.py
            if (forecastData.forecast_type === 'marine') {
                forecastTitle += ' (Marine & General)';
            } else if (forecastData.forecast_type === 'general') {
                forecastTitle += ' (General Weather)'; // Simplified title
            }
            initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>`; // Prepend title

            const hourly = forecastData.hourly;
            const units = forecastData.hourly_units || {}; // Get units from the forecast data
            const totalHoursAvailable = hourly.time.length;

            const createTableHtml = (startHour, endHour) => {
                let tableHtml = '<table class="table table-sm table-striped table-hover">';
                tableHtml += '<thead><tr>' +
                             '<th>Time</th>' +
                             '<th>Weather</th>' +
                             `<th>Air Temp (${units.temperature_2m || '°C'})</th>` + // Default unit if not provided
                             `<th>Precip (${units.precipitation || 'mm'})</th>` +   // Default unit
                             `<th>Wind (${units.windspeed_10m || 'm/s'} @ ${units.winddirection_10m || '°'})</th>`; // Default units
                tableHtml += '</tr></thead>';
                tableHtml += '<tbody>';

                for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                    const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                    
                    const weatherCode = (hourly.weathercode && hourly.weathercode[i] !== null) ? hourly.weathercode[i] : 'N/A';
                    const weatherDisplay = getWeatherDescription(weatherCode);

                    const airTemp = (hourly.temperature_2m && hourly.temperature_2m[i] !== null) ? hourly.temperature_2m[i].toFixed(1) : 'N/A';
                    const precip = (hourly.precipitation && hourly.precipitation[i] !== null) ? hourly.precipitation[i].toFixed(1) : 'N/A';
                    
                    // Wind data (speed and direction)
                    const windSpeed = (hourly.windspeed_10m && hourly.windspeed_10m[i] !== null) ? hourly.windspeed_10m[i].toFixed(1) : 'N/A';
                    const windDir = (hourly.winddirection_10m && hourly.winddirection_10m[i] !== null) ? hourly.winddirection_10m[i].toFixed(0) : 'N/A';
                    const windDisplay = windSpeed !== 'N/A' ? `${windSpeed} @ ${windDir}°` : 'N/A';

                    tableHtml += `<tr>` +
                                 `<td>${time}</td>` +
                                 `<td>${weatherDisplay}</td>` +
                                 `<td>${airTemp}</td>` +
                                 `<td>${precip}</td>` +
                                 `<td>${windDisplay}</td>` +
                                 `</tr>`;
                }
                tableHtml += '</tbody></table>';
                return tableHtml;
            };

            const initialHours = 12;
            // Append the table to the initial container, after the title
            initialContainer.innerHTML += createTableHtml(0, initialHours);

            const extendedStartHour = initialHours;
            const maxExtendedHours = 48; // Show up to 48 hours total when expanded

            if (totalHoursAvailable > initialHours) {
                extendedContainer.innerHTML = createTableHtml(extendedStartHour, Math.min(totalHoursAvailable, maxExtendedHours));
                toggleButton.style.display = 'block'; // Show the button
                
                const collapseElement = document.getElementById('forecastExtended');
                // Listener to update button text
                collapseElement.addEventListener('show.bs.collapse', function () {
                    toggleButton.textContent = 'Show Less';
                });
                collapseElement.addEventListener('hide.bs.collapse', function () {
                    toggleButton.textContent = 'Show More';
                });
                // Set initial text
                if (!collapseElement.classList.contains('show')) {
                     toggleButton.textContent = 'Show More';
                } else {
                     toggleButton.textContent = 'Show Less';
                }
            } else {
                if (extendedContainer) extendedContainer.innerHTML = '';
                if (toggleButton) toggleButton.style.display = 'none';
         }          }
         // Ensure spinner is hidden and content area is visible
         // Spinner management removed for forecast

        initialContainer.style.display = 'block';

        // Populate forecast metadata
        const metaInfoContainer = document.getElementById('forecastMetaInfo');
        if (metaInfoContainer) {
            if (forecastData && forecastData.fetched_at_utc && forecastData.latitude_used !== undefined && forecastData.longitude_used !== undefined) {
                const fetchedDate = new Date(forecastData.fetched_at_utc);
                const formattedTime = fetchedDate.toLocaleTimeString('en-US', {
                    timeZone: 'UTC',
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                });
                const lat = parseFloat(forecastData.latitude_used).toFixed(3);
                const lon = parseFloat(forecastData.longitude_used).toFixed(3);
                metaInfoContainer.textContent = `Forecast fetched: ${formattedTime} UTC for Lat: ${lat}, Lon: ${lon}`;
                metaInfoContainer.style.display = 'block'; // Ensure it's visible
            } else {
                metaInfoContainer.textContent = ''; // Clear if no data
                metaInfoContainer.style.display = 'none'; // Hide if no data
            }
        }
    }

    async function fetchMarineForecastData(mission) {
        try {
            const initialMarineForecastArea = document.getElementById('marineForecastInitial');
            if (initialMarineForecastArea) initialMarineForecastArea.style.display = 'none';

            let marineForecastApiUrl = `/api/marine_forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            // Marine forecast might need lat/lon explicitly if not inferred by backend for this specific endpoint
            // For now, assuming backend handles it or we pass lat/lon if available from telemetry summary
            // Example: if (currentGliderLat && currentGliderLon) {
            //    forecastParams.append('lat', currentGliderLat);
            //    forecastParams.append('lon', currentGliderLon);
            // }
            forecastParams.append('source', currentSource); // Keep consistent with other data calls
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            const response = await fetch(`${marineForecastApiUrl}?${forecastParams.toString()}`);
            if (!response.ok) {
                const errorText = await response.text();
                console.error(`Error fetching marine forecast data: ${response.statusText}. Server: ${errorText}`);
                displayGlobalError('Failed to load marine forecast.');
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Network error fetching marine forecast data:`, error);
            displayGlobalError('Network error while fetching marine forecast.');
            return null;
        }
    }


    // Fetch and render forecast
    fetchForecastData(missionId).then(data => {
        renderForecast(data);
    });
    /**
     * Renders the Wave Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderWaveChart(chartData) { 
        // console.log('Attempting to render Wave Chart. Data received:', chartData);
        const ctx = document.getElementById('waveChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

                if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Wave Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No wave trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveChartInstance) { waveChartInstance.destroy(); waveChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.SignificantWaveHeight !== null && d.SignificantWaveHeight !== undefined)) {
            datasets.push({
                label: 'Sig. Wave Height (m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SignificantWaveHeight })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT,
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WavePeriod !== null && d.WavePeriod !== undefined)) {
            datasets.push({
                label: 'Wave Period (s)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WavePeriod })),
                borderColor: CHART_COLORS.WAVES_PERIOD,
                yAxisID: 'yPeriod',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Wave Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable wave data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveChartInstance) { waveChartInstance.destroy(); waveChartInstance = null; }
            return;
        }

        if (waveChartInstance) {
            waveChartInstance.destroy();
        }

        waveChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } },
                        title: { display: true, text: 'Time', color: chartTextColor },
                        ticks: {
                            color: chartTextColor,
                            maxRotation: 0,
                            autoSkip: true,
                            autoSkipPadding: 20
                        },
                        grid: { color: chartGridColor }
                    },
                    yHeight: { type: 'linear', position: 'left', title: { display: true, text: 'Wave Height (m)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yPeriod: { type: 'linear', position: 'right', title: { display: true, text: 'Wave Period (s)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false, color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    function renderMarineForecast(marineForecastData) {
        const initialContainer = document.getElementById('marineForecastInitial');
        const extendedContainer = document.getElementById('marineForecastExtendedContent');
        const toggleButton = document.getElementById('toggleMarineForecastBtn');
        const metaInfoContainer = document.getElementById('marineForecastMetaInfo');

        if (!initialContainer || !extendedContainer || !toggleButton || !metaInfoContainer) {
            console.error("One or more marine forecast display elements are missing from the DOM.");
            return;
        }

        if (!marineForecastData || !marineForecastData.hourly || !marineForecastData.hourly.time || marineForecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Marine forecast data is currently unavailable.</p>';
            initialContainer.style.display = 'block';
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
            metaInfoContainer.style.display = 'none';
            return;
        }

        let forecastTitle = 'Marine Forecast'; // Already specific
        initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>`;

        const hourly = marineForecastData.hourly;
        const units = marineForecastData.hourly_units || {};
        const totalHoursAvailable = hourly.time.length;

        const createMarineTableHtml = (startHour, endHour) => {
            let tableHtml = '<table class="table table-sm table-striped table-hover">';
            tableHtml += '<thead><tr>' +
                         '<th>Time</th>' +
                         `<th>Wave Ht (${units.wave_height || 'm'})</th>` +
                         `<th>Wave Prd (${units.wave_period || 's'})</th>` +
                         `<th>Wave Dir (${units.wave_direction || '°'})</th>` +
                         `<th>Current (${units.ocean_current_velocity || 'm/s'} @ ${units.ocean_current_direction || '°'})</th>`;
            tableHtml += '</tr></thead>';
            tableHtml += '<tbody>';

            for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                const waveHeight = (hourly.wave_height && hourly.wave_height[i] !== null) ? hourly.wave_height[i].toFixed(1) : 'N/A';
                const wavePeriod = (hourly.wave_period && hourly.wave_period[i] !== null) ? hourly.wave_period[i].toFixed(1) : 'N/A';
                const waveDir = (hourly.wave_direction && hourly.wave_direction[i] !== null) ? hourly.wave_direction[i].toFixed(0) : 'N/A';
                const currentSpeed = (hourly.ocean_current_velocity && hourly.ocean_current_velocity[i] !== null) ? hourly.ocean_current_velocity[i].toFixed(2) : 'N/A';
                const currentDir = (hourly.ocean_current_direction && hourly.ocean_current_direction[i] !== null) ? hourly.ocean_current_direction[i].toFixed(0) : 'N/A';
                const currentDisplay = currentSpeed !== 'N/A' ? `${currentSpeed} @ ${currentDir}°` : 'N/A';

                tableHtml += `<tr><td>${time}</td><td>${waveHeight}</td><td>${wavePeriod}</td><td>${waveDir}</td><td>${currentDisplay}</td></tr>`;
            }
            tableHtml += '</tbody></table>';
            return tableHtml;
        };

        const initialHours = 12;
        initialContainer.innerHTML += createMarineTableHtml(0, initialHours);
        initialContainer.style.display = 'block';

        const extendedStartHour = initialHours;
        const maxExtendedHours = 48;

        if (totalHoursAvailable > initialHours) {
            extendedContainer.innerHTML = createMarineTableHtml(extendedStartHour, Math.min(totalHoursAvailable, maxExtendedHours));
            toggleButton.style.display = 'block';
            const collapseElement = document.getElementById('marineForecastExtended');
            collapseElement.addEventListener('show.bs.collapse', () => { toggleButton.textContent = 'Show Less'; });
            collapseElement.addEventListener('hide.bs.collapse', () => { toggleButton.textContent = 'Show More'; });
            toggleButton.textContent = collapseElement.classList.contains('show') ? 'Show Less' : 'Show More';
        } else {
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
        }

        if (marineForecastData.fetched_at_utc && marineForecastData.latitude_used !== undefined) {
            const fetchedDate = new Date(marineForecastData.fetched_at_utc);
            metaInfoContainer.textContent = `Forecast fetched: ${fetchedDate.toLocaleTimeString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} UTC for Lat: ${parseFloat(marineForecastData.latitude_used).toFixed(3)}, Lon: ${parseFloat(marineForecastData.longitude_used).toFixed(3)}`;
            metaInfoContainer.style.display = 'block';
        } else {
            metaInfoContainer.style.display = 'none';
        }
    }

    // Fetch and render the Wave chart on page load
    fetchChartData('waves', missionId, hoursBack).then(data => {
        renderWaveChart(data); // Renders Hs vs Tp chart (time-series)
        renderWaveHeightDirectionChart(data); // Call the reinstated function
        // Wave spectrum is loaded on demand when its detail card is clicked
    }); // This call was missing in the previous diff

    /**
     * Renders the VR2C Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderVr2cChart(chartData) {
        // console.log('Attempting to render VR2C Chart. Data received:', chartData);
        const ctx = document.getElementById('vr2cChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for VR2C Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No VR2C trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (vr2cChartInstance) { vr2cChartInstance.destroy(); vr2cChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.DetectionCount !== null && d.DetectionCount !== undefined)) {
            datasets.push({
                label: 'Detection Count (DC)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.DetectionCount })),
                borderColor: CHART_COLORS.VR2C_DETECTION,
                yAxisID: 'yCounts',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.PingCountDelta !== null && d.PingCountDelta !== undefined)) {
            datasets.push({
                label: 'Ping Count Delta (ΔPC/hr)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.PingCountDelta })),
                borderColor: CHART_COLORS.POWER_DRAW, // Re-use a contrasting color like red
                yAxisID: 'yDelta', // Assign to new right-hand Y-axis
                tension: 0.1, fill: false, // No fill for delta
                borderDash: [5, 5] // Optional: make it dashed
            });
        }

        if (datasets.length === 0) {
            // console.warn('VR2C Chart: No valid datasets could be formed from the provided chartData.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No plottable VR2C data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (vr2cChartInstance) { vr2cChartInstance.destroy(); vr2cChartInstance = null; }
            return;
        }

        if (vr2cChartInstance) {
            vr2cChartInstance.destroy();
        }

        vr2cChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yCounts: { type: 'linear', position: 'left', title: { display: true, text: 'Detection Count (DC)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDelta: { type: 'linear', position: 'right', title: { display: true, text: 'Ping Count Delta (ΔPC/hr)', color: chartTextColor }, ticks: { color: chartTextColor /* beginAtZero: false might be better for deltas */ }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }
        /**
     * Renders the Wave Height vs. Direction Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderWaveHeightDirectionChart(chartData) {
        const canvas = document.getElementById('waveHeightDirectionChart');
        if (!canvas) { console.error("Canvas 'waveHeightDirectionChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No wave Ht/Dir data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); waveHeightDirectionChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.SignificantWaveHeight !== null && d.SignificantWaveHeight !== undefined)) {
            datasets.push({
                label: 'Sig. Wave Height (m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SignificantWaveHeight })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT,
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.MeanWaveDirection !== null && d.MeanWaveDirection !== undefined)) {
            datasets.push({
                label: 'Mean Wave Dir (°)',
                data: chartData.map(item => {
                    // --- DEBUGGING START ---
                    // console.log("Original MeanWaveDirection:", item.MeanWaveDirection, "Type:", typeof item.MeanWaveDirection);
                    // --- DEBUGGING END ---
                    let waveDirNum = parseFloat(item.MeanWaveDirection);
                    // --- DEBUGGING START ---
                    // console.log("Parsed waveDirNum:", waveDirNum, "Type:", typeof waveDirNum);
                    // --- DEBUGGING END ---

                    // Filter out specific outlier values for wave direction
                    if (waveDirNum === 9999 || waveDirNum === -9999) {
                        // --- DEBUGGING START ---
                        // console.log("Outlier detected, setting to null. Original value was:", item.MeanWaveDirection);
                        // --- DEBUGGING END ---
                        waveDirNum = null; // Chart.js will skip null points
                    }
                    return { x: new Date(item.Timestamp), y: waveDirNum };
                }),
                borderColor: CHART_COLORS.CTD_SALINITY.replace('1)', '0.7)'), // Re-use a color
                yAxisID: 'yDirection',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable wave Ht/Dir data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); waveHeightDirectionChartInstance = null; }
            return;
        }

        if (waveHeightDirectionChartInstance) { waveHeightDirectionChartInstance.destroy(); }
        waveHeightDirectionChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm' }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    yHeight: { type: 'linear', position: 'left', title: { display: true, text: 'Wave Height (m)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDirection: { type: 'linear', position: 'right', title: { display: true, text: 'Wave Direction (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the VR2C chart on page load
    fetchChartData('vr2c', missionId, hoursBack).then(data => {
        renderVr2cChart(data);
    });

    // Fetch and render the Fluorometer chart on page load
    fetchChartData('fluorometer', missionId, hoursBack).then(data => {
        renderFluorometerChart(data);
    }); // Removed the stray closing brace from the next line

    /**
     * Fetches and renders the latest wave spectrum data.
     * @param {string} mission - The mission ID.
     */
    async function fetchAndRenderWaveSpectrum(mission) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) { console.error("Canvas 'waveSpectrumChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'block';

        try {
            let apiUrl = `/api/wave_spectrum/${mission}`;
            const spectrumParams = new URLSearchParams();
            spectrumParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                spectrumParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                spectrumParams.append('refresh', 'true');
            }
            // Note: We are NOT passing a specific timestamp here, relying on the backend to get the latest
            // unless a specific timestamp selection UI is added later.
            const response = await fetch(`${apiUrl}?${spectrumParams.toString()}`);
            if (!response.ok) {
                const errorText = await response.text();
                const errorMessage = `Error fetching wave spectrum data: ${response.statusText}. Server: ${errorText}`;
                console.error(errorMessage);
                displayGlobalError('Failed to load wave spectrum data.');
                renderWaveSpectrumChart(null); // Render empty chart
                return;
            }
            const spectrumData = await response.json();
            renderWaveSpectrumChart(spectrumData);
        } catch (error) {
            console.error(`Network error fetching wave spectrum data:`, error);
            displayGlobalError('Network error while fetching wave spectrum data.');
            renderWaveSpectrumChart(null); // Render empty chart
        } finally {
            if (spinner) spinner.style.display = 'none';
        }
    }

    /**
     * Renders the Wave Energy Spectrum Chart using Chart.js.
     * @param {Array<Object>|null} spectrumData - The data array [{x: freq, y: efth}] fetched from the API.
     */
    function renderWaveSpectrumChart(spectrumData) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) return; 
        const ctx = canvas.getContext('2d');

        if (waveSpectrumChartInstance) { waveSpectrumChartInstance.destroy(); }

        if (!spectrumData || spectrumData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No wave spectrum data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        waveSpectrumChartInstance = new Chart(ctx, {
            type: 'line', 
            data: { datasets: [{ label: 'Energy Density (m²/Hz)', data: spectrumData, borderColor: CHART_COLORS.WAVE_SPECTRUM, borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'linear', position: 'bottom', title: { display: true, text: 'Frequency (Hz)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    y: { type: 'linear', position: 'left', title: { display: true, text: 'Energy Density (m²/Hz)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

     /**
     * Renders the Fluorometer Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderFluorometerChart(chartData) {
        const canvas = document.getElementById('fluorometerChart');
        if (!canvas) { console.error("Canvas 'fluorometerChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No fluorometer data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); fluorometerChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.C1_Avg !== null && d.C1_Avg !== undefined)) {
            datasets.push({
                label: 'C1 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C1_Avg })),
                borderColor: CHART_COLORS.FLUORO_C_AVG_PRIMARY,
                yAxisID: 'yPrimary',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.C2_Avg !== null && d.C2_Avg !== undefined)) {
            datasets.push({
                label: 'C2 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C2_Avg })),
                borderColor: CHART_COLORS.WAVES_SIG_HEIGHT, // Re-use a distinct color
                yAxisID: 'yPrimary', // Share the primary Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.C3_Avg !== null && d.C3_Avg !== undefined)) {
            datasets.push({
                label: 'C3 Avg',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.C3_Avg })),
                borderColor: CHART_COLORS.WAVES_PERIOD, // Re-use another distinct color
                yAxisID: 'yPrimary', // Share the primary Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Temperature_Fluor !== null && d.Temperature_Fluor !== undefined)) {
            datasets.push({
                label: 'Temperature (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Temperature_Fluor })),
                borderColor: CHART_COLORS.FLUORO_TEMP, // Use a distinct color
                yAxisID: 'yTemp', // Use a secondary axis for temperature
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable fluorometer data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); fluorometerChartInstance = null; }
            return;
        }

        if (fluorometerChartInstance) { fluorometerChartInstance.destroy(); }
        fluorometerChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm' }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    yPrimary: { type: 'linear', position: 'left', title: { display: true, text: 'Fluorescence Units', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'right', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

  
    /**
     * Renders the Solar Panel Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     * @param {Array<Object>|null} powerData - The data array for the main power report, used for total solar input.
     */
    function renderSolarPanelChart(chartData, powerData) {
        // console.log('Attempting to render Solar Panel Chart. Data received:', chartData);
        const ctx = document.getElementById('solarPanelChart')?.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            // console.log('No data or empty data array for Solar Panel Chart.');
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No solar panel trend data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); solarPanelChartInstance = null; }
            return;
        }

        const datasets = [];
        // Add Total Solar Input from powerData
        if (powerData && powerData.some(d => d.SolarInputWatts !== null && d.SolarInputWatts !== undefined)) {
            datasets.push({
                label: 'Total Solar Input (W)',
                data: powerData.map(item => ({ x: new Date(item.Timestamp), y: item.SolarInputWatts })),
                borderColor: CHART_COLORS.POWER_SOLAR, // Use the existing color for total solar
                yAxisID: 'yTotalSolar', // Assign to the new right y-axis
                borderDash: [5, 5], // Optional: Differentiate with a dashed line
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel1Power !== null && d.Panel1Power !== undefined)) {
            datasets.push({
                label: 'Panel 1 Power (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel1Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_1,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel2Power !== null && d.Panel2Power !== undefined)) {
            datasets.push({
                label: 'Panel 2 Power (W)', // Corresponds to panelPower3 from CSV
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel2Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_2,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Panel4Power !== null && d.Panel4Power !== undefined)) {
            datasets.push({
                label: 'Panel 4 Power (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Panel4Power })),
                borderColor: CHART_COLORS.SOLAR_PANEL_4,
                yAxisID: 'yIndividualPanels', // Assign to the left y-axis
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            // console.warn('Solar Panel Chart: No valid datasets could be formed.');
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable solar panel data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); solarPanelChartInstance = null; }
            return;
        }

        if (solarPanelChartInstance) { solarPanelChartInstance.destroy(); }

        solarPanelChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true, autoSkipPadding: 20 }, grid: { color: chartGridColor } },
                    yIndividualPanels: { // Y-axis for individual panel powers
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: 'Panel Power (W)', color: chartTextColor },
                        ticks: { color: chartTextColor, beginAtZero: true },
                        grid: { color: chartGridColor }
                    },
                    yTotalSolar: { // New Y-axis for Total Solar Input
                        type: 'linear',
                        position: 'right',
                        title: { display: true, text: 'Total Solar (W)', color: chartTextColor },
                        ticks: { color: chartTextColor, beginAtZero: true },
                        grid: { drawOnChartArea: false } // Only draw grid lines for the primary y-axis (left)
                    }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Navigation Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderNavigationChart(chartData) {
        const canvas = document.getElementById('navigationChart');
        if (!canvas) { console.error("Canvas 'navigationChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No navigation trend data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationChartInstance) { navigationChartInstance.destroy(); navigationChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.GliderSpeed !== null && d.GliderSpeed !== undefined)) {
            datasets.push({
                label: 'Glider Speed (knots)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.GliderSpeed })),
                borderColor: CHART_COLORS.NAV_SPEED,
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SpeedOverGround !== null && d.SpeedOverGround !== undefined)) {
            datasets.push({
                label: 'SOG (knots)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SpeedOverGround })),
                borderColor: CHART_COLORS.NAV_SOG,
                yAxisID: 'ySpeed', // Share Y-axis with GliderSpeed
                borderDash: [5, 5], // Dashed line
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.GliderHeading !== null && d.GliderHeading !== undefined)) {
            datasets.push({
                label: 'Glider Heading (°)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.GliderHeading })),
                borderColor: CHART_COLORS.NAV_HEADING,
                yAxisID: 'yHeading',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable navigation data found.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationChartInstance) { navigationChartInstance.destroy(); navigationChartInstance = null; }
            return;
        }

        if (navigationChartInstance) { navigationChartInstance.destroy(); }
        navigationChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm' }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Speed (knots)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yHeading: { type: 'linear', position: 'right', title: { display: true, text: 'Heading (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Navigation Ocean Current Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderNavigationCurrentChart(chartData) {
        const canvas = document.getElementById('navigationCurrentChart');
        if (!canvas) { console.error("Canvas 'navigationCurrentChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No ocean current data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); navigationCurrentChartInstance = null; }
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.OceanCurrentSpeed !== null && d.OceanCurrentSpeed !== undefined)) {
            datasets.push({
                label: 'Ocean Current Speed (kn)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentSpeed })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_SPEED,
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.OceanCurrentDirection !== null && d.OceanCurrentDirection !== undefined)) {
            datasets.push({
                label: 'Ocean Current Dir (°)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentDirection })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_DIRECTION,
                yAxisID: 'yDirection',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SpeedOverGround !== null && d.SpeedOverGround !== undefined)) {
            datasets.push({
                label: 'SOG (knots)', // Will use yDirection axis
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SpeedOverGround })),
                borderColor: CHART_COLORS.NAV_SOG.replace('0.7)', '0.5)'), // Make it 50% transparent
                yAxisID: 'ySpeed', // Plot SOG against the speed axis
                borderDash: [5, 5],
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable ocean current data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); navigationCurrentChartInstance = null; }
            return;
        }

        if (navigationCurrentChartInstance) { navigationCurrentChartInstance.destroy(); }
        navigationCurrentChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm' }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Speed (knots)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDirection: { type: 'linear', position: 'right', title: { display: true, text: 'Direction (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: 0, max: 360 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    /**
     * Renders the Navigation Heading Difference Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderNavigationHeadingDiffChart(chartData) {
        const canvas = document.getElementById('navigationHeadingDiffChart');
        if (!canvas) { console.error("Canvas 'navigationHeadingDiffChart' not found."); return; }
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No heading difference data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); navigationHeadingDiffChartInstance = null; }
            return;
        }

        const datasets = [];
        // Calculate Heading Difference
        const headingDiffData = chartData.map(item => {
            let diff = null;
            if (item.HeadingSubDegrees !== null && item.DesiredBearingDegrees !== null) {
                diff = item.HeadingSubDegrees - item.DesiredBearingDegrees;
                // Normalize to -180 to 180 range
                while (diff > 180) diff -= 360;
                while (diff < -180) diff += 360;
            }
            return { x: new Date(item.Timestamp), y: diff };
        }).filter(item => item.y !== null);

        if (headingDiffData.length > 0) {
            datasets.push({
                label: 'Sub Heading Diff (°)',
                data: headingDiffData,
                borderColor: CHART_COLORS.HEADING_DIFF,
                yAxisID: 'yDiff',
                tension: 0.1, fill: false
            });
        }

        if (chartData.some(d => d.OceanCurrentSpeed !== null && d.OceanCurrentSpeed !== undefined)) {
            datasets.push({
                label: 'Ocean Current Speed (kn)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.OceanCurrentSpeed })),
                borderColor: CHART_COLORS.OCEAN_CURRENT_SPEED.replace('1)', '0.7)'), // Slightly transparent
                borderDash: [5, 5],
                yAxisID: 'ySpeed',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No plottable heading diff data.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); navigationHeadingDiffChartInstance = null; }
            return;
        }

        if (navigationHeadingDiffChartInstance) { navigationHeadingDiffChartInstance.destroy(); }
        navigationHeadingDiffChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm' }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor, maxRotation: 0, autoSkip: true }, grid: { color: chartGridColor } },
                    ySpeed: { type: 'linear', position: 'left', title: { display: true, text: 'Ocean Current (kn)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } },
                    yDiff: { type: 'linear', position: 'right', title: { display: true, text: 'Heading Diff (°)', color: chartTextColor }, ticks: { color: chartTextColor, min: -180, max: 180 }, grid: { drawOnChartArea: false } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Refresh Data Button Logic (Moved here for better organization)
    const refreshDataBtn = document.getElementById('refreshDataBtn');
    if (refreshDataBtn) {
        refreshDataBtn.addEventListener('click', function() {
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('refresh', 'true'); // Add refresh parameter
            window.location.href = currentUrl.toString(); // Reload the page
        });
    }
    // Reminder: Revisit threshold highlighting values
    // console.log("Reminder: Revisit and fine-tune threshold highlighting values in index.html for summaries.");

    // Initialize and update the UTC clock
    updateUtcClock(); // Initial call
    setInterval(updateUtcClock, 1000); // Update every second

    
    // --- NEW: Mini Chart Rendering ---
    function renderMiniChart(canvasId, trendData, chartColor = miniChartLineColor) {
        // console.log(`Attempting to render mini chart for canvas ID: ${canvasId} with data length: ${trendData ? trendData.length : 'null'}`);
        const canvas = document.getElementById(canvasId);
        if (!canvas) {
            console.error(`Mini chart canvas with ID ${canvasId} not found.`);
            return;
        }
        const ctx = canvas.getContext('2d');

        if (miniChartInstances[canvasId]) {
            miniChartInstances[canvasId].destroy();
        }

        if (!trendData || trendData.length === 0) { // Check moved to caller, but safe to keep
            // console.log(`No data points to render for mini chart ${canvasId}.`);
            return;
        }

        const dataPoints = trendData.map(item => ({
            x: new Date(item.Timestamp), // Ensure Timestamp is parsed as Date
            y: item.value
        }));

        // Log first few parsed dates to check validity
        // if (dataPoints.length > 0) {
            // console.log(`  First 3 parsed timestamps for ${canvasId}:`, dataPoints.slice(0, 3).map(p => p.x));
        // }

        // Calculate min and max for y-axis to "stretch" the view
        let yMin = Infinity;
        let yMax = -Infinity;
        dataPoints.forEach(point => {
            if (point.y < yMin) yMin = point.y;
            if (point.y > yMax) yMax = point.y;
        });

        let yAxisMin, yAxisMax;
        const range = yMax - yMin;

        if (range === 0) { // Handle flat line data
            yAxisMin = yMin - 1; // Add some arbitrary padding
            yAxisMax = yMax + 1;
        } else {
            const padding = range * 0.10; // 10% padding
            yAxisMin = yMin - padding;
            yAxisMax = yMax + padding;
        }

        // console.log(`Rendering Chart.js instance for ${canvasId}`);
        miniChartInstances[canvasId] = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    data: dataPoints,
                    borderColor: chartColor, // Use the passed chartColor
                    borderWidth: 1.5, // Keep it slightly thicker
                    pointRadius: 0, // No points on mini charts
                    tension: 0.1,   // straight line for mini trend
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false, // No animation for mini charts
                scales: {
                    x: {
                        type: 'time', 
                        display: false, // Final: Hide x-axis
                        // ticks: { color: 'lime', font: { size: 7 }, autoSkip: true, maxRotation: 0, minRotation: 0 }, // TEMPORARY: For x-axis debugging
                        grid: { display: false } // Optionally hide x-axis grid lines for mini chart
                    }, 
                    y: { 
                        display: false, // Keep y-axis hidden for final appearance
                        min: yAxisMin, // Set calculated min
                        max: yAxisMax, // Set calculated max
                        // grace: '10%' // Not needed if min/max are manually set with padding
                    }
                },
                plugins: {
                    legend: { 
                        display: false // Keep legend hidden
                    }, 
                    tooltip: { enabled: false } // Keep tooltips disabled
                },
                layout: {
                    padding: { // Minimal padding
                        left: 1,
                        right: 1,
                        top: 3,
                        bottom: 1
                    }
                }
            }
        });
        // console.log(`Mini chart ${canvasId} should be rendered.`);
    }

    // --- NEW: Initialize Mini Charts ---
    function initializeMiniCharts() {
        // console.log("Initializing mini charts...");
        const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
        summaryCards.forEach(card => {
            const category = card.dataset.category; // e.g., "power", "ctd", "navigation"
            const miniChartCanvasId = `mini${category === 'waves' ? 'Wave' : category.charAt(0).toUpperCase() + category.slice(1)}Chart`;
            const canvasElement = document.getElementById(miniChartCanvasId);
            // console.log(`Processing mini chart for category: ${category}, canvas ID: ${miniChartCanvasId}`);

            if (canvasElement) { // Only try to render if a canvas exists
                const trendDataJson = card.dataset.miniTrend;
                // console.log(`  Raw mini-trend JSON for ${category}:`, trendDataJson);
                if (trendDataJson) {
                    // Ensure the string is not empty before trying to parse
                    if (trendDataJson.trim() === "") {
                        // console.log(`  Skipping empty mini-trend JSON for ${category}.`);
                        return; // Skip to the next card
                    }
                    try {
                        const trendData = JSON.parse(trendDataJson);
                        if (trendData && trendData.length > 0) {
                            let specificColor = miniChartLineColor; // Default color
                            // Assign specific colors based on category, matching large charts
                            switch (category) {
                                case 'power': // NetPowerWatts mini-trend. Using SolarInputWatts color as a proxy.
                                    specificColor = CHART_COLORS.POWER_SOLAR;
                                    break;
                                case 'ctd': // WaterTemperature mini-trend
                                    specificColor = CHART_COLORS.CTD_TEMP;
                                    break;
                                case 'weather': // WindSpeed mini-trend
                                    specificColor = CHART_COLORS.WEATHER_WIND_SPEED;
                                    break;
                                case 'waves': // SignificantWaveHeight mini-trend
                                    specificColor = CHART_COLORS.WAVES_SIG_HEIGHT;
                                    break;
                                case 'vr2c': // DetectionCount mini-trend
                                    specificColor = CHART_COLORS.VR2C_DETECTION;
                                    break;
                                case 'fluorometer': // C1_Avg mini-trend
                                    specificColor = CHART_COLORS.FLUORO_C_AVG_PRIMARY;
                                    break;
                                case 'navigation': // GliderSpeed mini-trend
                                    specificColor = CHART_COLORS.NAV_SPEED;
                                    break;
                            }
                            renderMiniChart(miniChartCanvasId, trendData, specificColor);
                        } else {
                            // console.log(`  No data points to render for mini chart ${category} (data is empty or null).`);
                        }
                    } catch (e) {
                        console.error(`Error parsing mini-trend data for ${category}:`, e, `Problematic JSON: "${trendDataJson}"`);
                    }
                }
            }
        });
    }

    // --- NEW: Left Panel Click Handler ---
    function handleLeftPanelClicks() {
        const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
        const detailViews = document.querySelectorAll('#main-display-area .category-detail-view');

        summaryCards.forEach(card => {
            card.addEventListener('click', function() {
                summaryCards.forEach(c => c.classList.remove('active-card'));
                this.classList.add('active-card');
                const category = this.dataset.category;
                detailViews.forEach(view => view.style.display = 'none');
                const activeDetailView = document.getElementById(`detail-${category}`);
                if (activeDetailView) {
                    activeDetailView.style.display = 'block';

                    // Special handling for Waves to trigger spectrum load when its detail view is shown
                    if (category === 'waves') {
                        fetchAndRenderWaveSpectrum(missionId);
                        // Fetch and render marine forecast when Waves detail is shown
                        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));

                    } else if (category === 'navigation') { // Fetch telemetry data for navigation chart
                        fetchChartData('telemetry', missionId, hoursBack).then(data => {
                            renderNavigationChart(data);
                            renderNavigationCurrentChart(data);
                            renderNavigationHeadingDiffChart(data);
                        });
                    }
                } // <-- Missing closing brace for if (activeDetailView)
            }); // <-- Missing closing brace for card.addEventListener
        });
    } // <-- Closing brace for handleLeftPanelClicks function

    // Initialize new UI features
    initializeMiniCharts();
    handleLeftPanelClicks();

    // Initial data load for the default active view (Navigation)
    // This ensures the main chart for the default view loads without needing a click.
    const defaultActiveCategory = document.querySelector('#left-nav-panel .summary-card.active-card')?.dataset.category;
    if (defaultActiveCategory === 'navigation') {
        fetchChartData('telemetry', missionId, hoursBack).then(data => {
            renderNavigationChart(data);
            renderNavigationCurrentChart(data);
            renderNavigationHeadingDiffChart(data);
        });
    } else if (defaultActiveCategory === 'waves') {
        // If waves is the default, also fetch its marine forecast
        fetchAndRenderWaveSpectrum(missionId); // Already there for spectrum
        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));

    }
    // console.log("Dashboard setup complete");
});