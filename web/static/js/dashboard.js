document.addEventListener('DOMContentLoaded', function() {
    const missionId = document.body.dataset.missionId; // Get mission ID from body's data attribute
    const hoursBack = 72; // Default lookback period for charts

    let powerChartInstance = null;
    let ctdChartInstance = null;
    let weatherSensorChartInstance = null;
    let waveChartInstance = null;

    // Define colors for dark mode charts
    const chartTextColor = 'rgba(255, 255, 255, 0.8)';
    const chartGridColor = 'rgba(255, 255, 255, 0.1)';

    async function fetchChartData(reportType, mission, hours) {
        try {
            const response = await fetch(`/api/data/${reportType}/${mission}?hours_back=${hours}`);
            if (!response.ok) {
                console.error(`Error fetching ${reportType} data: ${response.statusText}`);
                const errorText = await response.text();
                console.error(`Server response: ${errorText}`);
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Network error fetching ${reportType} data:`, error);
            return null;
        }
    }

    function renderPowerChart(chartData) {
        const ctx = document.getElementById('powerChart').getContext('2d');

        if (!chartData || chartData.length === 0) {
            // Display a message on the canvas if no data
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No power trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        const datasets = [];
        // Dynamically add datasets based on available data
        if (chartData.some(d => d.BatteryWattHours !== null && d.BatteryWattHours !== undefined)) {
            datasets.push({
                label: 'Battery (Wh)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.BatteryWattHours })),
                borderColor: 'rgba(54, 162, 235, 1)', // Blue
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.SolarInputWatts !== null && d.SolarInputWatts !== undefined)) {
            datasets.push({
                label: 'Solar Input (W)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SolarInputWatts })),
                borderColor: 'rgba(255, 159, 64, 1)', // Orange
                tension: 0.1, fill: false
            });
        }
        // Add more power metrics if needed (e.g., PowerDrawWatts, NetPowerWatts)

        if (powerChartInstance) {
            powerChartInstance.destroy(); // Clear previous chart if any
        }

        powerChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    y: { title: { display: true, text: 'Power Value', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }
    // --- Weather Forecast ---
    async function fetchForecastData(mission) {
        try {
            // We can add lat/lon here if we want to allow manual override later
            const response = await fetch(`/api/forecast/${mission}`);
            if (!response.ok) {
                console.error(`Error fetching forecast data: ${response.statusText}`);
                const errorText = await response.text();
                console.error(`Server response: ${errorText}`);
                return null;
            }
            return await response.json();
        } catch (error) {
            console.error(`Network error fetching forecast data:`, error);
            return null;
        }
    }

    function renderForecast(forecastData) {
        const forecastContainer = document.getElementById('forecastDisplay');
        if (!forecastData || !forecastData.hourly || !forecastData.hourly.time || forecastData.hourly.time.length === 0) {
            forecastContainer.innerHTML = '<p class="text-muted">Forecast data is currently unavailable.</p>';
            return;
        }

        const hourly = forecastData.hourly;
        let tableHtml = '<table class="table table-sm table-striped table-hover">';
        tableHtml += '<thead><tr><th>Time</th><th>Temp (°C)</th><th>Precip (mm)</th><th>Wind (m/s)</th><th>Weather</th></tr></thead>';
        tableHtml += '<tbody>';

        // Display up to 24 hours of forecast or available data
        const displayLimit = Math.min(hourly.time.length, 24);

        for (let i = 0; i < displayLimit; i++) {
            const time = new Date(hourly.time[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            const temp = hourly.temperature_2m[i] !== null ? hourly.temperature_2m[i].toFixed(1) : 'N/A';
            const precip = hourly.precipitation[i] !== null ? hourly.precipitation[i].toFixed(1) : 'N/A';
            const wind = hourly.windspeed_10m[i] !== null ? hourly.windspeed_10m[i].toFixed(1) : 'N/A';
            // You might want a mapping for weathercode to a description or icon
            const weatherCode = hourly.weathercode[i] !== null ? hourly.weathercode[i] : 'N/A';

            tableHtml += `<tr><td>${time}</td><td>${temp}</td><td>${precip}</td><td>${wind}</td><td>${weatherCode}</td></tr>`;
        }
        tableHtml += '</tbody></table>';
        forecastContainer.innerHTML = tableHtml;
    }

    // Fetch and render forecast
    fetchForecastData(missionId).then(data => {
        renderForecast(data);
    });

     function renderCtdChart(chartData) {
        const ctx = document.getElementById('ctdChart').getContext('2d');

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No CTD trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.WaterTemperature !== null && d.WaterTemperature !== undefined)) {
            datasets.push({
                label: 'Water Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WaterTemperature })),
                borderColor: 'rgba(255, 99, 132, 1)', // Red
                yAxisID: 'yTemp', // Assign to a specific Y axis
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.Salinity !== null && d.Salinity !== undefined)) {
            datasets.push({
                label: 'Salinity (PSU)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.Salinity })),
                borderColor: 'rgba(75, 192, 192, 1)', // Green
                yAxisID: 'ySalinity', // Assign to a different Y axis
                tension: 0.1, fill: false
            });
        }
        // Add other CTD metrics (Conductivity, DissolvedOxygen, Pressure) similarly, potentially on new axes or separate charts

        if (ctdChartInstance) {
            ctdChartInstance.destroy();
        }

        ctdChartInstance = new Chart(ctx, {
            type: 'line',
            data: { datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    ySalinity: { type: 'linear', position: 'right', title: { display: true, text: 'Salinity (PSU)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false, color: chartGridColor } } // Hide grid for secondary axis
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the power chart on page load
    fetchChartData('power', missionId, hoursBack).then(data => {
        renderPowerChart(data); // data can be null or empty array, renderPowerChart handles this
    });
    // Fetch and render the CTD chart on page load
    fetchChartData('ctd', missionId, hoursBack).then(data => {
        renderCtdChart(data);
    });
    function renderWeatherSensorChart(chartData) {
        const ctx = document.getElementById('weatherSensorChart').getContext('2d');

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No weather sensor trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.AirTemperature !== null && d.AirTemperature !== undefined)) {
            datasets.push({
                label: 'Air Temp (°C)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.AirTemperature })),
                borderColor: 'rgba(255, 99, 132, 1)', // Red
                yAxisID: 'yTemp',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindSpeed !== null && d.WindSpeed !== undefined)) {
            datasets.push({
                label: 'Wind Speed (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindSpeed })),
                borderColor: 'rgba(54, 162, 235, 1)', // Blue
                yAxisID: 'yWind',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WindGust !== null && d.WindGust !== undefined)) {
            datasets.push({
                label: 'Wind Gust (kt)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WindGust })),
                borderColor: 'rgba(75, 192, 192, 1)', // Teal/Green
                borderDash: [5, 5], // Dashed line for gusts
                yAxisID: 'yWind', // Share axis with WindSpeed
                tension: 0.1, fill: false
            });
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
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yTemp: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    yWind: { type: 'linear', position: 'right', title: { display: true, text: 'Wind (kt)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { drawOnChartArea: false, color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }

    // Fetch and render the Weather Sensor chart on page load
    fetchChartData('weather', missionId, hoursBack).then(data => {
        renderWeatherSensorChart(data);
    });
    function renderWaveChart(chartData) {
        const ctx = document.getElementById('waveChart').getContext('2d');

        if (!chartData || chartData.length === 0) {
            ctx.font = "16px Arial";
            ctx.fillStyle = "grey";
            ctx.textAlign = "center";
            ctx.fillText("No wave trend data available to display.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        const datasets = [];
        if (chartData.some(d => d.SignificantWaveHeight !== null && d.SignificantWaveHeight !== undefined)) {
            datasets.push({
                label: 'Sig. Wave Height (m)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.SignificantWaveHeight })),
                borderColor: 'rgba(54, 162, 235, 1)', // Blue
                yAxisID: 'yHeight',
                tension: 0.1, fill: false
            });
        }
        if (chartData.some(d => d.WavePeriod !== null && d.WavePeriod !== undefined)) {
            datasets.push({
                label: 'Wave Period (s)',
                data: chartData.map(item => ({ x: new Date(item.Timestamp), y: item.WavePeriod })),
                borderColor: 'rgba(255, 99, 132, 1)', // Red
                yAxisID: 'yPeriod',
                tension: 0.1, fill: false
            });
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
                    x: { type: 'time', time: { unit: 'hour', tooltipFormat: 'MMM d, yyyy HH:mm', displayFormats: { hour: 'HH:mm' } }, title: { display: true, text: 'Time', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
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
    });
});