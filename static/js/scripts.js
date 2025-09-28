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
    socket.emit('set_brightness', { light_id: lightId, value: value });
}

function sendToggle(lightId) {
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
            const sceneBtns = document.querySelectorAll('.scene-btn');
            sceneBtns.forEach(b => b.classList.remove('active'));
            sendBrightness(lightId, parseInt(e.target.value));
        });

        // Ignore server updates during drag
        slider.addEventListener('pointerdown', () => {
            control.classList.add('sync-lock');
        });
    }

    if (toggle) {
        toggle.addEventListener('change', () => {
            if (!(isColorToggle && slider.value === '0')) {
                const sceneBtns = document.querySelectorAll('.scene-btn');
                sceneBtns.forEach(b => b.classList.remove('active'));
            }
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
        socket.emit('set_relay', { name: name, state: toggle.checked });
    });
});

// Handle scene buttons interlock and toast
const sceneBtns = document.querySelectorAll('.scene-btn');
sceneBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        sceneBtns.forEach(b => b.classList.remove('active'));

        const sceneId = btn.dataset.sceneId;
        if (sceneId) {
            lightControls.forEach(lockControl);
            socket.emit('apply_scene', { scene_id: sceneId });
        }
    });
});

// Handle brightness buttons
const brightnessBtns = document.querySelectorAll('.brightness-btn');
brightnessBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        brightnessBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const level = btn.id.replace('brightness-', '');
        socket.emit('set_brightness_level', { level: level });
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

// Additional settings change listeners
document.getElementById('auto-theme-toggle').addEventListener('change', (e) => {
    socket.emit('set_setting', { key: 'auto_theme', value: e.target.checked });
});

document.getElementById('auto-brightness-toggle').addEventListener('change', (e) => {
    socket.emit('set_setting', { key: 'auto_brightness', value: e.target.checked });
});

document.querySelector('.evening-offset').addEventListener('change', (e) => {
    socket.emit('set_setting', { key: 'evening_offset', value: e.target.value });
});

document.querySelector('.sunrise-offset').addEventListener('change', (e) => {
    socket.emit('set_setting', { key: 'sunrise_offset', value: e.target.value });
});

document.querySelector('.night-time').addEventListener('change', (e) => {
    socket.emit('set_setting', { key: 'night_time', value: e.target.value });
});

// Weather elements
const weatherIcon = document.getElementById('weather-icon');
const currentTemp = document.getElementById('current-temp');
const condition = document.getElementById('condition');
const minMax = document.getElementById('min-max');
const humidity = document.getElementById('humidity');

// Sync states from backend via WebSocket
socket.on('update_states', (states) => {
    lightControls.forEach(control => {
        if (control.classList.contains('locked') || control.classList.contains('sync-lock')) return; // Skip if locked or syncing
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
    });
});

socket.on('ramp_start', (data) => {
    const { light_id, ramp_duration } = data;
    const control = lightControls.find(c => parseInt(c.dataset.lightId) === light_id);
    if (control) {
        setTimeout(() => {
            unlockControl(control);
        }, ramp_duration + 100);
    }
});

socket.on('brightness_ramp_start', (data) => {
    const { light_id, target_brightness, ramp_duration } = data;
    const control = lightControls.find(c => parseInt(c.dataset.lightId) === light_id);
    if (!control) return;
    lockControl(control);

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
            unlockControl(control);
            control.classList.remove('ramping');
        }
    }

    requestAnimationFrame(animate);
});

