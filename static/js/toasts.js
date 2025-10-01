const toastArea = document.querySelector('.toast-area');
let toastQueue = [];
const toastHeight = 60; // Approximate height including padding
const gap = 10;
let offlineToast = null;
let toastDuration = 5000;

function updateToastPositions() {
    const toasts = Array.from(toastArea.children);
    toasts.forEach((toast, index) => {
        const pos = (toasts.length - 1 - index) * (toastHeight + gap);
        toast.style.bottom = `${pos}px`;
    });
}

function createToast(message, type, persistent = false, additionalClasses = []) {
    const toastElem = document.createElement('div');
    toastElem.classList.add(`toast-${type}`);
    additionalClasses.forEach(cls => toastElem.classList.add(cls));
    toastElem.textContent = message;
    toastElem.style.opacity = '0';
    toastElem.style.bottom = `-${toastHeight}px`;
    toastArea.appendChild(toastElem);

    setTimeout(() => {
        toastElem.style.opacity = '1';
        updateToastPositions();
    }, 10);

    if (!persistent) {
        toastElem.addEventListener('click', () => removeToast(toastElem));
        setTimeout(() => removeToast(toastElem), toastDuration);
    }

    return toastElem;
}

function removeToast(toastElem) {
    toastElem.style.opacity = '0';
    setTimeout(() => {
        if (toastElem.parentNode) {
            toastElem.parentNode.removeChild(toastElem);
            updateToastPositions();
            if (toastQueue.length > 0) {
                const next = toastQueue.shift();
                createToast(next.message, next.type, next.persistent, next.additionalClasses || []);
            }
        }
    }, 500);
}

function showToast(message, type = 'message', persistent = false, additionalClasses = []) {
    if (toastArea.children.length >= 9) {
        toastQueue.push({ message, type, persistent, additionalClasses });
        return;
    }
    return createToast(message, type, persistent, additionalClasses);
}