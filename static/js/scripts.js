const pages = document.querySelector('.pages');
const sliderContainer = document.querySelector('.slider-container');
const dots = document.querySelectorAll('.dot');
const numPages = dots.length;
const pageWidth = 100;
let currentPage = 0;
let startX = 0;
let currentTranslate = 0;
let prevTranslate = 0;
let isDragging = false;
let prevX = 0;
let prevTime = 0;
let velocity = 0;

// Initialize Socket.IO
const socket = io();

// Theme toggle functionality
const themeToggle = document.getElementById('theme-toggle');
themeToggle.addEventListener('change', () => {
    document.body.dataset.theme = themeToggle.checked ? 'dark' : 'light';
    console.log('Emitting set_setting', { key: 'dark_mode', value: themeToggle.checked });
    socket.emit('set_setting', { key: 'dark_mode', value: themeToggle.checked });
});

function updatePagination(snap = true) {
    if (snap) {
        pages.style.transition = 'transform 0.3s ease';
        pages.style.transform = `translateX(-${currentPage * pageWidth}%)`;
    }
    dots.forEach((dot, index) => {
        dot.classList.toggle('active', index === currentPage);
    });
}

function setTranslate(delta) {
    currentTranslate = prevTranslate + delta;
    pages.style.transition = 'none';
    pages.style.transform = `translateX(${currentTranslate}%)`;
}

function onStart(e) {
    if (e.target.tagName === 'INPUT' || e.target.closest('.toggle')) return;
    const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
    startX = clientX;
    prevX = clientX;
    prevTime = Date.now();
    velocity = 0;
    prevTranslate = -currentPage * pageWidth;
    isDragging = true;
    pages.style.transition = 'none';
    if (e.type === 'mousedown') {
        document.body.style.cursor = 'grabbing';
    }
    e.preventDefault();
}

function onMove(e) {
    if (!isDragging) return;
    const clientX = e.type.includes('touch') ? e.touches[0].clientX : e.clientX;
    const currentTime = Date.now();
    let dt = currentTime - prevTime;
    dt = Math.max(dt, 1);
    if (dt > 0) {
        const dx = clientX - prevX;
        velocity = dx / dt;
    }
    prevX = clientX;
    prevTime = currentTime;
    const deltaX = clientX - startX;
    const diff = (deltaX / sliderContainer.clientWidth) * pageWidth;
    setTranslate(diff);
}

function onEnd() {
    if (!isDragging) return;
    isDragging = false;
    const movedBy = currentTranslate + currentPage * pageWidth;
    let shouldChange = false;
    if (movedBy < - (pageWidth / 2) && currentPage < numPages - 1) {
        currentPage++;
        shouldChange = true;
    } else if (movedBy > (pageWidth / 2) && currentPage > 0) {
        currentPage--;
        shouldChange = true;
    }
    if (!shouldChange) {
        const velocityThreshold = 0.5; // px/ms
        if (velocity < -velocityThreshold && currentPage < numPages - 1) {
            currentPage++;
        } else if (velocity > velocityThreshold && currentPage > 0) {
            currentPage--;
        }
    }
    document.body.style.cursor = '';
    updatePagination();
}

// Touch events
sliderContainer.addEventListener('touchstart', onStart, { passive: false });
sliderContainer.addEventListener('touchmove', onMove, { passive: false });
sliderContainer.addEventListener('touchend', onEnd);

// Mouse events
sliderContainer.addEventListener('mousedown', onStart);
document.addEventListener('mousemove', onMove);
document.addEventListener('mouseup', onEnd);
sliderContainer.style.cursor = 'grab';

// Clickable dots
dots.forEach((dot, index) => {
    dot.addEventListener('click', () => {
        currentPage = index;
        updatePagination();
    });
});

