function springEase(t) {
    // Spring-like easing: combines exponential decay and oscillation
    return 1 - Math.cos(t * 4 * Math.PI) * Math.exp(-6 * t);
}

// Function to determine if the current page is the 5-inch version
function isFiveInchVersion() {
    return Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
        .some(link => link.href.includes('styles_5inch.css'));
}

// Get the display key based on the touchscreen type
function getDisplayKey() {
    return isFiveInchVersion() ? 'tent' : 'kitchen';
}

// Global state to track day/night for sunrise/sunset crossings
let isNightLast = null; // null = uninitialized, true = night, false = day
let lastArduinoStates = {};
let lastArduinoStatesTime = 0;
const ARDUINO_STATES_CACHE_DURATION = 1000; // Cache for 1 second
let config = {};
let originalConfig = {};
let sceneConfigs = {};
let currentActiveScene = null;
let arduinoStateInterval;
let lastSetBrightness = {};
let lastActiveScenePollTime = 0;
const ACTIVE_SCENE_POLL_INTERVAL = 2000; // Sync with arduino poll

$(document).ready(function() {
    console.log('Diagnostic: Page loaded, starting initialization');
    try {
        loadConfig();
        loadScenes();
        fetchData();
        fetchArduinoStates();
        fetchRelayStates();
        setInterval(fetchData, 10000); // Increased from 5000ms
        startArduinoStateInterval();

        // Initialize theme and brightness on page load if auto settings are enabled
        if ($('#auto-theme-toggle').prop('checked') || $('#auto-brightness-toggle').prop('checked')) {
            console.log('Diagnostic: Auto-theme or auto-brightness enabled on page load, checking settings');
            if ($('#sunrise').text() !== '---' && $('#sunset').text() !== '---') {
                if ($('#auto-theme-toggle').prop('checked')) {
                    updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                }
                if ($('#auto-brightness-toggle').prop('checked')) {
                    updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                }
            } else {
                console.log('Diagnostic: Sunrise/sunset not available on page load, fetching data');
                fetchData();
                setTimeout(() => {
                    if ($('#auto-theme-toggle').prop('checked')) {
                        updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                    }
                    if ($('#auto-brightness-toggle').prop('checked')) {
                        updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                    }
                }, 1000);
            }
        }

        // Lighting slider pagination
        const lightingSlider = document.querySelector('.lighting-slider');
        const dots = document.querySelectorAll('.pagination-dots .dot');

        if (lightingSlider) {
            // Check if this is the 5-inch version by looking for styles_5inch.css
            const isFiveInchVersion = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
                .some(link => link.href.includes('styles_5inch.css'));
            
            // Set default page (0 for main version, 2 for 5-inch version)
            const defaultPage = isFiveInchVersion ? 1 : 0;
            const pageWidth = lightingSlider.clientWidth || 1;
            lightingSlider.scrollLeft = defaultPage * pageWidth;
            console.log(`Diagnostic: Initialized lightingSlider to page ${defaultPage}, scrollLeft=${lightingSlider.scrollLeft}, isFiveInchVersion=${isFiveInchVersion}`);
        } else {
            console.error('Diagnostic: lightingSlider not found');
            return;
        }

        function updateActiveDot() {
            if (!lightingSlider || !dots.length) {
                console.error('Diagnostic: lightingSlider or dots missing');
                return;
            }
            const scrollPos = lightingSlider.scrollLeft;
            const pageWidth = lightingSlider.clientWidth || 1;
            const currentPage = Math.round(scrollPos / pageWidth);
            console.log(`Diagnostic: updateActiveDot - scrollPos=${scrollPos}, pageWidth=${pageWidth}, currentPage=${currentPage}`);
            dots.forEach((dot, index) => {
                dot.classList.toggle('active', index === currentPage);
            });
        }

        setTimeout(() => updateActiveDot(), 100);

        dots.forEach(dot => {
            dot.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const page = parseInt(dot.dataset.page);
                if (isNaN(page)) {
                    console.error(`Diagnostic: Invalid data-page for dot: ${dot.dataset.page}`);
                    return;
                }
                console.log(`Diagnostic: Dot clicked, navigating to page ${page}`);
                const pageWidth = lightingSlider.clientWidth;
                lightingSlider.scrollTo({
                    left: page * pageWidth,
                    behavior: 'smooth'
                });
                setTimeout(updateActiveDot, 300);
            });
        });

        // Swipe and drag handling
        let isDragging = false;
        let startX = 0;
        let scrollLeft = 0;
        let velocity = 0;
        let lastX = 0;
        let lastTime = 0;
        let animationFrame = null;
        let overscrollDistance = 0;

        function snapToPage(targetPage, instant = false) {
            const pageWidth = lightingSlider.clientWidth || 1;
            const maxPage = dots.length - 1;
            targetPage = Math.max(0, Math.min(targetPage, maxPage));
            const targetScroll = targetPage * pageWidth;

            console.log(`Diagnostic: snapToPage called, targetPage=${targetPage}, targetScroll=${targetScroll}, overscroll=${lightingSlider.classList.contains('overscroll-start') || lightingSlider.classList.contains('overscroll-end')}`);

            if (lightingSlider.classList.contains('overscroll-start') || lightingSlider.classList.contains('overscroll-end')) {
                const startScroll = lightingSlider.scrollLeft;
                const startTransform = overscrollDistance;
                const duration = 600;
                let startTime = null;

                function animate(currentTime) {
                    if (!startTime) startTime = currentTime;
                    const elapsed = currentTime - startTime;
                    const progress = Math.min(elapsed / duration, 1);
                    const easedProgress = springEase(progress);

                    lightingSlider.scrollLeft = startScroll + (targetScroll - startScroll) * easedProgress;
                    const currentTransform = startTransform * (1 - easedProgress);
                    lightingSlider.style.setProperty('--overscroll-distance', `${currentTransform}px`);

                    console.log(`Diagnostic: Overscroll animation, progress=${progress.toFixed(2)}, scrollLeft=${lightingSlider.scrollLeft}, --overscroll-distance=${currentTransform}px`);

                    if (progress < 1) {
                        requestAnimationFrame(animate);
                    } else {
                        lightingSlider.scrollLeft = targetScroll;
                        lightingSlider.style.setProperty('--overscroll-distance', '0px');
                        lightingSlider.classList.remove('overscroll-start', 'overscroll-end');
                        overscrollDistance = 0;
                        updateActiveDot();
                        lightingSlider.classList.remove('dragging');
                        console.log(`Diagnostic: Overscroll animation complete, scrollLeft=${lightingSlider.scrollLeft}`);
                    }
                }

                lightingSlider.classList.add('dragging');
                requestAnimationFrame(animate);
            } else {
                console.log(`Diagnostic: Snapping to page ${targetPage}, pageWidth=${pageWidth}, targetScroll=${targetScroll}, instant=${instant}`);
                lightingSlider.scrollTo({
                    left: targetScroll,
                    behavior: instant ? 'auto' : 'smooth'
                });
                lightingSlider.classList.remove('overscroll-start', 'overscroll-end');
                lightingSlider.style.setProperty('--overscroll-distance', '0px');
                overscrollDistance = 0;
                setTimeout(updateActiveDot, instant ? 50 : 300);
            }
        }

        function calculateVelocity(currentX, currentTime) {
            const deltaX = currentX - lastX;
            const deltaTime = (currentTime - lastTime) / 1000;
            if (deltaTime > 0) {
                velocity = deltaX / deltaTime;
            }
            lastX = currentX;
            lastTime = currentTime;
        }

        function applyMomentum() {
            if (Math.abs(velocity) < 10) {
                velocity = 0;
                const pageWidth = lightingSlider.clientWidth || 1;
                snapToPage(Math.round(lightingSlider.scrollLeft / pageWidth));
                return;
            }
            lightingSlider.scrollLeft -= velocity * 0.016;
            velocity *= 0.95;
            animationFrame = requestAnimationFrame(applyMomentum);
        }

        function stopMomentum() {
            if (animationFrame) {
                cancelAnimationFrame(animationFrame);
                animationFrame = null;
            }
            velocity = 0;
        }

        function handleOverscroll(walk) {
            const pageWidth = lightingSlider.clientWidth || 1;
            const maxScroll = pageWidth * (dots.length - 1);
            const currentScroll = scrollLeft - walk;

            if (currentScroll < 0 && walk > 0) {
                overscrollDistance = Math.min(walk * 0.3, pageWidth / 3);
                lightingSlider.classList.add('overscroll-start');
                lightingSlider.classList.remove('overscroll-end');
                lightingSlider.style.setProperty('--overscroll-distance', `${overscrollDistance}px`);
                lightingSlider.scrollLeft = 0;
                console.log(`Diagnostic: Overscroll start, walk=${walk}, overscrollDistance=${overscrollDistance}`);
                return true;
            } else if (currentScroll > maxScroll && walk < 0) {
                overscrollDistance = Math.min(Math.abs(walk) * 0.3, pageWidth / 3);
                lightingSlider.classList.add('overscroll-end');
                lightingSlider.classList.remove('overscroll-start');
                lightingSlider.style.setProperty('--overscroll-distance', `${overscrollDistance}px`);
                lightingSlider.scrollLeft = maxScroll;
                console.log(`Diagnostic: Overscroll end, walk=${walk}, overscrollDistance=${overscrollDistance}`);
                return true;
            } else {
                lightingSlider.classList.remove('overscroll-start', 'overscroll-end');
                lightingSlider.style.setProperty('--overscroll-distance', '0px');
                overscrollDistance = 0;
                console.log(`Diagnostic: Normal scroll, scrollLeft=${lightingSlider.scrollLeft}`);
                return false;
            }
        }

        lightingSlider.addEventListener('touchstart', (e) => {
            if ($('#settingsModal').is(':visible')) return;
            if (e.touches.length > 1) return;
            isDragging = true;
            stopMomentum();
            startX = e.touches[0].pageX;
            scrollLeft = lightingSlider.scrollLeft;
            lastX = startX;
            lastTime = performance.now();
            lightingSlider.classList.add('dragging');
            console.log(`Diagnostic: Touch start at X=${startX}, scrollLeft=${scrollLeft}`);
        }, { passive: false });

        lightingSlider.addEventListener('touchmove', (e) => {
            if ($('#settingsModal').is(':visible') || !isDragging || e.touches.length > 1) return;
            e.preventDefault();
            const x = e.touches[0].pageX;
            const walk = x - startX;
            if (!handleOverscroll(walk)) {
                lightingSlider.scrollLeft = scrollLeft - walk;
            }
            const currentTime = performance.now();
            calculateVelocity(x, currentTime);
            const currentScroll = lightingSlider.scrollLeft;
            console.log(`Diagnostic: Touch move to X=${x}, walk=${walk}, scrollLeft=${currentScroll}, velocity=${velocity}`);
        }, { passive: false });

        lightingSlider.addEventListener('touchend', (e) => {
            if ($('#settingsModal').is(':visible') || !isDragging) return;
            isDragging = false;
            lightingSlider.classList.remove('dragging');
            const x = e.changedTouches[0].pageX;
            const distance = startX - x;
            const pageWidth = lightingSlider.clientWidth || 1;
            const currentPage = Math.round(lightingSlider.scrollLeft / pageWidth);
            let targetPage = currentPage;

            if (!lightingSlider.classList.contains('overscroll-start') && !lightingSlider.classList.contains('overscroll-end')) {
                if (Math.abs(distance) > pageWidth / 4 || Math.abs(velocity) > 500) {
                    targetPage += distance > 0 ? 1 : -1;
                }
            }

            stopMomentum();
            snapToPage(targetPage);
            console.log(`Diagnostic: Touch end, distance=${distance}, velocity=${velocity}, targetPage=${targetPage}`);
        });

        lightingSlider.addEventListener('mousedown', (e) => {
            if ($('#settingsModal').is(':visible')) return;
            e.preventDefault();
            isDragging = true;
            stopMomentum();
            startX = e.pageX;
            scrollLeft = lightingSlider.scrollLeft;
            lastX = startX;
            lastTime = performance.now();
            lightingSlider.style.cursor = 'grabbing';
            lightingSlider.classList.add('dragging');
            console.log(`Diagnostic: Mouse down at X=${startX}, scrollLeft=${scrollLeft}`);
        });

        lightingSlider.addEventListener('mousemove', (e) => {
            if ($('#settingsModal').is(':visible') || !isDragging) return;
            e.preventDefault();
            const x = e.pageX;
            const walk = x - startX;
            if (!handleOverscroll(walk)) {
                lightingSlider.scrollLeft = scrollLeft - walk;
            }
            const currentTime = performance.now();
            calculateVelocity(x, currentTime);
            console.log(`Diagnostic: Mouse move to X=${x}, walk=${walk}, scrollLeft=${lightingSlider.scrollLeft}, velocity=${velocity}`);
        });

        lightingSlider.addEventListener('mouseup', (e) => {
            if ($('#settingsModal').is(':visible') || !isDragging) return;
            isDragging = false;
            lightingSlider.style.cursor = 'grab';
            lightingSlider.classList.remove('dragging');
            const x = e.pageX;
            const distance = startX - x;
            const pageWidth = lightingSlider.clientWidth || 1;
            const currentPage = Math.round(lightingSlider.scrollLeft / pageWidth);
            let targetPage = currentPage;

            if (!lightingSlider.classList.contains('overscroll-start') && !lightingSlider.classList.contains('overscroll-end')) {
                if (Math.abs(distance) > pageWidth / 4 || Math.abs(velocity) > 500) {
                    targetPage += distance > 0 ? 1 : -1;
                }
            }

            stopMomentum();
            snapToPage(targetPage);
            console.log(`Diagnostic: Mouse up, distance=${distance}, velocity=${velocity}, targetPage=${targetPage}`);
        });

        lightingSlider.addEventListener('mouseleave', () => {
            if ($('#settingsModal').is(':visible') || !isDragging) return;
            isDragging = false;
            lightingSlider.style.cursor = 'grab';
            lightingSlider.classList.remove('dragging');
            const pageWidth = lightingSlider.clientWidth || 1;
            const currentPage = Math.round(lightingSlider.scrollLeft / pageWidth);
            stopMomentum();
            snapToPage(currentPage);
            console.log('Diagnostic: Mouse leave');
        });

        lightingSlider.addEventListener('scroll', () => {
            const pageWidth = lightingSlider.clientWidth || 1;
            const maxScroll = pageWidth * (dots.length - 1);
            if (lightingSlider.scrollLeft < 0) {
                lightingSlider.scrollLeft = 0;
            } else if (lightingSlider.scrollLeft > maxScroll) {
                lightingSlider.scrollLeft = maxScroll;
            }
            const debouncedUpdateActiveDot = debounce(updateActiveDot, 100);
            debouncedUpdateActiveDot();
        }, { passive: true });

        // Slider event listeners for lighting controls
        document.querySelectorAll('input[type="range"]:not(#screen-brightness)').forEach(slider => {
            const updateSliderUI = (value, channel) => {
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} for slider`);
                    return;
                }
                $(`#arduino-value-${channel}`).text(value + '%');
                slider.style.setProperty('--value', value + '%');
                slider.value = value;
                const toggleSlider = $(`.control-item:has(input[data-channel="${channel}"]) .toggle-slider`);
                if (value > 0) {
                    toggleSlider.addClass('on').removeClass('disabled');
                } else {
                    toggleSlider.removeClass('on').removeClass('disabled');
                }
                console.log(`Diagnostic: Updated UI for channel ${channel}: ${value}%`);
            };

            let isDraggingSlider = false;

            slider.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                isDraggingSlider = true;
                const channel = parseInt(slider.dataset.channel);
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} on mousedown`);
                    isDraggingSlider = false;
                    return;
                }
                console.log(`Diagnostic: Slider mousedown for channel ${channel}`);
                stopArduinoStateInterval();
            });

            document.addEventListener('mousemove', (e) => {
                if (!isDraggingSlider) return;
                e.preventDefault();
                const channel = parseInt(slider.dataset.channel);
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} on mousemove`);
                    return;
                }
                const rect = slider.getBoundingClientRect();
                const totalHeight = rect.height;
                const mouseY = e.clientY - rect.top;
                let value = Math.round(((totalHeight - mouseY) / totalHeight) * 100);
                value = Math.max(0, Math.min(100, value));
                console.log(`Diagnostic: Slider mousemove for channel ${channel}: ${value}%`);
                updateSliderUI(value, channel);
                slider.dispatchEvent(new Event('input'));
            });

            document.addEventListener('mouseup', () => {
                if (isDraggingSlider) {
                    const channel = parseInt(slider.dataset.channel);
                    if (channel < 1 || channel > 12) {
                        console.error(`Diagnostic: Invalid channel ${channel} on mouseup`);
                    } else {
                        console.log(`Diagnostic: Slider mouseup for channel ${channel}`);
                    }
                    isDraggingSlider = false;
                    debouncedFetchArduinoStates();
                    setBrightness('arduino', channel, slider.value);
                }
            });

            slider.addEventListener('input', (e) => {
                const value = parseInt(slider.value);
                const channel = parseInt(slider.dataset.channel);
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} on input`);
                    return;
                }
                console.log(`Diagnostic: Slider input for channel ${channel}: ${value}%`);
                updateSliderUI(value, channel);
            });

            slider.addEventListener('touchstart', (e) => {
                e.preventDefault();
                e.stopPropagation();
                isDraggingSlider = true;
                const channel = parseInt(slider.dataset.channel);
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} on touchstart`);
                    isDraggingSlider = false;
                    return;
                }
                console.log(`Diagnostic: Slider touchstart for channel ${channel}`);
                stopArduinoStateInterval();
                slider.classList.add('active');
            });

            slider.addEventListener('touchmove', (e) => {
                if (!isDraggingSlider) return;
                e.preventDefault();
                e.stopPropagation();
                const channel = parseInt(slider.dataset.channel);
                if (channel < 1 || channel > 12) {
                    console.error(`Diagnostic: Invalid channel ${channel} on touchmove`);
                    return;
                }
                const rect = slider.getBoundingClientRect();
                const totalHeight = rect.height;
                const touchY = e.touches[0].clientY - rect.top;
                let value = Math.round(((totalHeight - touchY) / totalHeight) * 100);
                value = Math.max(0, Math.min(100, value));
                console.log(`Diagnostic: Slider touchmove for channel ${channel}: ${value}%`);
                updateSliderUI(value, channel);
                slider.dispatchEvent(new Event('input'));
            });

            slider.addEventListener('touchend', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (isDraggingSlider) {
                    const channel = parseInt(slider.dataset.channel);
                    if (channel < 1 || channel > 12) {
                        console.error(`Diagnostic: Invalid channel ${channel} on touchend`);
                    } else {
                        console.log(`Diagnostic: Slider touchend for channel ${channel}`);
                    }
                    isDraggingSlider = false;
                    slider.classList.remove('active');
                    debouncedFetchArduinoStates();
                    setBrightness('arduino', channel, slider.value);
                }
            });
        });
		
		$('.shutdown-btn').on('click', initiateShutdown);
		console.log('Shutdown button clicked');
		
        // Settings event listeners
        $('#dark-mode-toggle').off('change').on('change', function(e) {
            e.stopPropagation();
            const $checkbox = $(this);
            const toggle = $checkbox.parent();
            toggle.toggleClass('on', $checkbox.prop('checked'));
            console.log('Diagnostic: Dark mode toggle changed:', $checkbox.prop('checked'));
            $('body').toggleClass('dark-mode', $checkbox.prop('checked'));
            debouncedSaveConfig();
        });

        $('#auto-theme-toggle').off('change').on('change', function(e) {
            e.stopPropagation();
            const $checkbox = $(this);
            const toggle = $checkbox.parent();
            toggle.toggleClass('on', $checkbox.prop('checked'));
            console.log('Diagnostic: Auto-theme toggle changed:', $checkbox.prop('checked'));
            if ($checkbox.prop('checked')) {
                $('#default-theme').prop('disabled', true).css('opacity', 0.5);
                if ($('#sunrise').text() !== '---' && $('#sunset').text() !== '---') {
                    updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                } else {
                    fetchData();
                    setTimeout(() => {
                        updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                    }, 1000);
                }
            } else {
                $('#default-theme').prop('disabled', false).css('opacity', 1);
                applyDefaultTheme($('#default-theme').val());
            }
            debouncedSaveConfig();
        });

        $('#auto-brightness-toggle').off('change').on('change', function(e) {
            e.stopPropagation();
            const $checkbox = $(this);
            const isChecked = $checkbox.prop('checked');
            const toggle = $checkbox.parent();
            toggle.toggleClass('on', isChecked);
            console.log('Diagnostic: Auto-brightness toggle changed:', isChecked);
            if (isChecked) {
                if ($('#sunrise').text() !== '---' && $('#sunset').text() !== '---') {
                    updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                } else {
                    fetchData();
                    setTimeout(() => {
                        updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                    }, 1000);
                }
            } else {
                const brightness = $('.brightness-btn.active').data('brightness') || 'medium';
                $('.brightness-btn').removeClass('active');
                $(`.brightness-btn[data-brightness="${brightness}"]`).addClass('active');
                setScreenBrightness(brightness);
            }
            saveConfig();
        });

        $('.brightness-btn').off('click').on('click', function() {
            console.log('Diagnostic: Brightness button clicked:', $(this).data('brightness'));
            $('.brightness-btn').removeClass('active');
            $(this).addClass('active');
            const brightness = $(this).data('brightness');
            setScreenBrightness(brightness);
            debouncedSaveConfig();
        });

		// Add handler for screen-brightness-btn in 5inch data-panel
		$('.screen-brightness-btn').off('click').on('click', function() {
			const brightness = $(this).data('brightness');
			console.log('Diagnostic: Screen brightness button clicked:', brightness);
			$('.screen-brightness-btn').removeClass('active');
			if (brightness !== 'off') {
				$(this).addClass('active');
			}
			setScreenBrightness(brightness);
		});

		// Add touch wake-up for off state
		document.addEventListener('touchstart', function(e) {
			if ($('.screen-brightness-btn.active').length === 0) { // off state
				console.log('Diagnostic: Touch detected in off state, waking to low');
				setScreenBrightness('low');
				$('.screen-brightness-btn[data-brightness="low"]').addClass('active');
			}
		}, { passive: true });

        $('#default-theme').off('change').on('change', function() {
            console.log('Diagnostic: Default theme changed:', $(this).val());
            if (!$('#auto-theme-toggle').prop('checked')) {
                applyDefaultTheme($(this).val());
            }
            debouncedSaveConfig();
        });

        $('#evening-offset').off('change').on('change', debouncedSaveConfig);
        $('#night-time').off('change').on('change', debouncedSaveConfig);

        $('.settings-toggle').off('click').on('click', function(e) {
            e.preventDefault();
            const $checkbox = $(this).find('input[type="checkbox"]');
            $checkbox.prop('checked', !$checkbox.prop('checked')).trigger('change');
            console.log('Diagnostic: Settings toggle clicked:', $checkbox.attr('id'), 'New state:', $checkbox.prop('checked'));
        });

        $('#settingsModal').on('click', function(event) {
            console.log('Diagnostic: Click on settings-modal, target:', event.target);
            if ($(event.target).is('#settingsModal')) {
                console.log('Diagnostic: Clicked on backdrop, closing modal');
                closeSettings(event);
            } else {
                console.log('Diagnostic: Clicked inside modal content, ignoring');
            }
        });

		$('.settings-content').on('click', function(event) {
			if (!$(event.target).closest('.shutdown-btn, .brightness-btn, .scene-edit-btn, .save-scene-btn, .cancel-scene-btn').length) {
				console.log('Diagnostic: Click inside settings-content, stopping propagation');
				event.stopPropagation();
			}
		});

        if ($('#screen-brightness').length || $('#screen-brightness-value').length) {
            console.warn('Diagnostic: Found obsolete screen brightness slider elements');
            $('#screen-brightness, #screen-brightness-value').remove();
        }

        $.get('/load_config', function(data) {
            console.log('Config loaded from /load_config:', data);
            config = JSON.parse(JSON.stringify(data));
            originalConfig = JSON.parse(JSON.stringify(data));
            initializeSceneEditor();
        }).fail(function(jqXHR, textStatus, errorThrown) {
            console.error('Error loading config from /load_config:', textStatus, errorThrown);
            alert('Failed to load configuration. Please refresh the page.');
        });
    } catch (e) {
        console.error('Diagnostic: Error in document.ready:', e);
    }
});

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

