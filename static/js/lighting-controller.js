/**
 * PCCS Lighting Controller
 * Extracted from templates/index.html
 */
import { PCCS, getSocket } from './namespace.js';

const S = PCCS.state;

  function emitLightChange(payload) {
    const socket = getSocket();
    if (socket?.connected) {
      socket.emit('light_change', payload);
    } else {
      console.warn('[PCCS] light_change socket unavailable — using HTTP fallback', payload);
    }
    fetch('/api/light', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (data?.state) PCCS.lighting.onStateUpdate(data.state);
      })
      .catch(err => console.warn('[PCCS] light_change HTTP failed', err));
    return true;
  }

  function emitRelayChange(name, on) {
    const socket = getSocket();
    if (!socket?.connected) {
      console.warn('[PCCS] relay_change skipped — socket unavailable', name);
      return false;
    }
    socket.emit('relay_change', { name, on });
    return true;
  }

function getCurrentColumns() {
		const container = document.getElementById('lighting-controls');
		if (!container) return 1;

		const style = window.getComputedStyle(container);
		const gridTemplate = style.gridTemplateColumns || style.getPropertyValue('grid-template-columns');

		if (gridTemplate.includes('repeat(1') || gridTemplate.split(' ').length === 1) return 1;
		if (gridTemplate.includes('repeat(2') || gridTemplate.split(' ').length === 2) return 2;
		if (gridTemplate.includes('repeat(3') || gridTemplate.split(' ').length === 3) return 3;

		const children = container.children.length;
		if (children > 0) {
			const firstChild = container.children[0];
			const containerRect = container.getBoundingClientRect();
			const childRect = firstChild.getBoundingClientRect();
			
			if (containerRect.width > 0) {
				const approxCols = Math.round(containerRect.width / (childRect.width + 16)); // + gap
				return Math.max(1, Math.min(3, approxCols));
			}
		}

		return 1;
	}