socket.on('scene_ramp_start', (data) => {
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
        const targetActive = targetState.active;

        let colorChanged = false;
        let newToggleChecked = null;
        if (isColorToggle && targetActive && targetActive !== (toggle.checked ? 'red' : 'white')) {
            colorChanged = true;
            newToggleChecked = targetActive === 'red';
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
    setTimeout(() => {
        lightControls.forEach(unlockControl);
    }, data.ramp_duration + 100);
});

socket.on('set_active_scene', (data) => {
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
    document.getElementById('date-value').textContent = data.date || '---';
    document.getElementById('time-value').textContent = data.time || '---';
    document.getElementById('sunrise-value').textContent = data.sunrise || '---';
    document.getElementById('sunset-value').textContent = data.sunset || '---';
    document.getElementById('satellites-value').textContent = data.satellites || '---';
    document.getElementById('location-value').textContent = data.location || '---';
    if (data.weather) {
        currentTemp.innerText = `${data.weather.temp_C}°C`;
        condition.textContent = data.weather.condition;
        minMax.innerText = `${data.weather.min_temp_C}°C / ${data.weather.max_temp_C}°C`;
        humidity.innerText = `${data.weather.humidity}%`;

        const desc = data.weather.condition.toLowerCase();
        let iconClass = 'fa-cloud';
        if (desc.includes('sunny') || desc.includes('clear')) iconClass = 'fa-sun';
        if (desc.includes('cloud') || desc.includes('overcast')) iconClass = 'fa-cloud';
        if (desc.includes('rain') || desc.includes('shower')) iconClass = 'fa-cloud-rain';
        if (desc.includes('snow')) iconClass = 'fa-snowflake';
        if (desc.includes('fog')) iconClass = 'fa-smog';
        if (desc.includes('thunder')) iconClass = 'fa-cloud-bolt';
        weatherIcon.className = 'fas ' + iconClass;
    } else {
        currentTemp.innerText = '--°C';
        condition.textContent = '---';
        minMax.innerText = '-- / --';
        humidity.innerText = '-- %';
        weatherIcon.className = 'fas fa-cloud';
    }
});

// Handle relay updates
socket.on('update_relays', (states) => {
    relayControls.forEach((control, index) => {
        const toggle = control.querySelector('input[type="checkbox"]');
        const name = relayNames[index];
        toggle.checked = states[name];
    });
});

// Handle power updates
socket.on('update_power', (data) => {
    document.getElementById('battery-value').textContent = data.battery != null ? `${data.battery.toFixed(1)}V / ${data.battery_pct}%` : '---';
    document.getElementById('water-value').textContent = data.water != null ? `${data.water}%` : '---';
    document.getElementById('solar-value').textContent = data.solar != null ? `${data.solar.toFixed(1)}A` : '---';
    document.getElementById('phase-value').textContent = data.phase ? data.phase.charAt(0).toUpperCase() + data.phase.slice(1) : '---';
});

// Handle backend-triggered toasts
socket.on('show_toast', (data) => {
    showToast(data.message, data.type || 'message');
});

socket.on('update_settings', (settings) => {
    // Dark mode
    if ('dark_mode' in settings) {
        themeToggle.checked = settings.dark_mode;
        document.body.dataset.theme = settings.dark_mode ? 'dark' : 'light';
    }

    // Brightness
    if ('brightness' in settings) {
        const brightness = settings.brightness;
        brightnessBtns.forEach(b => b.classList.toggle('active', b.id === `brightness-${brightness}`));
    }

    // Auto theme
    if ('auto_theme' in settings) {
        document.getElementById('auto-theme-toggle').checked = settings.auto_theme;
    }

    // Auto brightness
    if ('auto_brightness' in settings) {
        document.getElementById('auto-brightness-toggle').checked = settings.auto_brightness;
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
});

socket.on('set_brightness_controls_enabled', (data) => {
    const btns = document.querySelectorAll('.brightness-btn');
    btns.forEach(btn => {
        btn.disabled = !data.enabled;
        if (!data.enabled) {
            btn.classList.add('disabled');
        } else {
            btn.classList.remove('disabled');
        }
    });
});

let isFirstConnect = true;

// Handle client-side connection toasts
socket.on('connect', () => {
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
    offlineToast = showToast('System Offline', 'warning', true, ['offline-toast']);
    disableInterface();
});

function disableInterface() {
    document.querySelector('.controls').classList.add('disabled');
    document.querySelector('.right-column').classList.add('disabled');
    // Set all data to ---
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
    currentTemp.innerText = '--°C';
    condition.textContent = '---';
    minMax.innerText = '-- / --';
    humidity.innerText = '-- %';
    weatherIcon.className = 'fas fa-cloud';
    // Optionally reset lights to 0, but since disconnected, maybe not
}

function enableInterface() {
    document.querySelector('.controls').classList.remove('disabled');
    document.querySelector('.right-column').classList.remove('disabled');
    // Data will be refreshed by server emits
}