const debouncedFetchArduinoStates = debounce(fetchArduinoStates, 1500);

function setScreenBrightness(brightness) {
    console.log(`Diagnostic: Setting screen brightness to ${brightness} via SSH`);
    $.ajax({
        url: '/set_screen_brightness',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ 
            brightness: brightness,
            display: isFiveInchVersion() ? '5inch' : '10inch' 
        }),
        success: function(response) {
            console.log(`Diagnostic: Screen brightness set to ${brightness}:`, response);
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error(`Diagnostic: Error setting screen brightness to ${brightness}:`, textStatus, errorThrown);
            alert('Failed to set screen brightness. Please try again.');
        }
    });
}

const debouncedSaveConfig = debounce(saveConfig, 500);
const debouncedSetBrightness = debounce(setBrightness, 100);

function fetchData() {
    $.get('/get_data', function(data) {
        console.log('Diagnostic: Raw data fetched:', data);
        $('#sunrise').text(data.sunrise === "---" || !data.sunrise ? "---" : data.sunrise);
        $('#sunset').text(data.sunset === "---" || !data.sunset ? "---" : data.sunset);
        $('#current_datetime').text(data.current_datetime === "---" || !data.current_datetime ? "---" : data.current_datetime);
        $('#temperature').text(data.temperature !== 'Error' ? data.temperature + '°C' : 'Error')
                        .toggleClass('error', data.temperature === 'Error');
        $('#battery_level').text(data.battery_level !== 'Error' ? data.battery_level : 'Error')
                          .toggleClass('error', data.battery_level === 'Error');
        $('#tank_level').text(data.tank_level !== 'Error' ? data.tank_level + '% Full' : 'Error')
                       .toggleClass('error', data.tank_level === 'Error');
        $('#kitchen_panel').text(data.kitchen_panel || 'Unknown');
        $('#storage_panel').text(data.storage_panel || 'Unknown');
        $('#rear_drawer').text(data.rear_drawer || 'Unknown');
        const gpsFix = data.gps_fix || 'No';
        const gpsSatellites = data.gps_quality ? (data.gps_quality.match(/\d+/) ? data.gps_quality.match(/\d+/)[0] : '0') : '0';
        const gpsDisplay = gpsFix === 'Yes' ? `${gpsSatellites} Satellites` : 'No';
        $('#gps_fix').text(gpsDisplay);
        const gpsCoords = (data.latitude && data.longitude) ?
            `${parseFloat(data.latitude).toFixed(6)}, ${parseFloat(data.longitude).toFixed(6)}` : 'N/A';
        $('#gps-coordinates').text(gpsCoords);
        $('#solar_output').text(data.solar_output !== 'Error' ? data.solar_output : 'Error')
                          .toggleClass('error', data.solar_output === 'Error');
        $('#battery_label').html(`<i class="fas fa-bolt"></i> ${data.battery_label || 'Battery Output'}:`);
        $('#battery_output').text(data.battery_current !== 'Error' ? data.battery_current : 'Error')
                           .toggleClass('error', data.battery_current === 'Error');

        if ($('#auto-theme-toggle').prop('checked') || $('#auto-brightness-toggle').prop('checked')) {
            if ($('#sunrise').text() !== '---' && $('#sunset').text() !== '---') {
                const sunrise = $('#sunrise').text().replace('*', '').trim();
                const sunset = $('#sunset').text().replace('*', '').trim();
                let now = new Date();
                let currentTimeStr = $('#current_datetime').text().replace('*', '').trim();
                if (currentTimeStr && currentTimeStr !== '---') {
                    try {
                        now = new Date(currentTimeStr);
                        if (isNaN(now.getTime())) {
                            console.warn('Diagnostic: Invalid current time, using system time');
                            now = new Date();
                        }
                    } catch (e) {
                        console.warn('Diagnostic: Error parsing current time, using system time:', e);
                    }
                }

                let sunriseTime, sunsetTime;
                const today = now.toDateString();
                if (sunrise === '---' || sunset === '---' || !sunrise || !sunset) {
                    console.warn('Diagnostic: Invalid sunrise/sunset data, skipping crossing check');
                    return;
                }
                try {
                    sunriseTime = new Date(`${today} ${sunrise}`);
                    sunsetTime = new Date(`${today} ${sunset}`);
                    if (isNaN(sunriseTime.getTime()) || isNaN(sunsetTime.getTime())) {
                        console.warn('Diagnostic: Invalid sunrise/sunset format, skipping crossing check');
                        return;
                    }
                    if (sunsetTime < sunriseTime) {
                        sunsetTime.setDate(sunsetTime.getDate() + 1);
                    }
                } catch (e) {
                    console.error('Diagnostic: Error parsing sunrise/sunset:', e);
                    return;
                }

                const isNight = now < sunriseTime || now >= sunsetTime;
                console.log('Diagnostic: Checking day/night state:', { now, sunriseTime, sunsetTime, isNight, isNightLast });

                if (isNightLast === null) {
                    isNightLast = isNight;
                    if ($('#auto-theme-toggle').prop('checked')) {
                        updateThemeBasedOnTime(sunrise, sunset);
                    }
                    if ($('#auto-brightness-toggle').prop('checked')) {
                        updateBrightnessBasedOnTime(sunrise, sunset);
                    }
                } else if (isNight !== isNightLast) {
                    console.log('Diagnostic: Sunrise/sunset crossing detected, updating settings');
                    isNightLast = isNight;
                    if ($('#auto-theme-toggle').prop('checked')) {
                        updateThemeBasedOnTime(sunrise, sunset);
                    }
                    if ($('#auto-brightness-toggle').prop('checked')) {
                        updateBrightnessBasedOnTime(sunrise, sunset);
                    }
                }
            }
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error fetching /get_data:', textStatus, errorThrown);
        $('#sunrise').text('---');
        $('#sunset').text('---');
        $('#current_datetime').text('---');
        $('#temperature').text('Error').toggleClass('error', true);
        $('#battery_level').text('Error').toggleClass('error', true);
        $('#tank_level').text('Error').toggleClass('error', true);
        $('#kitchen_panel').text('Unknown');
        $('#storage_panel').text('Unknown');
        $('#rear_drawer').text('Unknown');
        $('#gps_fix').text('No');
        $('#gps-coordinates').text('N/A');
        $('#solar_output').text('Error').toggleClass('error', true);
        $('#battery_label').html(`<i class="fas fa-bolt"></i> Battery Output:`);
        $('#battery_output').text('Error').toggleClass('error', true);
    });
}

function fetchActiveScene() {
    $.get('/get_active_scene', function(data) {
        console.log('Diagnostic: Active scene from backend:', data.active_scene);
        if (data.active_scene !== currentActiveScene) {
            currentActiveScene = data.active_scene;
            $('.scene-btn').removeClass('active');
            if (currentActiveScene) {
                const sceneTitle = currentActiveScene.replace('_', ' ').toLowerCase();
                $('.scene-btn').each(function() {
                    const buttonText = $(this).text().trim().toLowerCase().replace(' ', '');
                    if (buttonText.includes(sceneTitle)) {
                        $(this).addClass('active');
                    }
                });
            }
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error fetching /get_active_scene:', textStatus, errorThrown);
    });
}

function fetchArduinoStates() {
    const now = Date.now();
    if (now - lastArduinoStatesTime < ARDUINO_STATES_CACHE_DURATION) {
        console.log('Diagnostic: Using cached Arduino states:', lastArduinoStates);
        updateArduinoSliders(lastArduinoStates);
        return;
    }

    $.get('/get_arduino_states', function(data) {
        try {
            if (data.error === "Arduino not detected") {
                console.log('Diagnostic: Arduino not detected, disabling controls');
                $('input[id^="arduino-"]').each(function() {
                    const channel = $(this).data('channel');
                    $(this).prop('disabled', true).closest('.control-item').addClass('disabled');
                    $(`#arduino-value-${channel}`).text('Error').addClass('error');
                    $(`.control-item:has(input[data-channel="${channel}"]) .toggle-slider`)
                        .addClass('disabled').off('click');
                });
                $('.scene-btn').addClass('disabled').off('click');
                return;
            }
            const states = typeof data === 'string' ? JSON.parse(data) : data;
            console.log('Diagnostic: Arduino states received:', states);
            lastArduinoStates = states;
            lastArduinoStatesTime = now;
            updateArduinoSliders(states);
        } catch (e) {
            console.error('Diagnostic: Error parsing /get_arduino_states:', e);
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error fetching /get_arduino_states:', textStatus, errorThrown);
        $('input[id^="arduino-"]').each(function() {
            const channel = $(this).data('channel');
            $(this).prop('disabled', true).closest('.control-item').addClass('disabled');
            $(`#arduino-value-${channel}`).text('Error').addClass('error');
            $(`.control-item:has(input[data-channel="${channel}"]) .toggle-slider`)
                .addClass('disabled').off('click');
        });
        $('.scene-btn').addClass('disabled').off('click');
    });
}

function updateArduinoSliders(states) {
    const displayKey = getDisplayKey();
    Object.keys(states).forEach(channel => {
        // Check if display is an object or boolean for backward compatibility
        const displayValue = config.channels.arduino[channel]?.display;
        const shouldDisplay = typeof displayValue === 'object' ? displayValue[displayKey] : displayValue;
        if (!shouldDisplay) {
            console.log(`Diagnostic: Skipping UI update for hidden channel ${channel} on ${displayKey} touchscreen`);
            return;
        }
        const channelNum = parseInt(channel);
        if (channelNum < 1 || channelNum > 12) {
            console.error(`Diagnostic: Invalid channel ${channel}`);
            return;
        }
        let brightness = parseInt(states[channel]) || 0;
        if (brightness > 0 && brightness <= 2) {
            console.log(`Diagnostic: Adjusting brightness for channel ${channel} from ${brightness} to 0`);
            brightness = 0;
        }
        const valueElement = $(`#arduino-value-${channel}`);
        const sliderElement = $(`#arduino-${channel}`);
        const toggleSlider = $(`.control-item:has(input[data-channel="${channel}"]) .toggle-slider`);
        if (!valueElement.length || !sliderElement.length || !toggleSlider.length) {
            console.warn(`Diagnostic: Missing elements for channel ${channel}`);
            return;
        }
        if (lastSetBrightness[channel] && (Date.now() - lastSetBrightness[channel].timestamp < 3000) && Math.abs(brightness - lastSetBrightness[channel].value) > 10) {
            console.log(`Diagnostic: Ignoring erratic update for channel ${channel} during ramp window`);
            return;
        }
        console.log(`Diagnostic: Updating channel ${channel}: brightness=${brightness}%`);
        valueElement.text(brightness + '%').removeClass('error');
        sliderElement.val(brightness).prop('disabled', false);
        sliderElement[0].style.setProperty('--value', brightness + '%');
        sliderElement.closest('.control-item').removeClass('disabled');
        if (brightness > 0) {
            toggleSlider.addClass('on').removeClass('disabled');
        } else {
            toggleSlider.removeClass('on').removeClass('disabled');
        }
    });
    $('.scene-btn').removeClass('disabled').each(function() {
        const scene = $(this).text().trim().toLowerCase().replace(' ', '_');
        $(this).off('click').on('click', () => activateScene(scene));
    });
    checkActiveScene();
}

function fetchRelayStates() {
    const displayKey = getDisplayKey();
    $.get('/get_relay_states', function(data) {
        console.log('Diagnostic: Relay states received:', data);
        Object.keys(data).forEach(channel => {
            // Check if display is an object or boolean for backward compatibility
            const displayValue = config.channels.relays[channel]?.display;
            const shouldDisplay = typeof displayValue === 'object' ? displayValue[displayKey] : displayValue;
            if (!shouldDisplay) {
                console.log(`Diagnostic: Skipping UI update for hidden relay channel ${channel} on ${displayKey} touchscreen`);
                return;
            }
            const state = data[channel] ? 'On' : 'Off';
            const toggleSlider = $(`#relay-value-${channel}`).closest('.control-item').find('.toggle-slider');
            $(`#relay-value-${channel}`).text(state);
            if (state === 'On') {
                toggleSlider.addClass('on');
            } else {
                toggleSlider.removeClass('on');
            }
        });
        checkActiveScene();
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error fetching /get_relay_states:', textStatus, errorThrown);
    });
}

function setBrightness(type, channel, value) {
    console.log(`Diagnostic: Setting ${type} channel ${channel} to ${value}%`);
    if (type === 'arduino' && (channel < 1 || channel > 12)) {
        console.error(`Diagnostic: Invalid Arduino channel ${channel}`);
        return;
    }
    $(`#arduino-value-${channel}`).text(value + '%');
    lastSetBrightness[channel] = {value: value, timestamp: Date.now()};
    stopArduinoStateInterval();
    $.ajax({
        url: '/set_brightness',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ type: type, channel: channel, brightness: value }),
        success: function(response) {
            console.log(`Diagnostic: Set brightness success for channel ${channel}:`, response);
            lastSetBrightness[channel] = {value: value, timestamp: Date.now()};
            debouncedFetchArduinoStates();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error(`Diagnostic: Error in set_brightness for channel ${channel}:`, textStatus, errorThrown);
            fetchArduinoStates();
        }
    });
}

function toggleLight(type, channel, slider) {
    const isOn = $(slider).hasClass('on');
    const state = isOn ? 'off' : 'on';
    const value = state === 'on' ? 100 : 0;
    console.log(`Diagnostic: Toggling ${type} channel ${channel} to ${state}`);
    if (type === 'arduino' && (channel < 1 || channel > 12)) {
        console.error(`Diagnostic: Invalid Arduino channel ${channel}`);
        return;
    }
    $(`#arduino-value-${channel}`).text(value + '%');
    $(`#arduino-${channel}`).val(value);
    $(`#arduino-${channel}`).css('--value', value + '%');
    lastSetBrightness[channel] = value;
    if (state === 'on') {
        $(slider).addClass('on');
    } else {
        $(slider).removeClass('on');
    }
    $.ajax({
        url: '/toggle',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ type: type, channel: channel, state: state }),
        success: function(response) {
            console.log(`Diagnostic: Toggle success for channel ${channel}:`, response);
            debouncedFetchArduinoStates();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error(`Diagnostic: Error in toggle for channel ${channel}:`, textStatus, errorThrown);
            debouncedFetchArduinoStates();
        }
    });
}