// ==================== LIGHTING RENDERING ====================
	function renderLightingControls() {
		const container = document.getElementById('lighting-controls');
		if (!container) {
			return false;
		}

		const currentHash = JSON.stringify(S.lightsConfig.map(l => l.name + l.type));
		if (currentHash === S.lastRenderConfigHash && S.lightsConfig.length > 0) {
			updateUIFromState();
			return true;
		}
		
		S.lastRenderConfigHash = currentHash;

		container.innerHTML = '';

		const columns = getCurrentColumns();
		
		let i = 0;
		while (i < S.lightsConfig.length) {
			const light = S.lightsConfig[i];

			const canPair = light.type === 'relay' &&
							i + 1 < S.lightsConfig.length &&
							S.lightsConfig[i + 1].type === 'relay';

			let shouldPair = canPair;

			if (canPair) {
				if (columns === 1) {
					shouldPair = false;
				} else if (columns === 2) {
					const isLastPair = (i + 2 === S.lightsConfig.length);
					shouldPair = !isLastPair;
				}
			}

			if (shouldPair) {
				const relay1 = light;
				const relay2 = S.lightsConfig[i + 1];

				const html = `
					<div class="slider-card glass paired-relay-card">
						<div class="paired-relay-inner">
							<!-- First relay -->
							<div class="paired-relay-row">
								<div class="slider-card-left">
									<div class="slider-card-title">
										<i class="fa-solid ${relay1.icon}"></i>
										<span class="slider-label">${relay1.label}</span>
									</div>
								</div>
								<div class="slider-card-right">
									<div class="value-display" id="val-${relay1.name}">${(S.currentState[relay1.name] ? 'On' : 'Off')}</div>
									<div class="relay-toggle ${S.currentState[relay1.name] ? 'on' : ''}" 
										 data-name="${relay1.name}" 
										 data-state="${S.currentState[relay1.name] ? 'on' : 'off'}">
										<div class="relay-knob"></div>
									</div>
								</div>
							</div>

							<div class="paired-relay-divider"></div>

							<!-- Second relay -->
							<div class="paired-relay-row">
								<div class="slider-card-left">
									<div class="slider-card-title">
										<i class="fa-solid ${relay2.icon}"></i>
										<span class="slider-label">${relay2.label}</span>
									</div>
								</div>
								<div class="slider-card-right">
									<div class="value-display" id="val-${relay2.name}">${(S.currentState[relay2.name] ? 'On' : 'Off')}</div>
									<div class="relay-toggle ${S.currentState[relay2.name] ? 'on' : ''}" 
										 data-name="${relay2.name}" 
										 data-state="${S.currentState[relay2.name] ? 'on' : 'off'}">
										<div class="relay-knob"></div>
									</div>
								</div>
							</div>
						</div>
					</div>`;

				container.innerHTML += html;
				i += 2;
				continue;
			}

			const isRelay = light.type === 'relay';
			const currentVal = S.currentState[light.name] || 0;
			const isOn = isRelay ? !!currentVal : false;

			let html = `
				<div class="slider-card glass">
					<div class="slider-card-header">
						<div class="slider-card-left">
							<div class="slider-card-title">
								<i class="fa-solid ${light.icon}"></i>
								<span class="slider-label">${light.label}</span>
							</div>
						</div>
						<div class="slider-card-right">
							<div class="value-display" id="val-${light.name}">
								${isRelay ? (isOn ? 'On' : 'Off') : '0%'}
							</div>`;

			if (isRelay) {
				html += `
							<div class="relay-toggle ${isOn ? 'on' : ''}" 
								 data-name="${light.name}" 
								 data-state="${isOn ? 'on' : 'off'}">
								<div class="relay-knob"></div>
							</div>`;
			} else {
				const extraClass = light.has_mode ? 'colour-toggle' : '';
				html += `
							<div class="toggle-pill ${extraClass}" data-name="${light.name}" data-state="off">
								<div class="toggle-knob"></div>
							</div>`;
			}

			html += `</div></div>`;

			if (!isRelay) {
				html += `
					<div class="slider-wrapper" data-name="${light.name}" data-value="0" data-last-brightness="100">
						<div class="slider-inner">
							<div class="slider-track"></div>
							<div class="slider-fill" style="width: 0%"></div>
							<div class="slider-thumb" style="left: 0%"></div>
						</div>
					</div>`;
			}

			html += `</div>`;
			container.innerHTML += html;
			i++;
		}

		initUnifiedToggleListeners();
		initSliders();

		setTimeout(updateUIFromState, 100);
		return true;
	}

	function toggleControl(el) {
		const name = el.dataset.name;
		const light = S.lightsConfig.find(l => l.name === name);
		if (!light) return;

		// Safety: rooftop tent reed closed → block all user interaction on frontend
		if (name === 'rooftop_tent' && isRooftopTentPhysicallyClosed()) {
			return;
		}

		S.userJustSet.add(name);
		setTimeout(() => S.userJustSet.delete(name), S.JUST_SET_DURATION);

		if (light.type === 'relay') {
			const isCurrentlyOn = el.dataset.state === 'on';
			const newState = !isCurrentlyOn;

			updateLightUI(name, newState ? 1 : 0);
			emitRelayChange(name, newState);
			
			setTimeout(() => updateLightUI(name, newState ? 1 : 0), 50);
			return;
		}

		if (light.has_mode) {
			const currentMode = S.currentModes[name] || 'white';
			const newMode = currentMode === 'white' ? 'red' : 'white';
			S.currentModes[name] = newMode;

			const currentBrightness = S.currentState[name] || 0;
			// Update UI immediately — a delayed update loses races with stale state_update.
			updateLightUI(name, currentBrightness);

			emitLightChange({
				name,
				brightness: currentBrightness,
				mode: newMode,
			});
			return;
		}

		const wrapper = document.querySelector(`.slider-wrapper[data-name="${name}"]`);
		const currentBrightness = wrapper ? parseInt(wrapper.dataset.value) || 0 : 0;
		const isOn = el.dataset.state === 'on';
		const newBrightness = isOn ? 0 : (parseInt(wrapper?.dataset.lastBrightness) || 100);

		updateLightUI(name, newBrightness);
		S.currentState[name] = newBrightness;  // keep model in sync with just-set value
		emitLightChange({ name, brightness: newBrightness });
	}

	function initUnifiedToggleListeners() {
		const container = document.getElementById('lighting-controls');
		
		container.removeEventListener('click', handleLightingClick);
		
		function handleLightingClick(e) {
			const toggle = e.target.closest('.relay-toggle, .toggle-pill');
			if (!toggle) return;
			
			if (toggle.dataset.justClicked === 'true') return;
			toggle.dataset.justClicked = 'true';
			setTimeout(() => delete toggle.dataset.justClicked, 350);
			
			toggleControl(toggle);
		}
		
		container.addEventListener('click', handleLightingClick);
	}

	function updateLightUI(name, value) {
		const light = S.lightsConfig.find(l => l.name === name);
		if (!light) return;

		const valueEl = document.getElementById(`val-${name}`);
		const pills = document.querySelectorAll(
			`.toggle-pill[data-name="${name}"], .relay-toggle[data-name="${name}"]`
		);

		if (light.type === 'relay') {
			const isOn = !!value;

			pills.forEach(toggle => {
				toggle.classList.toggle('on', isOn);
				toggle.dataset.state = isOn ? 'on' : 'off';
			});

			if (valueEl) {
				valueEl.textContent = isOn ? 'On' : 'Off';
			}
			return;
		}

		// ====================== DIMMERS / BUG MODE ======================
		const wrapper = document.querySelector(`.slider-wrapper[data-name="${name}"]`);
		const fill = wrapper ? wrapper.querySelector('.slider-fill') : null;
		const thumb = wrapper ? wrapper.querySelector('.slider-thumb') : null;
		const brightness = Math.max(0, Math.min(100, value || 0));
		const card = wrapper ? wrapper.closest('.slider-card') : null;

		if (wrapper) {
			wrapper.dataset.value = brightness;
			if (brightness > 0) wrapper.dataset.lastBrightness = brightness;

			if (fill) fill.style.width = `${brightness}%`;
			if (thumb) thumb.style.left = `${brightness}%`;
			if (valueEl) valueEl.textContent = `${brightness}%`;
		}

		const isBugMode = light.has_mode && (S.currentModes[name] || 'white') === 'red';
		const pillOn = light.has_mode ? isBugMode : (brightness > 0);

		pills.forEach(pill => {
			pill.classList.toggle('on', pillOn);
			pill.classList.toggle('bug-mode', isBugMode);
			pill.dataset.state = pillOn ? 'on' : 'off';
		});

		if (card) card.classList.toggle('bug-mode', isBugMode);

		if (wrapper) {
			wrapper.classList.toggle('bug-mode', isBugMode);
			if (fill) fill.classList.toggle('bug-mode', isBugMode);
			if (thumb) thumb.classList.toggle('bug-mode', isBugMode);
		}
	}

	// ==================== UPDATE UI FROM STATE ====================
	function cancelSceneAnimations() {
		Object.values(S.sceneAnimationCancels).forEach(cancel => {
			if (typeof cancel === 'function') cancel();
		});
		S.sceneAnimationCancels = {};
	}

	function setSliderMotion(wrapper, enabled) {
		if (!wrapper) return;
		const fill = wrapper.querySelector('.slider-fill');
		const thumb = wrapper.querySelector('.slider-thumb');
		const transition = enabled ? '' : 'none';
		if (fill) fill.style.transition = transition;
		if (thumb) thumb.style.transition = transition;
	}

	function applyStateToUI(newState, { animate = false, rampMs = S.SCENE_RAMP_MS } = {}) {
		const protectedLights = new Set([...S.currentlyDragging]);
		if (!animate) {
			S.userJustSet.forEach(name => protectedLights.add(name));
		}

		S.lightsConfig.forEach(light => {
			const modeKey = `${light.name}_mode`;
			if (light.has_mode && newState[modeKey] && !protectedLights.has(light.name)) {
				S.currentModes[light.name] = newState[modeKey];
			}
		});

		if (!animate) {
			Object.keys(newState).forEach(k => {
				if (k.endsWith('_mode')) return;
				if (!protectedLights.has(k)) S.currentState[k] = newState[k];
			});
			updateUIFromState();
			return;
		}

		cancelSceneAnimations();

		S.lightsConfig.forEach(light => {
			if (protectedLights.has(light.name)) return;

			const target = newState[light.name];
			if (target === undefined) return;

			if (light.type === 'relay') {
				S.currentState[light.name] = !!target;
				updateLightUI(light.name, !!target);
				return;
			}

			const wrapper = document.querySelector(`.slider-wrapper[data-name="${light.name}"]`);
			const start = parseInt(wrapper?.dataset.value, 10);
			const from = Number.isFinite(start) ? start : (S.currentState[light.name] || 0);
			const end = Math.max(0, Math.min(100, target || 0));
			S.currentState[light.name] = end;

			if (from === end) {
				updateLightUI(light.name, end);
				return;
			}

			setSliderMotion(wrapper, false);
			S.sceneAnimationCancels[light.name] = PCCS.animate.run({
				duration: rampMs,
				onStep: (t) => {
					const v = Math.round(from + (end - from) * t);
					updateLightUI(light.name, v);
				},
				onComplete: () => {
					updateLightUI(light.name, end);
					setSliderMotion(wrapper, true);
					delete S.sceneAnimationCancels[light.name];
				},
			});
		});

		updateRooftopTentControls();
	}

	function updateUIFromState() {
		S.lightsConfig.forEach(light => {
			if (S.currentlyDragging.has(light.name) || S.userJustSet.has(light.name)) {
				return;
			}

			const val = S.currentState[light.name];
			if (val === undefined) return;

			// Always pass boolean for relays
			updateLightUI(light.name, light.type === 'relay' ? !!val : (val || 0));
		});

		updateRooftopTentControls();
	}

    // ==================== DRAG LOGIC (pointer events) ====================
	let lastTouchPointerUp = 0;

	function makeDraggable(wrapper) {
		if (wrapper.dataset.pccsSliderBound === '1') return;
		wrapper.dataset.pccsSliderBound = '1';

		const inner = wrapper.querySelector('.slider-inner');
		const fill = wrapper.querySelector('.slider-fill');
		const thumb = wrapper.querySelector('.slider-thumb');
		const name = wrapper.dataset.name;
		const valueEl = document.getElementById(`val-${name}`);

		let isDragging = false;
		let activePointerId = null;
		let startX = 0;
		let startY = 0;
		let valueAtPointerStart = 0;

		function updatePosition(clientX) {
			const rect = inner.getBoundingClientRect();
			const percent = Math.max(0, Math.min(100,
				Math.round(((clientX - rect.left) / rect.width) * 100)
			));

			wrapper.dataset.value = percent;
			if (fill) fill.style.width = `${percent}%`;
			if (thumb) thumb.style.left = `${percent}%`;
			if (valueEl) valueEl.textContent = `${percent}%`;
		}

		function startDrag() {
			if (isDragging) return;
			isDragging = true;
			wrapper.classList.add('dragging');
			S.currentlyDragging.add(name);
			S.userJustSet.delete(name);
			if (fill) fill.style.transition = 'none';
			if (thumb) thumb.style.transition = 'none';
		}

		function commitDrag(force) {
			if (!force && !isDragging) return;

			const final = parseInt(wrapper.dataset.value) || 0;
			isDragging = false;
			activePointerId = null;
			wrapper.classList.remove('dragging');
			S.currentlyDragging.delete(name);

			S.userJustSet.add(name);
			setTimeout(() => S.userJustSet.delete(name), S.JUST_SET_DURATION);
			S.currentState[name] = final;
			updateLightUI(name, final);

			const light = S.lightsConfig.find(l => l.name === name);
			const payload = { name, brightness: final };
			if (light?.has_mode && S.currentModes[name]) {
				payload.mode = S.currentModes[name];
			}
			emitLightChange(payload);
		}

		wrapper.addEventListener('pointerdown', e => {
			if (e.button !== 0) return;
			if (name === 'rooftop_tent' && isRooftopTentPhysicallyClosed()) return;
			// Touchscreens fire synthetic mouse events after touch — ignore them.
			if (e.pointerType === 'mouse' && Date.now() - lastTouchPointerUp < 600) return;

			activePointerId = e.pointerId;
			startX = e.clientX;
			startY = e.clientY;
			valueAtPointerStart = parseInt(wrapper.dataset.value) || 0;
			isDragging = false;

			if (e.pointerType === 'mouse') {
				e.preventDefault();
				wrapper.setPointerCapture(e.pointerId);
				startDrag();
				updatePosition(e.clientX);
			}
		});

		wrapper.addEventListener('pointermove', e => {
			if (e.pointerId !== activePointerId) return;
			if (name === 'rooftop_tent' && isRooftopTentPhysicallyClosed()) return;

			const deltaX = Math.abs(e.clientX - startX);
			const deltaY = Math.abs(e.clientY - startY);

			if (!isDragging) {
				if (e.pointerType === 'mouse') {
					startDrag();
				} else if (deltaX > 10 && deltaX > deltaY * 1.5) {
					e.preventDefault();
					wrapper.setPointerCapture(e.pointerId);
					startDrag();
				} else {
					return;
				}
			}

			e.preventDefault();
			updatePosition(e.clientX);
		});

		wrapper.addEventListener('pointerup', e => {
			if (e.pointerId !== activePointerId) return;
			if (e.pointerType === 'touch') lastTouchPointerUp = Date.now();
			try { wrapper.releasePointerCapture(e.pointerId); } catch (_) { /* ok */ }

			const final = parseInt(wrapper.dataset.value) || 0;
			const changed = isDragging || final !== valueAtPointerStart;
			if (changed) commitDrag(true);
			else {
				isDragging = false;
				activePointerId = null;
			}
		});

		wrapper.addEventListener('pointercancel', e => {
			if (e.pointerId !== activePointerId) return;
			if (isDragging) commitDrag(true);
			else {
				isDragging = false;
				activePointerId = null;
			}
		});
	}

    function initSliders() {
        document.querySelectorAll('.slider-wrapper:not([data-pccs-slider-bound="1"])').forEach(makeDraggable);
    }

    // ==================== ROOFTOP TENT ====================
    function updateRooftopTentControls() {
        const tentCard = document.querySelector('.slider-wrapper[data-name="rooftop_tent"]')?.closest('.slider-card');
        if (!tentCard) return;
        
        const isClosed = S.currentReeds.rooftop_tent !== false;
        
        if (isClosed) {
            tentCard.classList.add('rooftop-disabled');
            updateLightUI('rooftop_tent', 0);
        } else {
            tentCard.classList.remove('rooftop-disabled');
        }
    }

    function isRooftopTentPhysicallyClosed() {
        return S.currentReeds.rooftop_tent !== false;
    }

  PCCS.lighting = {
    getCurrentColumns,
    renderLightingControls,
    updateUIFromState,
    updateRooftopTentControls,
    isRooftopTentPhysicallyClosed,
    onLightsConfig(config) {
      S.lightsConfig = config || [];
      S.lightsConfig.forEach(light => {
        const mode = S.currentState[`${light.name}_mode`];
        if (light.has_mode && mode) S.currentModes[light.name] = mode;
      });
      if (!renderLightingControls()) {
        const renderWhenReady = () => {
          if (renderLightingControls()) {
            document.removeEventListener('DOMContentLoaded', renderWhenReady);
          }
        };
        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', renderWhenReady);
        } else {
          requestAnimationFrame(renderWhenReady);
        }
      }
      const socket = getSocket();
      if (socket?.connected) socket.emit('get_reeds');
      if (Object.keys(S.currentState).length > 0) updateUIFromState();
    },
    onStateUpdate(newState) {
      const animate = S.sceneActivating;
      S.sceneActivating = false;
      applyStateToUI(newState, { animate, rampMs: S.SCENE_RAMP_MS });
    },
    onReedUpdate(payload) {
      S.currentReeds = payload.states || {};
      updateRooftopTentControls();
    },
    initResize() {
      let lastColumnCount = getCurrentColumns();
      function handleResizeForLighting() {
        const newCols = getCurrentColumns();
        if (newCols !== lastColumnCount && S.lightsConfig.length > 0) {
          lastColumnCount = newCols;
          renderLightingControls();
        }
      }
      window.addEventListener('resize', handleResizeForLighting);
      setTimeout(() => { lastColumnCount = getCurrentColumns(); }, 300);
    },
  };