// Handle sliders and toggles
document.querySelectorAll('.control').forEach(control => {
    const slider = control.querySelector('input[type="range"]');
    const percentage = control.querySelector('.percentage');
    const toggle = control.querySelector('.on-off-toggle input[type="checkbox"]');
    const isColorToggle = control.classList.contains('color-toggle');
    const colorLabel = isColorToggle ? control.querySelector('.color-label') : null;

    if (slider && percentage && toggle) {
        const updatePercentage = () => {
            percentage.textContent = `${slider.value}%`;
        };

        slider.addEventListener('input', (e) => {
            e.target.style.setProperty('--value', e.target.value + '%');
            updatePercentage();
            if (!isColorToggle) {
                toggle.checked = slider.value > 0;
            } else {
                const val = parseInt(e.target.value);
                control.classList.toggle('lit', val > 0);
            }
        });

        slider.style.setProperty('--value', slider.value + '%');
        updatePercentage();
        if (!isColorToggle) {
            toggle.checked = parseInt(slider.value, 10) > 0;
        } else {
            const val = parseInt(slider.value);
            control.classList.toggle('lit', val > 0);
        }
    }
});

// Server communication
function sendBrightness(lightId, value) {
    console.log('Emitting set_brightness', { light_id: lightId, value: value });
    socket.emit('set_brightness', { light_id: lightId, value: value });
}

function sendToggle(lightId) {
    console.log('Emitting toggle_color', { light_id: lightId });
    socket.emit('toggle_color', { light_id: lightId });
}

function lockControl(control) {
    control.classList.add('locked');
}

function unlockControl(control) {
    control.classList.remove('locked');
}

// Assign light IDs to controls (sliders 1-8)
const lightControls = Array.from(document.querySelectorAll('.page:not(:last-child) .control'));
lightControls.forEach((control, index) => {
    control.dataset.lightId = index + 1;
    const lightId = parseInt(control.dataset.lightId);
    const slider = control.querySelector('input[type="range"]');
    const toggle = control.querySelector('.on-off-toggle input[type="checkbox"]');
    const isColorToggle = control.classList.contains('color-toggle');

    if (slider) {
        slider.addEventListener('input', (e) => {
            if (control.classList.contains('locked') || control.classList.contains('disabled')) return;
            sendBrightness(lightId, parseInt(e.target.value));
        });

        // Ignore server updates during drag
        slider.addEventListener('pointerdown', () => {
            control.classList.add('sync-lock');
        });
    }

    if (toggle) {
        toggle.addEventListener('change', () => {
            if (control.classList.contains('locked') || control.classList.contains('disabled')) return;
            if (isColorToggle) {
                // Optimistic update
                const colorLabel = control.querySelector('.color-label');
                if (toggle.checked) {
                    control.classList.add('red-mode');
                    if (colorLabel) colorLabel.textContent = 'Red';
                } else {
                    control.classList.remove('red-mode');
                    if (colorLabel) colorLabel.textContent = 'White';
                }
                lockControl(control);
                sendToggle(lightId);
            } else {
                const target = toggle.checked ? 100 : 0;
                lockControl(control);
                console.log('Emitting ramp_brightness', { light_id: lightId, target: target });
                socket.emit('ramp_brightness', { light_id: lightId, target: target });
            }
        });
    }
});

// Clear sync-lock after drag (with delay for pending broadcasts)
document.addEventListener('pointerup', () => {
    setTimeout(() => {
        lightControls.forEach(control => {
            control.classList.remove('sync-lock');
        });
    }, 500); // Adjust if needed
});

// Handle relay toggles
const relayNames = ['water', 'fridge_and_oven', 'floodlights', 'lighting_circuits'];
const relayControls = document.querySelectorAll('.page:last-child .control');
relayControls.forEach((control, index) => {
    const toggle = control.querySelector('input[type="checkbox"]');
    const name = relayNames[index];
    toggle.addEventListener('change', () => {
        console.log('Emitting set_relay', { name: name, state: toggle.checked });
        socket.emit('set_relay', { name: name, state: toggle.checked });
    });
});

// Handle scene buttons interlock and toast
const sceneBtns = document.querySelectorAll('.scene-btn');
sceneBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        sceneBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const sceneId = btn.dataset.sceneId;
        if (sceneId) {
            lightControls.forEach(lockControl);
            console.log('Emitting apply_scene', { scene_id: sceneId });
            socket.emit('apply_scene', { scene_id: sceneId });
        }
    });
});

