/**
 * PCCS Toast Notifications
 * Extracted from templates/index.html
 */
(function () {
  'use strict';
  const PCCS = window.PCCS;
  const S = PCCS.state;
  function getSocket() { return PCCS.getSocket(); }

// ====================== TOAST SYSTEM ======================
    function createToast(data) {
        const { id, message, type = "info", duration = 5000, title, persistent = false } = data || {};
        const container = document.getElementById('toast-container');
        if (!container) return;

        let icon = 'fa-info-circle';
        if (type === 'success') icon = 'fa-check-circle';
        else if (type === 'warning') icon = 'fa-exclamation-triangle';
        else if (type === 'error') icon = 'fa-circle-xmark';

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.id = id || 'toast-' + Date.now();

		toast.innerHTML = `
			<i class="fa-solid ${icon} text-2xl flex-shrink-0 mt-0.5"></i>
			<div class="toast-content flex-1 min-w-0">
				${title ? `<div class="toast-title">${title}</div>` : ''}
				<div class="toast-message">${message}</div>
			</div>
			<button class="text-xl leading-none self-start mt-0.5" aria-label="Close">
				<i class="fa-solid fa-xmark"></i>
			</button>
		`;

        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('show'));

        const closeBtn = toast.querySelector('button');
        closeBtn.addEventListener('click', () => dismissToast(toast));

        toast.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON' && !e.target.closest('button')) dismissToast(toast);
        });

        if (!persistent && duration > 0) {
            setTimeout(() => dismissToast(toast), duration);
        }
    }

    function dismissToast(toast) {
        if (!toast || !toast.parentNode) return;
        toast.style.transition = 'opacity 0.95s cubic-bezier(0.25, 0.1, 0.25, 1), transform 0.95s cubic-bezier(0.25, 0.1, 0.25, 1)';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(12px)';

        toast.addEventListener('transitionend', () => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, { once: true });
    }

  PCCS.toasts = {
    createToast,
    dismissToast,
    register(socket) {
      socket.on('toast', data => createToast(data));
    },
  };
})();
