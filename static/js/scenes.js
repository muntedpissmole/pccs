/**
 * PCCS Scene Buttons
 * Extracted from templates/index.html
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const S = PCCS.state;
  function getSocket() { return PCCS.getSocket(); }

// ==================== DYNAMIC SCENES ====================

  function setScene(sceneKey) {
    document.querySelectorAll('.scene-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.scene === sceneKey);
    });
    setTimeout(() => {
      document.querySelectorAll('.scene-btn').forEach(btn => btn.classList.remove('active'));
    }, 750);
    getSocket().emit('set_scene', { scene: sceneKey });
  }

	async function loadScenes() {
		try {
			const res = await fetch('/api/scenes');
			const data = await res.json();
			S.currentScenes = data.scenes || [];
			renderScenes();
		} catch (e) {
			console.error('Failed to load scenes', e);
		}
	}

	// ==================== SCENES ====================
	function renderScenes() {
		const container = document.getElementById('scenes-grid');
		if (!container) return;

		container.innerHTML = '';

		S.currentScenes.forEach(scene => {
			const btn = document.createElement('button');
			btn.className = `scene-btn flex flex-col items-center justify-center py-6 rounded-2xl transition-all active:scale-95 ${scene.all_off ? 'all-off-btn' : ''}`;
			btn.dataset.scene = scene.key;

			if (scene.description) {
				btn.title = scene.description;
			}

			btn.innerHTML = `
				<i class="fa-solid ${scene.icon} text-2xl mb-3"></i>
				<span class="font-medium text-sm tracking-wide">${scene.name}</span>
			`;

			btn.addEventListener('click', () => setScene(scene.key));
			container.appendChild(btn);
		});

		fixLastRowStretching(container);
	}

function fixLastRowStretching(container) {
    const total = S.currentScenes.length;
    if (total <= 3) return;

    const remainder = total % 3;
    if (remainder === 0) return;

    const buttons = Array.from(container.children);
    const lastRowStart = total - remainder;

    // Remove any previous last-row wrappers
    container.querySelectorAll('.last-row').forEach(el => {
        const kids = Array.from(el.children);
        kids.forEach(kid => container.appendChild(kid));
        el.remove();
    });

    if (remainder === 1) {
        // Single button → full width
        buttons[lastRowStart].style.gridColumn = '1 / -1';
    } 
    else if (remainder === 2) {
        // Two buttons → wrap in flex container for perfect equal width
        const btn1 = buttons[lastRowStart];
        const btn2 = buttons[lastRowStart + 1];

        const wrapper = document.createElement('div');
        wrapper.className = 'last-row';
        wrapper.style.gridColumn = '1 / -1';   // take full row

        wrapper.appendChild(btn1);
        wrapper.appendChild(btn2);

        container.appendChild(wrapper);
    }
}

	

  PCCS.scenes = {
    loadScenes,
    renderScenes,
    fixLastRowStretching,
    setScene,
  };
})();