// Settings modal functions
function openSettings() {
    document.getElementById('settings-modal').style.display = 'flex';
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

// Click outside to close
document.getElementById('settings-modal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('settings-modal')) {
        closeSettings();
    }
});

// Shutdown button
document.querySelector('.shutdown-btn').addEventListener('click', () => {
    document.getElementById('shutdown-confirm-modal').style.display = 'flex';
});

// Shutdown confirm modal
document.querySelector('.confirm-btn.no').addEventListener('click', () => {
    document.getElementById('shutdown-confirm-modal').style.display = 'none';
});

document.querySelector('.confirm-btn.yes').addEventListener('click', () => {
    document.getElementById('shutdown-confirm-modal').style.display = 'none';
    showToast('Shutting down the system...', 'warning');
    console.log('Emitting shutdown_system');
    socket.emit('shutdown_system');
});

document.getElementById('shutdown-confirm-modal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('shutdown-confirm-modal')) {
        document.getElementById('shutdown-confirm-modal').style.display = 'none';
    }
});

// Additional settings change listeners
document.getElementById('auto-theme-toggle').addEventListener('change', (e) => {
    console.log('Emitting set_setting', { key: 'auto_theme', value: e.target.checked });
    socket.emit('set_setting', { key: 'auto_theme', value: e.target.checked });
});

document.querySelector('.evening-offset').addEventListener('change', (e) => {
    console.log('Emitting set_setting', { key: 'evening_offset', value: e.target.value });
    socket.emit('set_setting', { key: 'evening_offset', value: e.target.value });
    updateResultantTimes();
});

document.querySelector('.sunrise-offset').addEventListener('change', (e) => {
    console.log('Emitting set_setting', { key: 'sunrise_offset', value: e.target.value });
    socket.emit('set_setting', { key: 'sunrise_offset', value: e.target.value });
    updateResultantTimes();
});

document.querySelector('.night-time').addEventListener('change', (e) => {
    console.log('Emitting set_setting', { key: 'night_time', value: e.target.value });
    socket.emit('set_setting', { key: 'night_time', value: e.target.value });
});

// Fullscreen toggle button
const fullscreenBtn = document.getElementById('fullscreen-toggle-btn');

let isKitchenScreen = false;

// Listen for client_type from server to know if we're on the kitchen touchscreen
socket.on('client_type', (data) => {
    if (data.is_screen && data.screen_name === 'kitchen') {
        isKitchenScreen = true;

        // Auto-enter fullscreen as soon as we confirm it's the kitchen screen
        // Use a small delay to ensure DOM is fully ready
        setTimeout(() => {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(err => {
                    console.warn("Auto fullscreen failed (possibly blocked):", err);
                    // Optional: show a subtle toast if you want
                    // showToast('Tap fullscreen button for best experience', 'message', false, [], 5000);
                });
            }
        }, 500);
    }
});

// Manual fullscreen toggle button (works on all devices)
if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', function () {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(err => {
                console.error("Fullscreen request failed:", err);
                showToast('Fullscreen not available or blocked', 'warning');
            });
        } else {
            document.exitFullscreen();
        }
    });

    // Update button icon/text based on fullscreen state
    function updateFullscreenButton() {
        if (document.fullscreenElement) {
            fullscreenBtn.classList.add('active');
            fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i> Exit Fullscreen';
        } else {
            fullscreenBtn.classList.remove('active');
            fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i> Enter Fullscreen';
        }
    }

    // Initial check
    updateFullscreenButton();

    // Listen for changes (e.g., user presses ESC)
    document.addEventListener('fullscreenchange', updateFullscreenButton);
}

// Refresh UI button
const refreshBtn = document.getElementById('refresh-ui-btn');
if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
        showToast('Refreshing interface...', 'message');
        setTimeout(() => {
            location.reload();
        }, 800); // Small delay to show toast
    });
}

// Weather elements
const weatherIcon = document.getElementById('weather-icon');
const currentTemp = document.getElementById('current-temp');
const condition = document.getElementById('condition');
const minMax = document.getElementById('min-max');
const humidity = document.getElementById('humidity');

const weatherIconMobile = document.getElementById('weather-icon-mobile');
const currentTempMobile = document.getElementById('current-temp-mobile');
const conditionMobile = document.getElementById('condition-mobile');
const minMaxMobile = document.getElementById('min-max-mobile');
const humidityMobile = document.getElementById('humidity-mobile');

