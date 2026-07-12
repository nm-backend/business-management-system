/**
 * I18nManager - менеджер переводов интерфейса.
 *
 * Загружает переводы с бэкенда и применяет к элементам с data-i18n.
 * Хранит текущий язык + узбекский как fallback (по ТЗ).
 */
class I18nManager {
    constructor() {
        this.translations = {};
        this.fallbackTranslations = {};
        this.fallbackLang = 'uz_cyrl';
        this.currentLang = localStorage.getItem('language') || 'uz_cyrl';
    }

    async init() {
        await this.loadTranslations(this.currentLang);
        if (this.currentLang !== this.fallbackLang) {
            await this.loadFallback();
        }
        this.applyTranslations();
    }

    async loadFallback() {
        try {
            const response = await fetch(`/api/v1/core/locale/${this.fallbackLang}/`);
            if (response.ok) {
                this.fallbackTranslations = await response.json();
            }
        } catch (error) {
            console.error('Error loading fallback translations', error);
        }
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

    lookup(dict, key) {
        const keys = key.split('.');
        let value = dict;
        for (const k of keys) {
            if (value && Object.prototype.hasOwnProperty.call(value, k)) {
                value = value[k];
            } else {
                return undefined;
            }
        }
        return value;
    }

    translate(key) {
        let value = this.lookup(this.translations, key);
        if (value === undefined) {
            value = this.lookup(this.fallbackTranslations, key); // fallback на uz_cyrl
        }
        return value !== undefined ? value : key;
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
        if (this.currentLang !== this.fallbackLang && Object.keys(this.fallbackTranslations).length === 0) {
            await this.loadFallback();
        }
        this.applyTranslations();
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