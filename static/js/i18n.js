class I18nManager {
    constructor() {
        this.translations = {};
        this.currentLang = localStorage.getItem('language') || 'uz_cyrl';
    }

    async init() {
        await this.loadTranslations(this.currentLang);
        this.applyTranslations();
    }

    async loadTranslations(lang) {
        try {
            const response = await fetch(`/api/v1/core/locale/${lang}/`);
            if (response.ok) {
                this.translations = await response.json();
                this.currentLang = lang;
                localStorage.setItem('language', lang);
            } else {
                console.error('Failed to load translations');
            }
        } catch (error) {
            console.error('Error loading translations', error);
        }
    }

    translate(key) {
        const keys = key.split('.');
        let value = this.translations;
        for (const k of keys) {
            if (value && value[k]) {
                value = value[k];
            } else {
                return key; // return key if not found
            }
        }
        return value;
    }

    applyTranslations() {
        const elements = document.querySelectorAll('[data-i18n]');
        elements.forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.translate(key);
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                el.placeholder = translation;
            } else {
                el.textContent = translation;
            }
        });
    }

    async setLanguage(lang) {
        await this.loadTranslations(lang);
        this.applyTranslations();
        // Also inform the backend if user is logged in
        if (window.api && window.api.getTokens().access) {
            try {
                await window.api.request('/accounts/me/language/', {
                    method: 'POST',
                    body: JSON.stringify({ language: lang })
                });
            } catch (e) {
                console.error('Failed to update language on backend', e);
            }
        }
    }
}

const i18n = new I18nManager();
window.i18n = i18n;

document.addEventListener('DOMContentLoaded', () => {
    i18n.init();
});