socket.on('update_states', (states) => {
    console.log('Received update_states', states);
    lightControls.forEach(control => {
        if (control.classList.contains('sync-lock')) return; // Skip if syncing
        const lightId = control.dataset.lightId;
        const targetState = states[lightId];
        if (!targetState) return;

        const slider = control.querySelector('input[type="range"]');
        const percentage = control.querySelector('.percentage');
        const toggle = control.querySelector('.on-off-toggle input[type="checkbox"]');
        const isColorToggle = control.classList.contains('color-toggle');
        const colorLabel = isColorToggle ? control.querySelector('.color-label') : null;

        slider.value = targetState.brightness;
        slider.style.setProperty('--value', targetState.brightness + '%');
        percentage.textContent = `${targetState.brightness}%`;

        if (isColorToggle && targetState.active) {
            toggle.checked = targetState.active === 'red';
            if (toggle.checked) {
                control.classList.add('red-mode');
                if (colorLabel) colorLabel.textContent = 'Red';
            } else {
                control.classList.remove('red-mode');
                if (colorLabel) colorLabel.textContent = 'White';
            }
        } else {
            toggle.checked = targetState.brightness > 0;
        }

        if (isColorToggle) {
            const br = targetState.brightness;
            control.classList.toggle('lit', br > 0);
        }

        if (targetState.locked) {
            control.classList.add('locked');
        } else {
            control.classList.remove('locked');
        }

        if (targetState.reed_locked) {
            control.classList.add('disabled');
        } else {
            control.classList.remove('disabled');
        }
    });
});

socket.on('brightness_ramp_start', (data) => {
    console.log('Received brightness_ramp_start', data);
    const { light_id, target_brightness, ramp_duration } = data;
    const control = lightControls.find(c => parseInt(c.dataset.lightId) === light_id);
    if (!control) return;

    const slider = control.querySelector('input[type="range"]');
    const percentage = control.querySelector('.percentage');
    const toggle = control.querySelector('.on-off-toggle input[type="checkbox"]');
    const isColorToggle = control.classList.contains('color-toggle');

    if (!isColorToggle) {
        toggle.checked = target_brightness > 0;
    }

    const start_brightness = parseFloat(slider.value);
    const startTime = performance.now();
    control.classList.add('ramping');

    function animate(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / ramp_duration, 1);
        const newValue = Math.round(start_brightness + (target_brightness - start_brightness) * progress);
        slider.value = newValue;
        slider.style.setProperty('--value', newValue + '%');
        percentage.textContent = `${newValue}%`;
        if (isColorToggle) {
            control.classList.toggle('lit', newValue > 0);
        }
        if (progress < 1) {
            requestAnimationFrame(animate);
        } else {
            control.classList.remove('ramping');
        }
    }

    requestAnimationFrame(animate);
});

socket.on('scene_ramp_start', (data) => {
    console.log('Received scene_ramp_start', data);
    lightControls.forEach(control => {
        const lightId = control.dataset.lightId;
        const targetState = data.states[lightId];
        if (!targetState) return;

        const slider = control.querySelector('input[type="range"]');
        const percentage = control.querySelector('.percentage');
        const toggle = control.querySelector('.on-off-toggle input[type="checkbox"]');
        const isColorToggle = control.classList.contains('color-toggle');
        const colorLabel = isColorToggle ? control.querySelector('.color-label') : null;

        const target_brightness = targetState.brightness;
        const target_active = targetState.active;

        let colorChanged = false;
        let newToggleChecked = null;
        if (isColorToggle && target_active && target_active !== (toggle.checked ? 'red' : 'white')) {
            colorChanged = true;
            newToggleChecked = target_active === 'red';
        }

        const start_brightness = parseFloat(slider.value);
        const startTime = performance.now();
        control.classList.add('ramping');

        function animate(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / data.ramp_duration, 1);
            const newValue = Math.round(start_brightness + (target_brightness - start_brightness) * progress);
            slider.value = newValue;
            slider.style.setProperty('--value', newValue + '%');
            percentage.textContent = `${newValue}%`;
            if (!isColorToggle) {
                toggle.checked = newValue > 0;
            } else {
                control.classList.toggle('lit', newValue > 0);
            }
            if (progress < 1) {
                requestAnimationFrame(animate);
            } else {
                control.classList.remove('ramping');
                if (colorChanged) {
                    toggle.checked = newToggleChecked;
                    if (newToggleChecked) {
                        control.classList.add('red-mode');
                        if (colorLabel) colorLabel.textContent = 'Red';
                    } else {
                        control.classList.remove('red-mode');
                        if (colorLabel) colorLabel.textContent = 'White';
                    }
                }
            }
        }

        requestAnimationFrame(animate);
    });
});