function toggleRelay(type, channel, slider) {
    const isOn = $(slider).hasClass('on');
    const state = isOn ? 'off' : 'on';
    console.log(`Diagnostic: Toggling relay channel ${channel} to ${state}`);
    $(`#relay-value-${channel}`).text(state.charAt(0).toUpperCase() + state.slice(1));
    if (state === 'on') {
        $(slider).addClass('on');
    } else {
        $(slider).removeClass('on');
    }
    $.ajax({
        url: '/toggle',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ type: type, channel: channel, state: state }),
        success: function(response) {
            console.log(`Diagnostic: Toggle success for relay ${channel}:`, response);
            fetchRelayStates();
            checkActiveScene();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error(`Diagnostic: Error in toggleRelay for channel ${channel}:`, textStatus, errorThrown);
        }
    });
}

function activateScene(scene) {
    console.log(`Diagnostic: Activating scene ${scene}`);
    $('.scene-btn').removeClass('active');
    currentActiveScene = scene;
    $('.scene-btn').each(function() {
        const buttonText = $(this).text().trim().toLowerCase().replace(' ', '_');
        if (buttonText === scene) {
            $(this).addClass('active');
        }
    });
    rampFaders();
    $.ajax({
        url: '/activate_scene',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ scene: scene }),
        success: function(response) {
            console.log(`Diagnostic: Scene ${scene} activated:`, response);
            debouncedFetchArduinoStates();
            fetchRelayStates();
            fetchActiveScene();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error(`Diagnostic: Error in activate_scene for ${scene}:`, textStatus, errorThrown);
            debouncedFetchArduinoStates();
            fetchRelayStates();
            fetchActiveScene();
        }
    });
}

