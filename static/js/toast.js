class ToastManager {
    constructor() {
        this.container = null;
    }

    ensureContainer() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            this.container.setAttribute('aria-live', 'polite');
            document.body.appendChild(this.container);
        }
        return this.container;
    }

    show(message, type = 'info', duration = 5000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
        toast.innerHTML = `<span class="toast-message"></span><button class="toast-close" type="button" aria-label="Close">&times;</button>`;
        toast.querySelector('.toast-message').textContent = message;
        toast.querySelector('.toast-close').addEventListener('click', () => toast.remove());
        this.ensureContainer().appendChild(toast);
        if (duration > 0) {
            window.setTimeout(() => toast.remove(), duration);
        }
        return toast;
    }

    success(message) { return this.show(message, 'success'); }
    error(message) { return this.show(message, 'error'); }
    info(message) { return this.show(message, 'info'); }
}

window.toast = new ToastManager();