socket.on('set_active_scene', (data) => {
    console.log('Received set_active_scene', data);
    const sceneBtns = document.querySelectorAll('.scene-btn');
    sceneBtns.forEach(b => b.classList.remove('active'));
    if (data.scene_id) {
        const btn = document.querySelector(`.scene-btn[data-scene-id="${data.scene_id}"]`);
        if (btn) {
            btn.classList.add('active');
        }
    }
});

socket.on('update_gps', (data) => {
    console.log('Received update_gps', data);
    document.getElementById('date-value').textContent = data.date || '---';
    document.getElementById('time-value').textContent = data.time || '---';
    document.getElementById('sunrise-value').textContent = data.sunrise || '---';
    document.getElementById('sunset-value').textContent = data.sunset || '---';
    document.getElementById('satellites-value').textContent = data.satellites || '---';
    document.getElementById('location-value').textContent = data.location || '---';

    if (data.weather) {
        const temp = `${data.weather.temp_C}°C`;
        const minmax = `${data.weather.min_temp_C}°C / ${data.weather.max_temp_C}°C`;
        const hum = `${data.weather.humidity}%`;
        const desc = data.weather.condition.toLowerCase();

        let iconClass = 'fa-cloud';
        if (desc.includes('sunny') || desc.includes('clear')) iconClass = 'fa-sun';
        if (desc.includes('cloud') || desc.includes('overcast')) iconClass = 'fa-cloud';
        if (desc.includes('rain') || desc.includes('shower')) iconClass = 'fa-cloud-rain';
        if (desc.includes('snow')) iconClass = 'fa-snowflake';
        if (desc.includes('fog')) iconClass = 'fa-smog';
        if (desc.includes('thunder')) iconClass = 'fa-cloud-bolt';

        // Update desktop weather card
        if (weatherIcon) weatherIcon.className = 'fas ' + iconClass;
        if (currentTemp) currentTemp.innerText = temp;
        if (condition) condition.textContent = data.weather.condition;
        if (minMax) minMax.innerText = minmax;
        if (humidity) humidity.innerText = hum;

        // Update mobile weather card (duplicate)
        if (weatherIconMobile) weatherIconMobile.className = 'fas ' + iconClass;
        if (currentTempMobile) currentTempMobile.innerText = temp;
        if (conditionMobile) conditionMobile.textContent = data.weather.condition;
        if (minMaxMobile) minMaxMobile.innerText = minmax;
        if (humidityMobile) humidityMobile.innerText = hum;
    } else {
        // Fallback when no weather data
        const fallbackTemp = '--°C';
        const fallbackMinMax = '-- / --';
        const fallbackHum = '-- %';

        // Desktop fallback
        if (currentTemp) currentTemp.innerText = fallbackTemp;
        if (condition) condition.textContent = '---';
        if (minMax) minMax.innerText = fallbackMinMax;
        if (humidity) humidity.innerText = fallbackHum;
        if (weatherIcon) weatherIcon.className = 'fas fa-cloud';

        // Mobile fallback
        if (currentTempMobile) currentTempMobile.innerText = fallbackTemp;
        if (conditionMobile) conditionMobile.textContent = '---';
        if (minMaxMobile) minMaxMobile.innerText = fallbackMinMax;
        if (humidityMobile) humidityMobile.innerText = fallbackHum;
        if (weatherIconMobile) weatherIconMobile.className = 'fas fa-cloud';
    }

    updateResultantTimes();
});

