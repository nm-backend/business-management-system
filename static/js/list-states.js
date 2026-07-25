window.listStates = {
    loading(element, message = null) {
        const msg = message || window.ui.t('common.loading');
        element.innerHTML = `<div class="list-state list-state-loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span>${msg}</span></div>`;
    },
    /** Skeleton-загрузка: плавные пульсирующие строки. */
    skeleton(element, rows = 5) {
        element.innerHTML = `<div class="skeleton-list" aria-hidden="true">${Array.from({ length: rows }).map(() => '<div class="skeleton-row"></div>').join('')}</div>`;
    },
    /** Пустое состояние: приветствие к действию, не просто «нет данных». */
    empty(element, message = null, actionHtml = '') {
        const fallbackMsg = window.ui.t('common.no_data');
        // Пробуем контекстные сообщения из data-атрибута контейнера
        const contextMsg = element.dataset?.emptyMessage || '';
        const msg = message || contextMsg || fallbackMsg;
        const action = actionHtml || (element.dataset?.emptyAction || '');
        element.innerHTML = `<div class="list-state list-state-empty" role="status">
            <span class="list-state-icon" aria-hidden="true" style="font-size:28px;opacity:.5;display:block;margin-bottom:4px;">—</span>
            <span style="font-weight:500;">${msg}</span>
            ${action ? `<span class="text-sm" style="margin-top:4px;color:var(--text-secondary)">${action}</span>` : ''}
        </div>`;
    },
    /** Ошибка загрузки: показываем кнопку повтора всегда. */
    error(element, message = null, retry) {
        const msg = message || window.ui.t('common.error_loading');
        const retryBtn = retry
            ? `<button type="button" class="btn btn-secondary btn-sm list-state-retry" style="margin-top:8px;width:auto;min-width:120px;">${window.ui.t('common.retry')}</button>`
            : '';
        element.innerHTML = `<div class="list-state list-state-error" role="alert">
            <span style="font-weight:500;">${msg}</span>
            ${retryBtn}
        </div>`;
        if (retry) {
            const btn = element.querySelector('.list-state-retry');
            if (btn) btn.addEventListener('click', retry);
        }
    },
    tableLoading(element, colspan, message = null) {
        const msg = message || window.ui.t('common.loading');
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span>${msg}</span></div></td></tr>`;
    },
    tableEmpty(element, colspan, message = null) {
        const msg = message || window.ui.t('common.no_data');
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-empty" role="status"><span style="opacity:.5">${msg}</span></div></td></tr>`;
    },
    tableError(element, colspan, message = null, retry) {
        const msg = message || window.ui.t('common.error_loading');
        const retryBtn = retry
            ? `<button type="button" class="btn btn-secondary btn-sm list-state-retry" style="margin-top:6px;min-width:100px;">${window.ui.t('common.retry')}</button>`
            : '';
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-error" role="alert">${msg}${retryBtn}</div></td></tr>`;
        if (retry) {
            const btn = element.querySelector('.list-state-retry');
            if (btn) btn.addEventListener('click', retry);
        }
    }
};
