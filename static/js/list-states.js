window.listStates = {
    loading(element, message = 'Loading...') {
        element.innerHTML = `<div class="list-state list-state-loading"><span class="spinner" aria-hidden="true"></span><span>${message}</span></div>`;
    },
    empty(element, message = 'No records found') {
        element.innerHTML = `<div class="list-state list-state-empty"><span class="list-state-icon" aria-hidden="true">—</span><span>${message}</span></div>`;
    },
    error(element, message = 'Unable to load records', retry) {
        element.innerHTML = `<div class="list-state list-state-error"><span>${message}</span>${retry ? '<button type="button" class="btn btn-secondary list-state-retry">Retry</button>' : ''}</div>`;
        if (retry) element.querySelector('.list-state-retry').addEventListener('click', retry);
    },
    tableLoading(element, colspan, message = 'Loading...') {
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-loading"><span class="spinner" aria-hidden="true"></span><span>${message}</span></div></td></tr>`;
    },
    tableEmpty(element, colspan, message = 'No records found') {
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-empty">${message}</div></td></tr>`;
    },
    tableError(element, colspan, message = 'Unable to load records', retry) {
        element.innerHTML = `<tr><td colspan="${colspan}"><div class="list-state list-state-error"><span>${message}</span>${retry ? '<button type="button" class="btn btn-secondary list-state-retry">Retry</button>' : ''}</div></td></tr>`;
        if (retry) element.querySelector('.list-state-retry').addEventListener('click', retry);
    }
};