// Handle relay updates
socket.on('update_relays', (states) => {
    console.log('Received update_relays', states);
    relayControls.forEach((control, index) => {
        const toggle = control.querySelector('input[type="checkbox"]');
        const name = relayNames[index];
        toggle.checked = states[name];
    });
});

// Handle power updates
socket.on('update_power', (data) => {
    console.log('Received update_power', data);
    document.getElementById('battery-value').textContent = data.battery != null ? `${data.battery.toFixed(1)}V / ${data.battery_pct}%` : '---';
    document.getElementById('water-value').textContent = data.water != null ? `${data.water}%` : '---';
    document.getElementById('solar-value').textContent = data.solar != null ? `${data.solar.toFixed(1)}A` : '---';
    document.getElementById('phase-value').textContent = data.phase ? data.phase.charAt(0).toUpperCase() + data.phase.slice(1) : '---';
});

// Handle backend-triggered toasts
socket.on('show_toast', (data) => {
    console.log('Received show_toast', data);
    showToast(data.message, data.type || 'message', false, [], data.duration);
});

socket.on('update_settings', (settings) => {
    console.log('Received update_settings', settings);
    // Dark mode
    if ('dark_mode' in settings) {
        themeToggle.checked = settings.dark_mode;
        document.body.dataset.theme = settings.dark_mode ? 'dark' : 'light';
    }

    // Auto theme
    if ('auto_theme' in settings) {
        document.getElementById('auto-theme-toggle').checked = settings.auto_theme;
    }

    // Evening offset
    if ('evening_offset' in settings) {
        document.querySelector('.evening-offset').value = settings.evening_offset;
    }

    // Morning offset
    if ('sunrise_offset' in settings) {
        document.querySelector('.sunrise-offset').value = settings.sunrise_offset;
    }

    // Night time
    if ('night_time' in settings) {
        document.querySelector('.night-time').value = settings.night_time;
    }

    // Toast duration
    if ('system_toast_display_time_ms' in settings) {
        toastDuration = settings.system_toast_display_time_ms;
    }

    updateResultantTimes();
});

socket.on('update_phase', (data) => {
    console.log('Received update_phase', data);
    document.getElementById('phase-value').textContent = data.phase ? data.phase.charAt(0).toUpperCase() + data.phase.slice(1) : '---';
});

socket.on('update_sensors', (data) => {
    console.log('Received update_sensors', data);
    // Handle if needed
});

socket.on('update_reed_state', (data) => {
    console.log('Received update_reed_state', data);
    // Handle if needed in main page, but it's for /reeds
});

let isFirstConnect = true;

// Handle client-side connection toasts
socket.on('connect', () => {
    console.log('Socket connected');
    console.log('Emitting request_sync');
    socket.emit('request_sync');
    if (!isFirstConnect) {
        showToast('System Online', 'message');
        if (offlineToast) {
            removeToast(offlineToast);
            offlineToast = null;
        }
        enableInterface();
    } else {
        isFirstConnect = false;
    }
});

socket.on('disconnect', () => {
    console.log('Socket disconnected');
    offlineToast = showToast('System Offline', 'warning', true, ['offline-toast']);
    disableInterface();
});

function disableInterface() {
    document.querySelector('.controls').classList.add('disabled');
    document.querySelector('.right-column').classList.add('disabled');

    // Reset all data to ---
    document.getElementById('date-value').textContent = '---';
    document.getElementById('time-value').textContent = '---';
    document.getElementById('sunrise-value').textContent = '---';
    document.getElementById('sunset-value').textContent = '---';
    document.getElementById('satellites-value').textContent = '---';
    document.getElementById('location-value').textContent = '---';
    document.getElementById('battery-value').textContent = '---';
    document.getElementById('water-value').textContent = '---';
    document.getElementById('solar-value').textContent = '---';
    document.getElementById('phase-value').textContent = '---';

    // Reset both weather cards
    if (currentTemp) currentTemp.innerText = '--°C';
    if (condition) condition.textContent = '---';
    if (minMax) minMax.innerText = '-- / --';
    if (humidity) humidity.innerText = '-- %';
    if (weatherIcon) weatherIcon.className = 'fas fa-cloud';

    if (currentTempMobile) currentTempMobile.innerText = '--°C';
    if (conditionMobile) conditionMobile.textContent = '---';
    if (minMaxMobile) minMaxMobile.innerText = '-- / --';
    if (humidityMobile) humidityMobile.innerText = '-- %';
    if (weatherIconMobile) weatherIconMobile.className = 'fas fa-cloud';
}