function initiateShutdown() {
    console.log('Diagnostic: Shutdown button clicked');
    // Create and append the modal
    const $modal = $('<div class="confirm-modal"><p>Are you sure you want to shut down the control system?</p><button class="confirm-btn">Yes</button><button class="cancel-btn">No</button></div>');
    $('body').append($modal);

    // Verify modal was created
    if (!$modal.length) {
        console.error('Diagnostic: Failed to create confirm modal');
        alert('Failed to display confirmation. Please try again.');
        return;
    }

    // Add event handlers
    $('.confirm-btn', $modal).on('click', function() {
        console.log('Diagnostic: Initiating shutdown for both systems');
        $.ajax({
            url: '/shutdown',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ token: 'okohWE_uJGFikr4bF_zVKLOazp27DCbI_rWjTtRALcY' }),
            success: function(response) {
                console.log('Diagnostic: Shutdown command sent:', response);
                alert('Both systems are shutting down. Please wait a moment before powering off.');
                $modal.remove(); // Remove only if $modal is valid
            },
            error: function(jqXHR, textStatus, errorThrown) {
                console.error('Diagnostic: Error initiating shutdown:', textStatus, errorThrown);
                alert('Failed to initiate shutdown. Please try again or check the server.');
                $modal.remove(); // Remove only if $modal is valid
            }
        });
    });

    $('.cancel-btn', $modal).on('click', function() {
        console.log('Diagnostic: Cancelled shutdown');
        $modal.remove(); // Remove only if $modal is valid
    });

    // Ensure modal is removed if AJAX fails silently
    $modal.on('click', '.confirm-btn, .cancel-btn', function() {
        if ($modal && $modal.length) $modal.remove();
    });
}

