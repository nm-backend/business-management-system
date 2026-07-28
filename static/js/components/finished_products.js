/**
 * Готовая продукция: список с резервами, низкие остатки красным,
 * добавление/редактирование (owner/admin), цены видит только owner.
 */
class FinishedProductsComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'warehouse.finished_title');
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;

        // Архив отдаётся API только владельцу — у остальных вкладка была бы пуста.
        this.tab = 'active';
        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn" id="tab-materials" data-i18n="warehouse.title"></button>
                <button class="tab-btn active" data-i18n="warehouse.finished_title"></button>
            </div>
            ${user.is_owner ? `
                <div class="tabs" id="product-subtabs">
                    <button class="tab-btn active" data-ptab="active" data-i18n="common.active"></button>
                    <button class="tab-btn" data-ptab="archive" data-i18n="common.archive"></button>
                </div>` : ''}
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" id="product-search" class="form-control" data-i18n="warehouse.search">
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-product-btn" style="margin-bottom:12px;" data-i18n="warehouse.add_product"></button>` : ''}
            <div class="list-group" id="products-list"></div>
        `;

        container.querySelector('#tab-materials').addEventListener('click', () => window.router.navigate('/warehouse'));

        container.querySelectorAll('[data-ptab]').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('[data-ptab]').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.tab = btn.dataset.ptab;
                const addBtn = container.querySelector('#add-product-btn');
                if (addBtn) addBtn.style.display = this.tab === 'archive' ? 'none' : '';
                this.loadProducts();
            });
        });

        const searchInput = container.querySelector('#product-search');
        let timer;
        searchInput.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                this.search = searchInput.value;
                this.loadProducts();
            }, 300);
        });

        if (canEdit) {
            container.querySelector('#add-product-btn').addEventListener('click', () => this.openForm());
        }

        window.i18n.applyTranslations();
        this.search = '';
        await this.loadProducts();
    }

    async loadProducts() {
        const listEl = document.getElementById('products-list');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(listEl)) return;
        window.listStates.skeleton(listEl);
        try {
            let query = `?is_archived=${this.tab === 'archive'}`;
            if (this.search) query += `&search=${encodeURIComponent(this.search)}`;
            const response = await window.api.request(`/warehouse/finished-products/${query}`);
            const products = response.results || response;

            if (!products.length) {
                window.listStates.empty(listEl, window.ui.t('common.no_data'));
                return;
            }
            listEl.innerHTML = products.map((p) => `
                <div class="list-row" data-id="${p.id}">
                    <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                        <div class="thumb">${p.photo ? `<img src="${p.photo}" alt="">` : '🪟'}</div>
                        <div style="min-width:0;">
                            <div style="font-size:14px;font-weight:600;">${window.ui.escape(p.name)}</div>
                            <div class="text-sm text-muted">
                                ${window.ui.escape(p.category || '-')} ·
                                <span data-i18n="warehouse.reserved"></span>: ${window.ui.qty(p.reserved_for_orders)}
                            </div>
                        </div>
                    </div>
                    <div style="text-align:right;flex-shrink:0;">
                        <div style="font-size:15px;font-weight:600;" class="${p.is_low_stock ? 'text-danger' : ''}">
                            ${window.ui.qty(p.available_quantity)} <span data-i18n="units.${p.unit}"></span>
                        </div>
                        ${p.is_low_stock ? `<div class="text-sm text-danger" data-i18n="warehouse.low_stock_warning"></div>` : ''}
                    </div>
                </div>`).join('');

            listEl.querySelectorAll('[data-id]').forEach((row) => {
                row.addEventListener('click', () => {
                    const product = products.find((p) => p.id === Number(row.dataset.id));
                    this.openDetail(product);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadProducts());
        }
    }

    openDetail(p) {
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;
        const row = (labelKey, value, danger = false) => (!value ? '' : `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold ${danger ? 'text-danger' : ''}">${window.ui.escape(String(value))}</span>
            </div>`);

        const modal = window.ui.modal('warehouse.finished_title', `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                <div class="thumb" style="width:56px;height:56px;">${p.photo ? `<img src="${p.photo}" alt="">` : '🪟'}</div>
                <div>
                    <div style="font-weight:600;font-size:16px;">${window.ui.escape(p.name)}</div>
                    <div class="text-sm text-muted">${window.ui.escape(p.category || '')}</div>
                </div>
            </div>
            <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;">
                ${row('warehouse.quantity', `${window.ui.qty(p.quantity)} ${window.ui.t('units.' + p.unit)}`, p.is_low_stock)}
                ${row('warehouse.reserved', window.ui.qty(p.reserved_for_orders))}
                ${row('warehouse.min_stock', window.ui.qty(p.min_stock))}
                ${user.is_owner ? row('warehouse.cost_price', window.ui.money(p.cost_price)) : ''}
                ${user.is_owner ? row('warehouse.sale_price', window.ui.money(p.sale_price)) : ''}
                ${row('warehouse.description', p.description)}
            </div>
            ${canEdit ? `
                <div style="display:flex;gap:10px;margin-top:14px;">
                    <button class="btn btn-secondary btn-sm" id="edit-product" style="flex:1;" data-i18n="common.edit"></button>
                    ${p.is_archived ? '' : `<button class="btn btn-success btn-sm" id="income-product" style="flex:1;" data-i18n="warehouse.incoming"></button>`}
                </div>
                ${user.is_owner ? `
                    <button class="btn btn-secondary btn-sm btn-block" id="archive-product" style="margin-top:10px;"
                        data-i18n="${p.is_archived ? 'common.restore' : 'common.archive'}"></button>` : ''}` : ''}
        `);

        if (canEdit) {
            modal.querySelector('#edit-product').addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openForm(p);
            });
            modal.querySelector('#income-product')?.addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openIncomeForm(p);
            });
            modal.querySelector('#archive-product')?.addEventListener('click', async () => {
                if (!p.is_archived && !(await window.confirmation.confirm(
                    window.ui.t('common.archive_confirm'), window.ui.t('common.archive')))) return;
                try {
                    await window.api.request(
                        `/warehouse/finished-products/${p.id}/${p.is_archived ? 'restore' : 'archive'}/`,
                        { method: 'POST' },
                    );
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadProducts();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        }
    }

    /**
     * Приход готовой продукции.
     *
     * Раньше остаток товара мог вырасти только через подтверждённое
     * производство: купленный или возвращённый товар оприходовать было нечем,
     * оставалось перезаписывать количество в форме руками.
     */
    openIncomeForm(p) {
        const isOwner = window.currentUser.is_owner;
        const modal = window.ui.modal('warehouse.incoming', `
            <p style="margin-bottom:12px;font-weight:600;">${window.ui.escape(p.name)}</p>
            <form id="product-income-form">
                <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                    <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required></div>
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="warehouse.cost_price"></label>
                        <input name="price_per_unit" type="number" step="0.01" min="0" class="form-control"></div>` : ''}
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="reason" class="form-control"></div>
                <button type="submit" class="btn btn-success btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#product-income-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            Object.keys(data).forEach((k) => { if (data[k] === '') delete data[k]; });
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/warehouse/finished-products/${p.id}/incoming/`, {
                        method: 'POST',
                        body: JSON.stringify(data),
                    });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadProducts();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    openForm(p = null) {
        const isOwner = window.currentUser.is_owner;
        const modal = window.ui.modal(p ? 'common.edit' : 'warehouse.add_product', `
            <form id="product-form">
                <div class="form-group"><label data-i18n="warehouse.name"></label>
                    <input name="name" class="form-control" required value="${window.ui.escape(p?.name || '')}"></div>
                <div class="form-group"><label data-i18n="warehouse.category"></label>
                    <input name="category" class="form-control" value="${window.ui.escape(p?.category || '')}"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="warehouse.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions(p?.unit || 'izdelie')}</select></div>
                    <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                        <input name="quantity" type="number" step="0.001" min="0" class="form-control" required value="${p?.quantity ?? ''}"></div>
                    <div class="form-group"><label data-i18n="warehouse.min_stock"></label>
                        <input name="min_stock" type="number" step="0.001" min="0" class="form-control" value="${p?.min_stock ?? 0}"></div>
                    <div class="form-group"><label data-i18n="warehouse.reserved"></label>
                        <input name="reserved_for_orders" type="number" step="0.001" min="0" class="form-control" value="${p?.reserved_for_orders ?? 0}"></div>
                </div>
                ${isOwner ? `
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                        <div class="form-group"><label data-i18n="warehouse.cost_price"></label>
                            <input name="cost_price" type="number" step="0.01" min="0" class="form-control" value="${p?.cost_price ?? 0}"></div>
                        <div class="form-group"><label data-i18n="warehouse.sale_price"></label>
                            <input name="sale_price" type="number" step="0.01" min="0" class="form-control" value="${p?.sale_price ?? 0}"></div>
                    </div>` : ''}
                <div class="form-group"><label data-i18n="warehouse.description"></label>
                    <textarea name="description" class="form-control" rows="2">${window.ui.escape(p?.description || '')}</textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#product-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (p) {
                        await window.api.request(`/warehouse/finished-products/${p.id}/`, {
                            method: 'PATCH', body: JSON.stringify(data),
                        });
                    } else {
                        await window.api.request('/warehouse/finished-products/', {
                            method: 'POST', body: JSON.stringify(data),
                        });
                    }
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadProducts();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.FinishedProductsComponent = new FinishedProductsComponent();