function enableInterface() {
    document.querySelector('.controls').classList.remove('disabled');
    document.querySelector('.right-column').classList.remove('disabled');
    // Data will be refreshed by server emits
}

// Fallback polling every 60 seconds
setInterval(() => {
    if (socket.connected) {
        console.log('Emitting periodic request_sync');
        socket.emit('request_sync');
    }
}, 60000);

// Function to parse time string to Date object
function parseTime(timeStr) {
    const [time, ampm] = timeStr.split(' ');
    let [hours, minutes] = time.split(':').map(Number);
    if (ampm === 'PM' && hours !== 12) hours += 12;
    if (ampm === 'AM' && hours === 12) hours = 0;
    const date = new Date();
    date.setHours(hours);
    date.setMinutes(minutes);
    date.setSeconds(0);
    return date;
}

// Function to add minutes to a Date object
function addMinutes(date, minutes) {
    const newDate = new Date(date);
    newDate.setMinutes(newDate.getMinutes() + minutes);
    return newDate;
}

// Function to format Date to time string
function formatTime(date) {
    let hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    const minStr = minutes < 10 ? '0' + minutes : minutes;
    return `${hours}:${minStr} ${ampm}`;
}

// Function to parse offset string to number
function parseOffset(offsetStr) {
    const numStr = offsetStr.replace(/ mins/, '');
    return parseInt(numStr, 10);
}

// Function to update resultant times
function updateResultantTimes() {
    const sunriseStr = document.getElementById('sunrise-value').textContent;
    const sunsetStr = document.getElementById('sunset-value').textContent;
    if (sunriseStr === '---' || sunsetStr === '---') {
        document.getElementById('evening-resultant').style.display = 'none';
        document.getElementById('morning-resultant').style.display = 'none';
        return;
    }

    const eveningOffsetStr = document.querySelector('.evening-offset').value;
    const morningOffsetStr = document.querySelector('.sunrise-offset').value;
    const eveningOffset = parseOffset(eveningOffsetStr);
    const morningOffset = parseOffset(morningOffsetStr);

    const sunriseTime = parseTime(sunriseStr);
    const sunsetTime = parseTime(sunsetStr);

    const eveningTime = addMinutes(sunsetTime, eveningOffset);
    const morningTime = addMinutes(sunriseTime, morningOffset);

    const eveningFormatted = formatTime(eveningTime);
    const morningFormatted = formatTime(morningTime);

    document.getElementById('evening-resultant').textContent = ` (${eveningFormatted})`;
    document.getElementById('morning-resultant').textContent = ` (${morningFormatted})`;
    document.getElementById('evening-resultant').style.display = 'inline';
    document.getElementById('morning-resultant').style.display = 'inline';
}

// Sonos Player Overlay
const musicBtn = document.getElementById('music-btn');
const sonosOverlay = document.getElementById('sonos-overlay');
const sonosIframe = document.getElementById('sonos-iframe');
const sonosBackBtn = document.getElementById('sonos-back-btn');

const SONOS_URL = 'https://play.sonos.com';

function openSonos() {
    sonosIframe.src = SONOS_URL;
    sonosOverlay.style.display = 'block';
    // Optional: hide main app content for cleaner look
    document.getElementById('app').style.opacity = '0';
}

function closeSonos() {
    sonosOverlay.style.display = 'none';
    sonosIframe.src = ''; // Stop loading/music
    document.getElementById('app').style.opacity = '1';
}

// Event Listeners
if (musicBtn) {
    musicBtn.addEventListener('click', openSonos);
}

if (sonosBackBtn) {
    sonosBackBtn.addEventListener('click', closeSonos);
}

// Optional: Allow ESC key to close Sonos (but not exit fullscreen)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sonosOverlay.style.display === 'block') {
        closeSonos();
    }
});
