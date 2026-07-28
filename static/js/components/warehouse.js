/**
 * Склад сырья: список с поиском, низкие остатки красным,
 * добавление/редактирование (owner/admin), закупочные цены видит только owner.
 */
class WarehouseComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'warehouse.title');
        this.search = '';
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;

        // Архив видит только владелец: API отдаёт архивные позиции лишь ему,
        // у остальных вкладка была бы всегда пустой.
        this.tab = 'active';
        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn active" data-i18n="warehouse.title"></button>
                <button class="tab-btn" id="tab-products" data-i18n="warehouse.finished_title"></button>
            </div>
            <div class="tabs" id="warehouse-subtabs">
                <button class="tab-btn active" data-wtab="active" data-i18n="common.active"></button>
                ${user.is_owner ? `<button class="tab-btn" data-wtab="archive" data-i18n="common.archive"></button>` : ''}
                ${canEdit ? `<button class="tab-btn" data-wtab="history" data-i18n="warehouse.stock_movement"></button>` : ''}
            </div>
            <div class="search-box" style="display:flex;gap:8px;align-items:center;">
                <div style="position:relative;flex:1;">
                    <span class="search-icon">🔍</span>
                    <input type="text" id="material-search" class="form-control" data-i18n="warehouse.search">
                </div>
                <button class="btn btn-secondary" id="scan-barcode-btn" type="button" title="Scan Barcode" style="padding:8px 12px;font-size:18px;">📷</button>
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-material-btn" style="margin-bottom:12px;margin-top:10px;" data-i18n="warehouse.add_material"></button>` : ''}
            <div class="list-group" id="materials-list"></div>
        `;

        container.querySelector('#tab-products').addEventListener('click', () => window.router.navigate('/finished-products'));

        container.querySelectorAll('[data-wtab]').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('[data-wtab]').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.tab = btn.dataset.wtab;
                // Поиск и «добавить» относятся к списку материалов, в истории они лишние.
                const isHistory = this.tab === 'history';
                container.querySelector('.search-box').style.display = isHistory ? 'none' : '';
                const addBtn = container.querySelector('#add-material-btn');
                if (addBtn) addBtn.style.display = isHistory || this.tab === 'archive' ? 'none' : '';
                if (isHistory) this.loadHistory();
                else this.loadMaterials();
            });
        });

        const searchInput = container.querySelector('#material-search');
        let timer;
        searchInput.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                this.search = searchInput.value;
                this.loadMaterials();
            }, 300);
        });

        if (canEdit) {
            container.querySelector('#add-material-btn').addEventListener('click', () => this.openForm());
        }

        const scanBtn = container.querySelector('#scan-barcode-btn');
        if (scanBtn) {
            scanBtn.addEventListener('click', () => this.openBarcodeScanner());
        }

        window.i18n.applyTranslations();
        await this.loadMaterials();
    }

    /** Модальное окно сканера штрихкодов / QR-кодов (по макетам) */
    openBarcodeScanner() {
        const modal = window.ui.modal('warehouse.scan_barcode', `
            <div class="scanner-modal" style="text-align:center;padding:10px 0;">
                <div class="scanner-box" style="position:relative;width:100%;max-width:280px;height:200px;margin:0 auto 15px;background:#0f172a;border-radius:12px;overflow:hidden;display:flex;align-items:center;justify-content:center;border:2px solid var(--primary);">
                    <div style="position:absolute;top:0;left:0;right:0;bottom:0;border:2px dashed rgba(255,255,255,0.4);margin:20px;border-radius:8px;"></div>
                    <div style="position:absolute;width:80%;height:2px;background:#e5484d;box-shadow:0 0 8px #e5484d;animation:scan 2s infinite;"></div>
                    <span style="font-size:32px;">📷</span>
                </div>
                <p class="text-sm text-muted" data-i18n="warehouse.scan_hint"></p>
                <div style="display:flex;gap:10px;justify-content:center;margin-top:15px;">
                    <button class="btn btn-secondary text-sm" type="button">🔦 <span data-i18n="warehouse.flashlight"></span></button>
                    <button class="btn btn-secondary text-sm" type="button">🖼️ <span data-i18n="warehouse.gallery"></span></button>
                </div>
            </div>
            <style>
                @keyframes scan { 0%{top:20%;} 50%{top:80%;} 100%{top:20%;} }
            </style>
        `);
    }

    async loadMaterials() {
        const listEl = document.getElementById('materials-list');
        window.listStates.skeleton(listEl);
        try {
            let query = `?is_archived=${this.tab === 'archive'}`;
            if (this.search) query += `&search=${encodeURIComponent(this.search)}`;
            const response = await window.api.request(`/warehouse/raw-materials/${query}`);
            const materials = response.results || response;

            if (!materials.length) {
                window.listStates.empty(listEl, window.ui.t('common.no_data'));
                return;
            }
            listEl.innerHTML = materials.map((m) => this.renderRow(m)).join('');
            listEl.querySelectorAll('[data-id]').forEach((row) => {
                row.addEventListener('click', () => {
                    const material = materials.find((m) => m.id === Number(row.dataset.id));
                    this.openDetail(material);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadMaterials());
        }
    }

    renderRow(m) {
        return `
            <div class="list-row" data-id="${m.id}">
                <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                    <div class="thumb">${m.photo ? `<img src="${m.photo}" alt="">` : '🪨'}</div>
                    <div style="min-width:0;">
                        <div style="font-size:14px;font-weight:600;">${window.ui.escape(m.name)}</div>
                        <div class="text-sm text-muted">${window.ui.escape([m.stone_type, m.size].filter(Boolean).join(' · ') || '-')}</div>
                    </div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <div style="font-size:15px;font-weight:600;" class="${m.is_low_stock ? 'text-danger' : ''}">
                        ${window.ui.qty(m.quantity)} <span data-i18n="units.${m.unit}"></span>
                    </div>
                    ${m.is_low_stock ? `<div class="text-sm text-danger" data-i18n="warehouse.low_stock_warning"></div>` : ''}
                </div>
            </div>`;
    }

    openDetail(m) {
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;
        const modal = window.ui.modal('warehouse.title', `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                <div class="thumb" style="width:56px;height:56px;">${m.photo ? `<img src="${m.photo}" alt="">` : '🪨'}</div>
                <div>
                    <div style="font-weight:600;font-size:16px;">${window.ui.escape(m.name)}</div>
                    <div class="text-sm text-muted">${window.ui.escape(m.stone_type || '')}</div>
                </div>
            </div>
            <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;">
                ${this.detailRow('warehouse.quantity', `${window.ui.qty(m.quantity)} ${window.ui.t('units.' + m.unit)}`, m.is_low_stock)}
                ${this.detailRow('warehouse.min_stock', window.ui.qty(m.min_stock))}
                ${this.detailRow('warehouse.color', m.color)}
                ${this.detailRow('warehouse.size', m.size)}
                ${this.detailRow('warehouse.thickness', m.thickness)}
                ${this.detailRow('warehouse.storage_location', m.storage_location)}
                ${this.detailRow('warehouse.supplier', m.supplier)}
                ${this.detailRow('warehouse.arrival_date', m.arrival_date ? window.ui.date(m.arrival_date) : '')}
                ${user.is_owner ? this.detailRow('warehouse.purchase_price', window.ui.money(m.purchase_price)) : ''}
                ${user.is_owner ? this.detailRow('warehouse.avg_cost', window.ui.money(m.avg_cost_price)) : ''}
                ${this.detailRow('warehouse.comment', m.comment)}
            </div>
            ${canEdit ? `
                <div style="display:flex;gap:10px;margin-top:14px;">
                    <button class="btn btn-secondary btn-sm" id="edit-material" style="flex:1;" data-i18n="common.edit"></button>
                    ${m.is_archived ? '' : `<button class="btn btn-success btn-sm" id="income-material" style="flex:1;" data-i18n="warehouse.incoming"></button>`}
                </div>
                ${user.is_owner ? `
                    <button class="btn btn-secondary btn-sm btn-block" id="archive-material" style="margin-top:10px;"
                        data-i18n="${m.is_archived ? 'common.restore' : 'common.archive'}"></button>` : ''}` : ''}
        `);

        if (canEdit) {
            modal.querySelector('#edit-material').addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openForm(m);
            });
            modal.querySelector('#income-material')?.addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openIncomeForm(m);
            });
            modal.querySelector('#archive-material')?.addEventListener('click', async () => {
                if (!m.is_archived && !(await window.confirmation.confirm(
                    window.ui.t('common.archive_confirm'), window.ui.t('common.archive')))) return;
                try {
                    await window.api.request(
                        `/warehouse/raw-materials/${m.id}/${m.is_archived ? 'restore' : 'archive'}/`,
                        { method: 'POST' },
                    );
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadMaterials();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        }
    }

    /** История движения склада: приходы, расходы, производство. */
    async loadHistory() {
        const listEl = document.getElementById('materials-list');
        window.listStates.skeleton(listEl);
        try {
            const response = await window.api.request('/warehouse/stock-movements/?page_size=50');
            const rows = response.results || response;
            if (!rows.length) {
                window.listStates.empty(listEl, window.ui.t('common.no_data'));
                return;
            }
            const sign = (type) => (['outgoing', 'production_out', 'loss'].includes(type) ? '−' : '+');
            const colour = (type) => (['outgoing', 'production_out', 'loss'].includes(type) ? 'text-danger' : 'text-success');
            listEl.innerHTML = rows.map((r) => `
                <div class="list-row" style="cursor:default;">
                    <div style="min-width:0;">
                        <div style="font-size:14px;font-weight:600;">
                            ${window.ui.escape(r.material_name || r.product_name || '-')}
                        </div>
                        <div class="text-sm text-muted">
                            ${window.ui.escape(r.movement_type_display || r.movement_type)}
                            · ${window.ui.datetime(r.created_at)}
                            ${r.created_by_name ? ` · ${window.ui.escape(r.created_by_name)}` : ''}
                        </div>
                    </div>
                    <div style="text-align:right;flex-shrink:0;">
                        <div style="font-size:15px;font-weight:600;" class="${colour(r.movement_type)}">
                            ${sign(r.movement_type)}${window.ui.qty(r.quantity)}
                            ${r.unit ? `<span data-i18n="units.${r.unit}"></span>` : ''}
                        </div>
                    </div>
                </div>`).join('');
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadHistory());
        }
    }

    detailRow(labelKey, value, danger = false) {
        if (!value) return '';
        return `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold ${danger ? 'text-danger' : ''}" style="text-align:right;">${window.ui.escape(String(value))}</span>
            </div>`;
    }

    /** Форма создания/редактирования материала. */
    openForm(m = null) {
        const isOwner = window.currentUser.is_owner;
        const modal = window.ui.modal(m ? 'common.edit' : 'warehouse.add_material', `
            <form id="material-form">
                <div class="form-group"><label data-i18n="warehouse.name"></label>
                    <input name="name" class="form-control" required value="${window.ui.escape(m?.name || '')}"></div>
                <div class="form-group"><label data-i18n="warehouse.stone_type"></label>
                    <input name="stone_type" class="form-control" value="${window.ui.escape(m?.stone_type || '')}"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="warehouse.color"></label>
                        <input name="color" class="form-control" value="${window.ui.escape(m?.color || '')}"></div>
                    <div class="form-group"><label data-i18n="warehouse.size"></label>
                        <input name="size" class="form-control" value="${window.ui.escape(m?.size || '')}"></div>
                    <div class="form-group"><label data-i18n="warehouse.thickness"></label>
                        <input name="thickness" class="form-control" value="${window.ui.escape(m?.thickness || '')}"></div>
                    <div class="form-group"><label data-i18n="warehouse.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions(m?.unit || 'sht')}</select></div>
                    <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                        <input name="quantity" type="number" step="0.001" min="0" class="form-control" required value="${m?.quantity ?? ''}"></div>
                    <div class="form-group"><label data-i18n="warehouse.min_stock"></label>
                        <input name="min_stock" type="number" step="0.001" min="0" class="form-control" value="${m?.min_stock ?? 0}"></div>
                </div>
                <div class="form-group"><label data-i18n="warehouse.storage_location"></label>
                    <input name="storage_location" class="form-control" value="${window.ui.escape(m?.storage_location || '')}"></div>
                <div class="form-group"><label data-i18n="warehouse.supplier"></label>
                    <input name="supplier" class="form-control" value="${window.ui.escape(m?.supplier || '')}"></div>
                <div class="form-group"><label data-i18n="warehouse.arrival_date"></label>
                    <input name="arrival_date" type="date" class="form-control" value="${m?.arrival_date || ''}"></div>
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="warehouse.purchase_price"></label>
                        <input name="purchase_price" type="number" step="0.01" min="0" class="form-control" value="${m?.purchase_price ?? 0}"></div>` : ''}
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2">${window.ui.escape(m?.comment || '')}</textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#material-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            if (!data.arrival_date) delete data.arrival_date;
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (m) {
                        await window.api.request(`/warehouse/raw-materials/${m.id}/`, {
                            method: 'PATCH', body: JSON.stringify(data),
                        });
                    } else {
                        await window.api.request('/warehouse/raw-materials/', {
                            method: 'POST', body: JSON.stringify(data),
                        });
                    }
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadMaterials();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    /** Приход материала: добавляет количество к остатку. */
    /**
     * Приход сырья.
     *
     * Раньше страница считала новый остаток сама и слала PATCH с абсолютным
     * значением: два прихода со страницы, открытой до первого из них, затирали
     * друг друга. Теперь прибавляет сервер (POST .../incoming/), он же пишет
     * движение в историю и пересчитывает среднюю себестоимость.
     */
    openIncomeForm(m) {
        const isOwner = window.currentUser.is_owner;
        const today = new Date().toISOString().slice(0, 10);
        const modal = window.ui.modal('warehouse.incoming', `
            <p style="margin-bottom:12px;font-weight:600;">${window.ui.escape(m.name)}</p>
            <form id="income-form">
                <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                    <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required></div>
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="warehouse.purchase_price"></label>
                        <input name="price_per_unit" type="number" step="0.01" min="0" class="form-control"></div>` : ''}
                <div class="form-group"><label data-i18n="warehouse.arrival_date"></label>
                    <input name="arrival_date" type="date" class="form-control" value="${today}" max="${today}"></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="reason" class="form-control"></div>
                <button type="submit" class="btn btn-success btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#income-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            Object.keys(data).forEach((k) => { if (data[k] === '') delete data[k]; });
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/warehouse/raw-materials/${m.id}/incoming/`, {
                        method: 'POST',
                        body: JSON.stringify(data),
                    });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadMaterials();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

}

window.WarehouseComponent = new WarehouseComponent();