function startArduinoStateInterval() {
    if (!arduinoStateInterval) {
        arduinoStateInterval = setInterval(() => {
            console.log('Diagnostic: Background fetchArduinoStates and fetchActiveScene triggered');
            debouncedFetchArduinoStates();
            fetchActiveScene();
        }, ACTIVE_SCENE_POLL_INTERVAL);
        console.log('Diagnostic: Started Arduino state and active scene interval');
    }
}

function stopArduinoStateInterval() {
    if (arduinoStateInterval) {
        clearInterval(arduinoStateInterval);
        arduinoStateInterval = null;
        console.log('Diagnostic: Stopped Arduino state interval');
    }
}

function updateThemeBasedOnTime(sunrise, sunset) {
    if (!$('#auto-theme-toggle').prop('checked')) {
        console.log('Diagnostic: Auto-theme disabled, skipping time-based theme update');
        return;
    }

    console.log('Diagnostic: Updating theme based on time:', { sunrise, sunset });
    sunrise = sunrise.replace('*', '').trim();
    sunset = sunset.replace('*', '').trim();

    let now = new Date();
    let currentTimeStr = $('#current_datetime').text().replace('*', '').trim();
    if (currentTimeStr && currentTimeStr !== '---') {
        try {
            now = new Date(currentTimeStr);
            if (isNaN(now.getTime())) {
                console.warn('Diagnostic: Invalid current time, using system time');
                now = new Date();
            }
        } catch (e) {
            console.warn('Diagnostic: Error parsing current time, using system time:', e);
        }
    }

    let sunriseTime, sunsetTime;
    const today = now.toDateString();
    if (sunrise === '---' || sunset === '---' || !sunrise || !sunset) {
        console.warn('Diagnostic: Invalid sunrise/sunset data, using Melbourne defaults (6 AM / 6 PM)');
        sunriseTime = new Date(`${today} 06:00`);
        sunsetTime = new Date(`${today} 18:00`);
    } else {
        try {
            sunriseTime = new Date(`${today} ${sunrise}`);
            sunsetTime = new Date(`${today} ${sunset}`);
            if (isNaN(sunriseTime.getTime()) || isNaN(sunsetTime.getTime())) {
                console.warn('Diagnostic: Invalid sunrise/sunset format, using Melbourne defaults');
                sunriseTime = new Date(`${today} 06:00`);
                sunsetTime = new Date(`${today} 18:00`);
            } else if (sunsetTime < sunriseTime) {
                sunsetTime.setDate(sunsetTime.getDate() + 1);
            }
        } catch (e) {
            console.error('Diagnostic: Error parsing sunrise/sunset:', e);
            sunriseTime = new Date(`${today} 06:00`);
            sunsetTime = new Date(`${today} 18:00`);
        }
    }

    console.log('Diagnostic: Applying theme - Now:', now, 'Sunrise:', sunriseTime, 'Sunset:', sunsetTime);
    const isDark = now < sunriseTime || now >= sunsetTime;
    $('body').toggleClass('dark-mode', isDark);
    $('#dark-mode-toggle').prop('checked', isDark).parent().toggleClass('on', isDark);
    debouncedSaveConfig();
}

