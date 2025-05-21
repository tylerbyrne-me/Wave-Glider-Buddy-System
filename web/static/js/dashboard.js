document.addEventListener('DOMContentLoaded', function() {
    const missionId = document.body.dataset.missionId; // Get mission ID from body's data attribute
    const hoursBack = 72; // Default lookback period for charts
    const missionSelector = document.getElementById('missionSelector');
    const isRealtimeMission = document.body.dataset.isRealtime === 'true'; // Get realtime status from body's data attribute
    const urlParams = new URLSearchParams(window.location.search);

    let powerChartInstance = null; // Use let as these will be reassigned
    let ctdChartInstance = null;
    let weatherSensorChartInstance = null;
    let waveChartInstance = null;

    // Define colors for dark mode charts
    const chartTextColor = 'rgba(255, 255, 255, 0.8)';
    const chartGridColor = 'rgba(255, 255, 255, 0.1)';

    const currentSource = urlParams.get('source') || 'remote'; // Default to remote
    const currentLocalPath = urlParams.get('local_path') || '';

    // Auto-refresh and Countdown variables
    const autoRefreshIntervalMinutes = 5; // Must match the interval logic
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
                // The page reload is handled by the setTimeout below
            } else {
                remainingSeconds--;
            }
        }

        // Initial display update
        updateCountdownDisplay();

        // Update every second
        countdownTimer = setInterval(updateCountdownDisplay, 1000);
    }



    if (missionSelector) {
        missionSelector.addEventListener('change', function() {
            const newMissionId = this.value;
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('mission', newMissionId);
            // missionId variable updated for current session if needed, though page reload handles it
            window.location.href = currentUrl.toString();
        });
    }

    // Data Source Modal Logic
    const dataSourceModal = document.getElementById('dataSourceModal');
    if (dataSourceModal) {
        const localPathInputGroup = document.getElementById('localPathInputGroup');
        const sourceLocalRadio = document.getElementById('sourceLocal');
        const sourceRemoteRadio = document.getElementById('sourceRemote');
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
            let newLocalPath = ''; // Use let as it might be reassigned
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
            // Bootstrap 5 modal needs to be hidden manually before page reload
            const modalInstance = bootstrap.Modal.getInstance(dataSourceModal); // Use const
            if (modalInstance) {
                modalInstance.hide();
            }
            // Add a slight delay for modal to hide before redirecting
            setTimeout(() => { window.location.href = currentUrl.toString(); }, 150);
        });
    }

    // Auto-refresh logic for real-time missions
    if (isRealtimeMission) {
        console.log(`This is a real-time mission page (${missionId}). Auto-refresh enabled for every ${autoRefreshIntervalMinutes} minutes.`);
        startCountdownTimer(); // Start the countdown immediately

        setTimeout(function() {
            // Check if a modal is open, don't refresh if it is to avoid interrupting user
            if (!document.querySelector('.modal.show')) {
                window.location.reload(true); // true forces a reload from the server, not cache
            }
        }, autoRefreshIntervalMinutes * 60 * 1000); // Schedule the page reload
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
        const chartCanvas = document.getElementById(`${reportType}Chart`); // Assuming chart IDs match reportType + "Chart"
        const spinner = chartCanvas ? chartCanvas.parentElement.querySelector('.chart-spinner') : null;
        if (spinner) spinner.style.display = 'block';

        try {
            let apiUrl = `/api/data/${reportType}/${mission}?hours_back=${hours}`;
            apiUrl += `&source=${currentSource}`;
            if (currentSource === 'local' && currentLocalPath) {
                apiUrl += `&local_path=${encodeURIComponent(currentLocalPath)}`;
            }
            // Check if the main page URL has a refresh parameter, and pass it along to API calls
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
     * Renders the Power Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderPowerChart(chartData) {
        console.log('Attempting to render Power Chart. Data received:', chartData);
        const ctx = document.getElementById('powerChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none'; // Hide spinner before rendering or showing "no data"


        if (!chartData || chartData.length === 0) {
            console.log('No data or empty data array for Power Chart.');
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
                borderColor: 'rgba(54, 162, 235, 1)', // Blue - Keep
                yAxisID: 'yBattery', // Assign to new right-hand Y-axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SolarInputWatts !== null && d.SolarInputWatts !== undefined)) {
            datasets.push({
                label: 'Solar Input (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SolarInputWatts })),
                borderColor: 'rgba(255, 159, 64, 0.7)', // Orange, semi-transparent
                yAxisID: 'ySolar', // Assign to left-hand Y-axis
                borderDash: [5, 5], // Dotted line
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.PowerDrawWatts !== null && d.PowerDrawWatts !== undefined)) {
            datasets.push({
                label: 'Power Draw (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.PowerDrawWatts })),
                borderColor: 'rgba(255, 99, 132, 1)', // Red
                yAxisID: 'ySolar', // Share with Solar Input
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            console.warn('Power Chart: No valid datasets could be formed from the provided chartData.');
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

    // Fetch and render the power chart on page load
    fetchChartData('power', missionId, hoursBack).then(data => {
        renderPowerChart(data); // data can be null or empty array, renderPowerChart handles this
    });

    /**
     * Renders the CTD Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    function renderCtdChart(chartData) { // This function was missing in the previous diff
        console.log('Attempting to render CTD Chart. Data received:', chartData);
        const ctx = document.getElementById('ctdChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            console.log('No data or empty data array for CTD Chart.');
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
                borderColor: 'rgba(0, 191, 255, 1)', // Deep Sky Blue (was Wave Height color)
                yAxisID: 'yTemp', // Assign to a specific Y axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Salinity !== null && d.Salinity !== undefined)) {
            datasets.push({
                label: 'Salinity (PSU)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Salinity })),
                borderColor: 'rgba(255, 105, 180, 1)', // Hot Pink (was Wave Period color)
                yAxisID: 'ySalinity', // Assign to a different Y axis
                tension: 0.1, fill: false
            });
        }
        // Add other CTD metrics (Conductivity, DissolvedOxygen, Pressure) similarly, potentially on new axes or separate charts

        if (datasets.length === 0) {
            console.warn('CTD Chart: No valid datasets could be formed from the provided chartData.');
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
        renderCtdChart(data);
    });

    /**
     * Renders the Weather Sensor Chart using Chart.js.
     * @param {Array<Object>|null} chartData - The data array fetched from the API.
     */
    // Fetch and render the Weather Sensor chart on page load
    fetchChartData('weather', missionId, hoursBack).then(data => {
        renderWeatherSensorChart(data);
    });


    function renderWeatherSensorChart(chartData) { // This function was missing in the previous diff
        console.log('Attempting to render Weather Chart. Data received:', chartData);
        const ctx = document.getElementById('weatherSensorChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

        if (!chartData || chartData.length === 0) {
            console.log('No data or empty data array for Weather Chart.');
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
                borderColor: 'rgba(255, 99, 71, 1)', // Tomato Red for Weather Temp
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindSpeed !== null && d.WindSpeed !== undefined)) {
            datasets.push({
                label: 'Wind Speed (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindSpeed })),
                borderColor: 'rgba(60, 179, 113, 1)', // Medium Sea Green for Wind Speed
                yAxisID: 'yWind',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindGust !== null && d.WindGust !== undefined)) {
            datasets.push({
                label: 'Wind Gust (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindGust })),
                borderColor: 'rgba(144, 238, 144, 0.7)', // Lighter, semi-transparent green for Gusts
                borderDash: [5, 5], // Dashed line for gusts
                yAxisID: 'yWind', // Share axis with WindSpeed
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            console.warn('Weather Chart: No valid datasets could be formed from the provided chartData.');
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
            if (forecastData.forecast_type === 'marine') {
                forecastTitle += ' (Marine)';
            } else if (forecastData.forecast_type === 'general') {
                forecastTitle += ' (General/Land-based)';
            }
            initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>`; // Prepend title

            const hourly = forecastData.hourly;
            const totalHoursAvailable = hourly.time.length;
            const isMarineForecast = forecastData.forecast_type === 'marine';

            const createTableHtml = (startHour, endHour) => {
                let tableHtml = '<table class="table table-sm table-striped table-hover">';
                tableHtml += '<thead><tr>' +
                             '<th>Time</th>' +
                             '<th>Weather</th>' +
                             '<th>Air Temp (°C)</th>' +
                             '<th>Precip (mm)</th>';
                if (isMarineForecast) {
                    tableHtml += '<th>Wind (m/s @10m)</th><th>Wind Dir (°)</th>' +
                                 '<th>Wave Ht (m)</th><th>Wave Period (s)</th><th>Wave Dir (°)</th>' +
                                 '<th>Current (m/s)</th><th>Current Dir (°)</th>';
                } else { // General forecast
                    tableHtml += '<th>Wind (m/s @10m)</th><th>Wind Dir (°)</th>';
                }
                tableHtml += '</tr></thead>';
                tableHtml += '<tbody>';

                for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                    const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                    const airTemp = hourly.temperature_2m[i] !== null ? hourly.temperature_2m[i].toFixed(1) : 'N/A';
                    const precip = hourly.precipitation[i] !== null ? hourly.precipitation[i].toFixed(1) : 'N/A';
                    const windSpeed = hourly.windspeed_10m[i] !== null ? hourly.windspeed_10m[i].toFixed(1) : 'N/A';
                    const windDir = hourly.winddirection_10m[i] !== null ? hourly.winddirection_10m[i].toFixed(0) : 'N/A';
                    
                    let waveHeight = 'N/A', wavePeriod = 'N/A', waveDir = 'N/A';
                    let currentSpeed = 'N/A', currentDir = 'N/A';

                    if (isMarineForecast) {
                        waveHeight = hourly.wave_height && hourly.wave_height[i] !== null ? hourly.wave_height[i].toFixed(1) : 'N/A';
                        wavePeriod = hourly.wave_period && hourly.wave_period[i] !== null ? hourly.wave_period[i].toFixed(1) : 'N/A';
                        waveDir = hourly.wave_direction && hourly.wave_direction[i] !== null ? hourly.wave_direction[i].toFixed(0) : 'N/A';
                        currentSpeed = hourly.ocean_current_velocity && hourly.ocean_current_velocity[i] !== null ? hourly.ocean_current_velocity[i].toFixed(2) : 'N/A';
                        currentDir = hourly.ocean_current_direction && hourly.ocean_current_direction[i] !== null ? hourly.ocean_current_direction[i].toFixed(0) : 'N/A';
                    }

                    const weatherCode = hourly.weathercode[i] !== null ? hourly.weathercode[i] : 'N/A';
                    let weatherDisplay;
                    const description = getWeatherDescription(weatherCode);

                    if (description !== 'Unknown') {
                        weatherDisplay = description;
                    } else if (weatherCode !== 'N/A') {
                        weatherDisplay = `Code: ${weatherCode}`;
                    } else {
                        weatherDisplay = 'N/A';
                    }

                    tableHtml += `<tr>` +
                                 `<td>${time}</td>` +
                                 `<td>${weatherDisplay}</td>` +
                                 `<td>${airTemp}</td>` +
                                 `<td>${precip}</td>` +
                                 `<td>${windSpeed}</td><td>${windDir}</td>`;
                    if (isMarineForecast) {
                        tableHtml += `<td>${waveHeight}</td><td>${wavePeriod}</td><td>${waveDir}</td>` +
                                     `<td>${currentSpeed}</td><td>${currentDir}</td>`;
                    }
                    tableHtml += `</tr>`;
                }
                tableHtml += '</tbody></table>';
                return tableHtml;
            };

            const initialHours = 12;
            // Append the table to the initial container, after the title
            initialContainer.innerHTML += createTableHtml(0, initialHours);

            const extendedStartHour = initialHours;
            const maxExtendedHours = 24; // Show up to 24 hours total when expanded (can be increased up to 48 or totalHoursAvailable)

            if (totalHoursAvailable > initialHours) {
                extendedContainer.innerHTML = createTableHtml(extendedStartHour, Math.min(totalHoursAvailable, maxExtendedHours));
                toggleButton.style.display = 'block'; // Show the button
                
                const collapseElement = document.getElementById('forecastExtended');
                // Listener to update button text (optional, Bootstrap handles aria-expanded)
                collapseElement.addEventListener('show.bs.collapse', function () {
                    toggleButton.textContent = 'Show Less';
                });
                collapseElement.addEventListener('hide.bs.collapse', function () {
                    toggleButton.textContent = 'Show More';
                });
                // Set initial text based on current state (e.g. if it was previously expanded and page reloaded)
                if (!collapseElement.classList.contains('show')) {
                     toggleButton.textContent = 'Show More';
                } else {
                     toggleButton.textContent = 'Show Less';
                }
            } else {
                if (extendedContainer) extendedContainer.innerHTML = '';
                if (toggleButton) toggleButton.style.display = 'none'; // Hide button if no more data
            }
        }
        // Ensure spinner is hidden and content area is visible
        // Spinner management removed for forecast
        initialContainer.style.display = 'block';
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
        console.log('Attempting to render Wave Chart. Data received:', chartData);
        const ctx = document.getElementById('waveChart').getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        if (spinner) spinner.style.display = 'none';

                if (!chartData || chartData.length === 0) {
            console.log('No data or empty data array for Wave Chart.');
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
                borderColor: 'rgba(255, 206, 86, 1)', // Yellow (was CTD Temp color)
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WavePeriod !== null && d.WavePeriod !== undefined)) {
            datasets.push({
                label: 'Wave Period (s)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WavePeriod })),
                borderColor: 'rgba(153, 102, 255, 1)', // Purple (was CTD Salinity color)
                yAxisID: 'yPeriod',
                tension: 0.1, fill: false
            });
        }

        if (datasets.length === 0) {
            console.warn('Wave Chart: No valid datasets could be formed from the provided chartData.');
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

    // Fetch and render the Wave chart on page load
    fetchChartData('waves', missionId, hoursBack).then(data => {
        renderWaveChart(data);
    }); // This call was missing in the previous diff
    
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
});