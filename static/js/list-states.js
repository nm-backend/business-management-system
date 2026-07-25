window.listStates = {
    loading(element, message = null) {
        const msg = message || window.ui.t('common.loading');
        element.innerHTML = `<div class="list-state list-state-loading"><span class="spinner" aria-hidden="true"></span><span>${msg}</span></div>`;
    },
    /** Skeleton-загрузка: серые «пульсирующие» строки вместо спиннера. */
    skeleton(element, rows = 5) {
        element.innerHTML = `<div class="skeleton-list">${Array.from({ length: rows }).map(() => '<div class="skeleton-row"></div>').join('')}</div>`;
    },
    empty(element, message = null) {
        const msg = message || window.ui.t('common.no_data');
        element.innerHTML = `<div class="list-state list-state-empty"><span class="list-state-icon" aria-hidden="true">—</span><span>${msg}</span></div>`;
    },
    error(element, message = null, retry) {
        const msg = message || window.ui.t('common.error_loading');
        const retryBtn = retry ? `<button type="button" class="btn btn-secondary list-state-retry">${window.ui.t('common.retry')}</button>` : '';
        element.innerHTML = `<div class="list-state list-state-error"><span>${msg}</span>${retryBtn}</div>`;
        if (retry) element.querySelector('.list-state-retry').addEventListener('click', retry);
    },
    tableLoading(element, colspan, message = null) {
        const msg = message || window.ui.t('common.loading');
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-loading"><span class="spinner" aria-hidden="true"></span><span>${msg}</span></div></td></tr>`;
    },
    tableEmpty(element, colspan, message = null) {
        const msg = message || window.ui.t('common.no_data');
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-empty">${msg}</div></td></tr>`;
    },
    tableError(element, colspan, message = null, retry) {
        const msg = message || window.ui.t('common.error_loading');
        const retryBtn = retry ? `<button type="button" class="btn btn-secondary list-state-retry">${window.ui.t('common.retry')}</button>` : '';
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-error"><span>${msg}</span>${retryBtn}</div></td></tr>`;
        if (retry) element.querySelector('.list-state-retry').addEventListener('click', retry);
    }
};