function updateBrightnessBasedOnTime(sunrise, sunset) {
    if (!$('#auto-brightness-toggle').prop('checked')) {
        console.log('Diagnostic: Auto-brightness disabled, skipping time-based brightness update');
        return;
    }

    console.log('Diagnostic: Updating brightness based on time:', { sunrise, sunset });
    sunrise = sunrise.replace('*', '').trim();
    sunset = sunset.replace('*', '').trim();

    let now = new Date();
    let currentTimeStr = $('#current_datetime').text().replace('*', '').trim();
    if (currentTimeStr && currentTimeStr !== '---') {
        try {
            now = new Date(currentTimeStr);
            if (isNaN(now.getTime())) {
                console.warn('Diagnostic: Invalid current time, using system time');
                now = new Date();
            }
        } catch (e) {
            console.warn('Diagnostic: Error parsing current time, using system time:', e);
        }
    }

    let sunriseTime, sunsetTime;
    const today = now.toDateString();
    if (sunrise === '---' || sunset === '---' || !sunrise || !sunset) {
        console.warn('Diagnostic: Invalid sunrise/sunset data, using Melbourne defaults (6 AM / 6 PM)');
        sunriseTime = new Date(`${today} 06:00`);
        sunsetTime = new Date(`${today} 18:00`);
    } else {
        try {
            sunriseTime = new Date(`${today} ${sunrise}`);
            sunsetTime = new Date(`${today} ${sunset}`);
            if (isNaN(sunriseTime.getTime()) || isNaN(sunsetTime.getTime())) {
                console.warn('Diagnostic: Invalid sunrise/sunset format, using Melbourne defaults');
                sunriseTime = new Date(`${today} 06:00`);
                sunsetTime = new Date(`${today} 18:00`);
            } else if (sunsetTime < sunriseTime) {
                sunsetTime.setDate(sunsetTime.getDate() + 1);
            }
        } catch (e) {
            console.error('Diagnostic: Error parsing sunrise/sunset:', e);
            sunriseTime = new Date(`${today} 06:00`);
            sunsetTime = new Date(`${today} 18:00`);
        }
    }

    console.log('Diagnostic: Applying brightness - Now:', now, 'Sunrise:', sunriseTime, 'Sunset:', sunsetTime);
    const isNight = now < sunriseTime || now >= sunsetTime;
    const brightness = isNight ? 'low' : 'medium';
    const currentBrightness = $('.brightness-btn.active').data('brightness');
    if (currentBrightness !== brightness) {
        $('.brightness-btn').removeClass('active');
        $(`.brightness-btn[data-brightness="${brightness}"]`).addClass('active');
        setScreenBrightness(brightness);
        debouncedSaveConfig();
    }
}

function applyDefaultTheme(theme) {
    console.log('Diagnostic: Applying default theme:', theme);
    const isDark = theme === 'dark';
    $('body').toggleClass('dark-mode', isDark);
    $('#dark-mode-toggle').prop('checked', isDark).parent().toggleClass('on', isDark);
}

function saveConfig() {
    const brightness = $('.brightness-btn.active').data('brightness') || 'medium';
    const config = {
        theme: {
            darkMode: $('#dark-mode-toggle').prop('checked') ? 'on' : 'off',
            autoTheme: $('#auto-theme-toggle').prop('checked') ? 'on' : 'off',
            autoBrightness: $('#auto-brightness-toggle').prop('checked') ? 'on' : 'off',
            defaultTheme: $('#default-theme').val(),
            screen_brightness: brightness
        },
        evening_offset: parseInt($('#evening-offset').val()),
        night_time: $('#night-time').val()
    };
    console.log('Diagnostic: Saving config:', config);
    $.ajax({
        url: '/save_config',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(config),
        success: function(response) {
            console.log('Diagnostic: Config saved successfully:', response);
        },
        error: function(jqXHR, textStatus, errorThrown) {
            console.error('Diagnostic: Error saving config:', textStatus, errorThrown);
        }
    });
}

function loadConfig() {
    console.log('Diagnostic: Loading config from /load_config');
    $.get('/load_config', function(data) {
        console.log('Diagnostic: Config loaded:', data);
        try {
            config = JSON.parse(JSON.stringify(data));
            originalConfig = JSON.parse(JSON.stringify(data));
            if (config && config.theme) {
                const darkMode = config.theme.darkMode === 'on';
                const autoTheme = config.theme.autoTheme === 'on';
                const autoBrightness = config.theme.autoBrightness === 'on';
                const defaultTheme = config.theme.defaultTheme || 'light';
                let brightness = config.theme.screen_brightness || 'medium';

                console.log(`Diagnostic: Parsed settings - darkMode: ${darkMode}, autoTheme: ${autoTheme}, autoBrightness: ${autoBrightness}, defaultTheme: ${defaultTheme}, brightness: ${brightness}`);

                brightness = ['low', 'medium', 'high'].includes(brightness) ? brightness : 'medium';

                $('#dark-mode-toggle').prop('checked', darkMode).parent().toggleClass('on', darkMode);
                $('#auto-theme-toggle').prop('checked', autoTheme).parent().toggleClass('on', autoTheme);
                $('#auto-brightness-toggle').prop('checked', autoBrightness).parent().toggleClass('on', autoBrightness);
                $('#default-theme').val(defaultTheme).prop('disabled', autoTheme).css('opacity', autoTheme ? 0.5 : 1);

                $('.brightness-btn').removeClass('active');
                $(`.brightness-btn[data-brightness="${brightness}"]`).addClass('active');

                // For 5inch screen-brightness-btn, activate corresponding button (map high to medium if needed)
                if ($('.screen-brightness-btn').length) {
                    let btnBrightness = brightness;
                    if (btnBrightness === 'high') btnBrightness = 'medium'; // No high on 5inch data-panel
                    $('.screen-brightness-btn').removeClass('active');
                    const btnLabel = btnBrightness.charAt(0).toUpperCase() + btnBrightness.slice(1);
                    $(`.screen-brightness-btn:contains('${btnLabel}')`).addClass('active');
                }

                if (autoTheme || autoBrightness) {
                    console.log('Diagnostic: Auto-theme or auto-brightness enabled, checking sunrise/sunset');
                    if ($('#sunrise').text() !== '---' && $('#sunset').text() !== '---') {
                        if (autoTheme) updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                        if (autoBrightness) updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                    } else {
                        console.log('Diagnostic: Sunrise/sunset not available, scheduling fetch');
                        fetchData();
                        setTimeout(() => {
                            if (autoTheme) updateThemeBasedOnTime($('#sunrise').text(), $('#sunset').text());
                            if (autoBrightness) updateBrightnessBasedOnTime($('#sunrise').text(), $('#sunset').text());
                        }, 1000);
                    }
                } else {
                    console.log('Diagnostic: Auto-theme and auto-brightness disabled, applying default theme');
                    applyDefaultTheme(defaultTheme);
                }

                $('#evening-offset').val(config.evening_offset || 60);
                $('#night-time').val(config.night_time || '20:00');

                debouncedSaveConfig();
            } else {
                console.warn('Diagnostic: No theme data in config, using defaults');
                applyDefaultSettings();
            }
            initializeSceneEditor();
        } catch (e) {
            console.error('Diagnostic: Error processing config data:', e);
            applyDefaultSettings();
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error loading config:', textStatus, errorThrown);
        applyDefaultSettings();
    });
}

function loadScenes(retryCount = 3, delay = 1000) {
    console.log('Diagnostic: Loading scenes from /get_scenes');
    $.get('/get_scenes', function(data) {
        try {
            sceneConfigs = typeof data === 'string' ? JSON.parse(data) : data;
            console.log('Diagnostic: Scenes loaded:', sceneConfigs);
            checkActiveScene();
        } catch (e) {
            console.error('Diagnostic: Error parsing /get_scenes:', e);
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error loading scenes:', textStatus, errorThrown);
        if (retryCount > 0) {
            console.log(`Diagnostic: Retrying loadScenes (${retryCount} attempts left)`);
            setTimeout(() => loadScenes(retryCount - 1, delay * 2), delay);
        } else {
            console.warn('Diagnostic: Failed to load scenes after retries');
        }
    });
}

const debouncedCheckActiveScene = debounce(function() {
    if (!Object.keys(sceneConfigs).length) {
        console.log('Diagnostic: Scene configs not loaded, skipping active scene check');
        return;
    }

    $.get('/get_active_scene', function(data) {
        if (data.active_scene) {
            console.log('Diagnostic: Using backend active scene:', data.active_scene);
            currentActiveScene = data.active_scene;
            $('.scene-btn').removeClass('active');
            const sceneTitle = currentActiveScene.replace('_', ' ').toLowerCase();
            $('.scene-btn').each(function() {
                const buttonText = $(this).text().trim().toLowerCase().replace(' ', '');
                if (buttonText.includes(sceneTitle)) {
                    $(this).addClass('active');
                }
            });
        } else {
            $.when(
                $.get('/get_arduino_states'),
                $.get('/get_relay_states')
            ).done(function(arduinoResponse, relayResponse) {
                try {
                    const arduinoStates = typeof arduinoResponse[0] === 'string' ? JSON.parse(arduinoResponse[0]) : arduinoResponse[0];
                    const relayStates = typeof relayResponse[0] === 'string' ? JSON.parse(relayResponse[0]) : relayResponse[0];
                    console.log('Diagnostic: Backend scene null, inferring from states - Arduino:', arduinoStates, 'Relay:', relayStates);

                    let newActiveScene = null;
                    Object.keys(sceneConfigs).forEach(scene => {
                        const sceneConfig = sceneConfigs[scene];
                        let isMatch = true;

                        if (sceneConfig.arduino) {
                            Object.keys(sceneConfig.arduino).forEach(channel => {
                                const sceneValue = sceneConfig.arduino[channel];
                                const currentValue = parseInt(arduinoStates[channel]) || 0;
                                if (Math.abs(sceneValue - currentValue) > 2) {
                                    isMatch = false;
                                }
                            });
                        }

                        if (sceneConfig.relays) {
                            Object.keys(sceneConfig.relays).forEach(channel => {
                                const sceneValue = sceneConfig.relays[channel];
                                const currentValue = relayStates[channel] ? 1 : 0;
                                if (sceneValue !== currentValue) {
                                    isMatch = false;
                                }
                            });
                        }

                        if (isMatch) {
                            Object.keys(arduinoStates).forEach(channel => {
                                if (!sceneConfig.arduino || !(channel in sceneConfig.arduino)) {
                                    const currentValue = parseInt(arduinoStates[channel]) || 0;
                                    if (currentValue > 2) {
                                        isMatch = false;
                                    }
                                }
                            });
                            Object.keys(relayStates).forEach(channel => {
                                if (!sceneConfig.relays || !(channel in sceneConfig.relays)) {
                                    const currentValue = relayStates[channel] ? 1 : 0;
                                    if (currentValue !== 0) {
                                        isMatch = false;
                                    }
                                }
                            });
                        }

                        if (isMatch) {
                            newActiveScene = scene;
                        }
                    });

                    console.log('Diagnostic: Inferred active scene:', newActiveScene);
                    $('.scene-btn').removeClass('active');
                    if (newActiveScene) {
                        const sceneTitle = newActiveScene.replace('_', ' ').toLowerCase();
                        $('.scene-btn').each(function() {
                            const buttonText = $(this).text().trim().toLowerCase().replace(' ', '');
                            if (buttonText.includes(sceneTitle)) {
                                $(this).addClass('active');
                            }
                        });
                        currentActiveScene = newActiveScene;
                    } else {
                        currentActiveScene = null;
                    }
                } catch (e) {
                    console.error('Diagnostic: Error in checkActiveScene inference:', e);
                    $('.scene-btn').removeClass('active');
                    currentActiveScene = null;
                }
            }).fail(function(jqXHR, textStatus, errorThrown) {
                console.error('Diagnostic: Error fetching states for checkActiveScene:', textStatus, errorThrown);
                $('.scene-btn').removeClass('active');
                currentActiveScene = null;
            });
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error('Diagnostic: Error fetching /get_active_scene in checkActiveScene:', textStatus, errorThrown);
        $.when(
            $.get('/get_arduino_states'),
            $.get('/get_relay_states')
        ).done(function(arduinoResponse, relayResponse) {
            try {
                const arduinoStates = typeof arduinoResponse[0] === 'string' ? JSON.parse(arduinoResponse[0]) : arduinoResponse[0];
                const relayStates = typeof relayResponse[0] === 'string' ? JSON.parse(relayResponse[0]) : relayResponse[0];
                console.log('Diagnostic: Backend scene null, inferring from states - Arduino:', arduinoStates, 'Relay:', relayStates);

                let newActiveScene = null;
                Object.keys(sceneConfigs).forEach(scene => {
                    const sceneConfig = sceneConfigs[scene];
                    let isMatch = true;

                    if (sceneConfig.arduino) {
                        Object.keys(sceneConfig.arduino).forEach(channel => {
                            const sceneValue = sceneConfig.arduino[channel];
                            const currentValue = parseInt(arduinoStates[channel]) || 0;
                            if (Math.abs(sceneValue - currentValue) > 2) {
                                isMatch = false;
                            }
                        });
                    }

                    if (sceneConfig.relays) {
                        Object.keys(sceneConfig.relays).forEach(channel => {
                            const sceneValue = sceneConfig.relays[channel];
                            const currentValue = relayStates[channel] ? 1 : 0;
                            if (sceneValue !== currentValue) {
                                isMatch = false;
                            }
                        });
                    }

                    if (isMatch) {
                        Object.keys(arduinoStates).forEach(channel => {
                            if (!sceneConfig.arduino || !(channel in sceneConfig.arduino)) {
                                const currentValue = parseInt(arduinoStates[channel]) || 0;
                                if (currentValue > 2) {
                                    isMatch = false;
                                }
                            }
                        });
                        Object.keys(relayStates).forEach(channel => {
                            if (!sceneConfig.relays || !(channel in sceneConfig.relays)) {
                                const currentValue = relayStates[channel] ? 1 : 0;
                                if (currentValue !== 0) {
                                    isMatch = false;
                                }
                            }
                        });
                    }

                    if (isMatch) {
                        newActiveScene = scene;
                    }
                });

                console.log('Diagnostic: Inferred active scene:', newActiveScene);
                $('.scene-btn').removeClass('active');
                if (newActiveScene) {
                    const sceneTitle = newActiveScene.replace('_', ' ').toLowerCase();
                    $('.scene-btn').each(function() {
                        const buttonText = $(this).text().trim().toLowerCase().replace(' ', '');
                        if (buttonText.includes(sceneTitle)) {
                            $(this).addClass('active');
                        }
                    });
                    currentActiveScene = newActiveScene;
                } else {
                    currentActiveScene = null;
                }
            } catch (e) {
                console.error('Diagnostic: Error in checkActiveScene inference:', e);
                $('.scene-btn').removeClass('active');
                currentActiveScene = null;
            }
        }).fail(function(jqXHR, textStatus, errorThrown) {
            console.error('Diagnostic: Error fetching states for checkActiveScene:', textStatus, errorThrown);
            $('.scene-btn').removeClass('active');
            currentActiveScene = null;
        });
    });
}, 500);

function checkActiveScene() {
    debouncedCheckActiveScene();
}

function applyDefaultSettings() {
    console.warn('Diagnostic: Applying default settings due to config load failure');
    $('#dark-mode-toggle').prop('checked', false).parent().removeClass('on');
    $('#auto-theme-toggle').prop('checked', false).parent().removeClass('on');
    $('#auto-brightness-toggle').prop('checked', false).parent().removeClass('on');
    $('#default-theme').val('light').prop('disabled', false).css('opacity', 1);
    $('.brightness-btn').removeClass('active');
    $(`.brightness-btn[data-brightness="medium"]`).addClass('active');
    setScreenBrightness('medium');
    applyDefaultTheme('light');
}

function openSettings() {
    console.log('Diagnostic: Opening settings modal');
    $('#settingsModal').fadeIn();
    openTab('general');
    positionCloseButton();
    $(window).off('resize.closeButton').on('resize.closeButton', positionCloseButton);
}

function positionCloseButton() {
    const $settingsContent = $('.settings-content');
    const $closeButton = $('.close-settings');
    const contentRect = $settingsContent[0].getBoundingClientRect();
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    const buttonWidth = $closeButton.outerWidth();

    const targetRight = contentRect.right + 1.5 * rem;
    const leftPosition = targetRight - buttonWidth;

    $closeButton.css({
        position: 'fixed',
        top: (contentRect.top - 1.5 * rem) + 'px',
        left: leftPosition + 'px'
    });

    console.log('Diagnostic: Positioning close button:', { contentRect, buttonWidth, targetRight, leftPosition });
}

function closeSettings(event) {
    event.stopPropagation();
    console.log('Diagnostic: Closing settings modal');
    $('#settingsModal').fadeOut();
    $(window).off('resize.closeButton');
}

function openTab(tabName) {
    console.log('Diagnostic: Opening tab:', tabName);
    $('.tab-content').removeClass('active');
    $('.tab-btn').removeClass('active');
    $('#' + tabName + '-tab').addClass('active');
    $(`[onclick="openTab('${tabName}')"]`).addClass('active');
}

function rampFaders() {
    const rampDuration = 1000;
    const stepInterval = 50;
    const steps = Math.ceil(rampDuration / stepInterval);
    let currentStep = 0;

    console.log('Diagnostic: Starting fader ramp polling');
    $('.scene-btn').removeClass('active');
    currentActiveScene = null;
    checkActiveScene();
    const interval = setInterval(() => {
        console.log(`Diagnostic: Fader ramp step ${currentStep + 1} fetching states`);
        $.get('/get_arduino_states', function(data) {
            try {
                if (data.error) {
                    console.error(`Diagnostic: Error in /get_arduino_states during ramp: ${data.error}`);
                    return;
                }
                const states = typeof data === 'string' ? JSON.parse(data) : data;
                console.log(`Diagnostic: Fader ramp step ${currentStep + 1}:`, states);
                lastArduinoStates = states;
                lastArduinoStatesTime = Date.now();
                updateArduinoSliders(states);
            } catch (e) {
                console.error('Diagnostic: Error parsing /get_arduino_states during ramp:', e);
            }
        }).fail(function(jqXHR, textStatus, errorThrown) {
            console.error('Diagnostic: Error fetching /get_arduino_states during ramp:', textStatus, errorThrown);
        });

        currentStep++;
        if (currentStep >= steps) {
            clearInterval(interval);
            console.log('Diagnostic: Finished fader ramp polling');
            debouncedFetchArduinoStates();
        }
    }, stepInterval);
}

function refreshPage() {
    console.log('Diagnostic: Refreshing page');
    location.reload();
}

let activeSceneId = 'evening';

function initializeSceneEditor() {
    $('.scene-edit-btn').click(function() {
        $('.scene-edit-btn').removeClass('active');
        $(this).addClass('active');
        activeSceneId = $(this).attr('data-scene-id');
        renderLightsList();
    });
    renderLightsList();
}

function renderLightsList() {
    const lightsList = $('.lights-list');
    lightsList.empty();
    const displayKey = getDisplayKey();

    if (!config.channels || !config.channels.arduino || !config.channels.relays) {
        console.error('Invalid config.channels:', config.channels);
        lightsList.append('<p>Error: No lights configuration found.</p>');
        return;
    }

    const lights = [
        ...Object.entries(config.channels.arduino)
            .filter(([_, info]) => {
                const displayValue = info.display;
                return typeof displayValue === 'object' ? displayValue[displayKey] : displayValue;
            })
            .map(([channel, info]) => ({
                id: `arduino:${channel}`,
                name: info.name,
                type: 'dimmer',
                channel
            })),
        ...Object.entries(config.channels.relays)
            .filter(([_, info]) => {
                const displayValue = info.display;
                return typeof displayValue === 'object' ? displayValue[displayKey] : displayValue;
            })
            .map(([channel, info]) => ({
                id: `relays:${channel}`,
                name: info.name,
                type: 'switch',
                channel
            }))
    ];

    console.log(`Diagnostic: Lights array for ${displayKey} touchscreen:`, lights);

    if (lights.length === 0) {
        console.warn(`No lights found for ${displayKey} touchscreen.`);
        lightsList.append('<p>No lights available.</p>');
        return;
    }

    lights.forEach(light => {
        const sceneData = config.scenes[activeSceneId] || { arduino: {}, relays: {} };
        const isPartOfScene = light.type === 'dimmer'
            ? sceneData.arduino && light.channel in sceneData.arduino
            : sceneData.relays && light.channel in sceneData.relays;
        const brightness = light.type === 'dimmer' && isPartOfScene
            ? sceneData.arduino[light.channel]
            : 0;
        const relayState = light.type === 'switch' && isPartOfScene
            ? sceneData.relays[light.channel]
            : 0;

        let controlHtml = '';
        if (light.type === 'switch') {
            controlHtml = `
                <div class="toggle-slider ${relayState ? 'active' : ''}"
                     onclick="toggleSceneRelay('${light.id}', this)">
                    <div class="slider-circle"></div>
                </div>
            `;
        } else if (light.type === 'dimmer') {
            controlHtml = `
                <input type="range" min="0" max="100" value="${brightness}"
                       style="--value: ${brightness}%;"
                       onchange="updateBrightness('${light.id}', this.value)">
                <span class="brightness-value">${brightness}%</span>
            `;
        }

        const lightHtml = `
            <div class="light-item" data-light-id="${light.id}">
                <label>${light.name}</label>
                <input type="checkbox" ${isPartOfScene ? 'checked' : ''} 
                       onchange="updateSceneMembership('${light.id}', this.checked)">
                ${controlHtml}
            </div>
        `;
        lightsList.append(lightHtml);
    });
}

function toggleSceneRelay(lightId, element) {
    $(element).toggleClass('active');
    updateSceneLightSettings(lightId);
}

function updateBrightness(lightId, value) {
    const slider = $(`.light-item[data-light-id="${lightId}"] input[type="range"]`);
    slider.css('--value', `${value}%`);
    $(`.light-item[data-light-id="${lightId}"] .brightness-value`).text(`${value}%`);
    updateSceneLightSettings(lightId);
}

function updateSceneMembership(lightId, isChecked) {
    const lightItem = $(`.light-item[data-light-id="${lightId}"]`);
    const [channelType, channel] = lightId.split(':');

    if (!config.scenes[activeSceneId]) {
        config.scenes[activeSceneId] = { arduino: {}, relays: {} };
    }
    if (!config.scenes[activeSceneId][channelType]) {
        config.scenes[activeSceneId][channelType] = {};
    }

    if (isChecked) {
        // Add with default value
        if (channelType === 'relays') {
            config.scenes[activeSceneId].relays[channel] = 0; // Default off
            lightItem.find('.toggle-slider').removeClass('active');
        } else if (channelType === 'arduino') {
            config.scenes[activeSceneId].arduino[channel] = 0; // Default 0%
            lightItem.find('input[type="range"]').val(0).css('--value', '0%');
            lightItem.find('.brightness-value').text('0%');
        }
    } else {
        // Remove
        delete config.scenes[activeSceneId][channelType][channel];
        if (Object.keys(config.scenes[activeSceneId][channelType]).length === 0) {
            delete config.scenes[activeSceneId][channelType];
        }
    }
}

function updateSceneLightSettings(lightId) {
    const lightItem = $(`.light-item[data-light-id="${lightId}"]`);
    const isPartOfScene = lightItem.find('input[type="checkbox"]').is(':checked');
    const [channelType, channel] = lightId.split(':');

    if (!config.scenes[activeSceneId]) {
        config.scenes[activeSceneId] = { arduino: {}, relays: {} };
    }
    if (!config.scenes[activeSceneId][channelType]) {
        config.scenes[activeSceneId][channelType] = {};
    }

    if (isPartOfScene) {
        if (channelType === 'relays') {
            const state = lightItem.find('.toggle-slider').hasClass('active') ? 1 : 0;
            config.scenes[activeSceneId].relays[channel] = state;
        } else if (channelType === 'arduino') {
            const brightness = parseInt(lightItem.find('input[type="range"]').val());
            config.scenes[activeSceneId].arduino[channel] = brightness;
        }
    } else {
        delete config.scenes[activeSceneId][channelType][channel];
        if (Object.keys(config.scenes[activeSceneId][channelType]).length === 0) {
            delete config.scenes[activeSceneId][channelType];
        }
    }
}

function saveScene() {
    $.ajax({
        url: '/save_config',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(config),
        success: function(response) {
            originalConfig = JSON.parse(JSON.stringify(config));
            alert('Scene saved successfully!');
        },
        error: function(xhr) {
            alert('Error saving scene: ' + (xhr.responseJSON?.error || 'Unknown error'));
        }
    });
}

function cancelScene() {
    config = JSON.parse(JSON.stringify(originalConfig));
    renderLightsList();
    alert('Changes cancelled.');
}