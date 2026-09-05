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
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="warehouse.title"></div>
                    <h2>${window.ui.t('warehouse.title')}</h2>
                </div>
            </div>
            <div class="tabs" role="tablist" aria-label="Warehouse sections">
                <button class="tab-btn active" role="tab" aria-selected="true" id="tab-materials" data-i18n="warehouse.title"></button>
                <button class="tab-btn" role="tab" aria-selected="false" id="tab-products" data-i18n="warehouse.finished_title"></button>
            </div>
            <div class="tabs" id="warehouse-subtabs" role="tablist" aria-label="Warehouse filters">
                <button class="tab-btn active" role="tab" aria-selected="true" data-wtab="active" data-i18n="common.active"></button>
                ${user.is_owner ? `<button class="tab-btn" role="tab" aria-selected="false" data-wtab="archive" data-i18n="common.archive"></button>` : ''}
                ${canEdit ? `<button class="tab-btn" role="tab" aria-selected="false" data-wtab="history" data-i18n="warehouse.stock_movement"></button>` : ''}
            </div>
            <div class="warehouse-summary" id="warehouse-summary" style="display:none;gap:10px;margin-bottom:10px;">
                <div class="card" style="flex:1;margin:0;">
                    <div class="text-sm text-muted" data-i18n="warehouse.summary_total"></div>
                    <div class="font-bold" id="summary-total"></div>
                </div>
                ${user.is_owner ? `
                <div class="card" style="flex:1;margin:0;">
                    <div class="text-sm text-muted" data-i18n="warehouse.summary_value"></div>
                    <div class="font-bold" id="summary-value"></div>
                </div>` : ''}
            </div>
            <div class="search-box search-box--with-action">
                <div class="search-field">
                    <span class="search-icon" aria-hidden="true">🔍</span>
                    <input type="text" id="material-search" class="form-control" data-i18n-attr="placeholder,aria-label" data-i18n="warehouse.search">
                </div>
                <button class="btn btn-secondary" id="scan-barcode-btn" type="button" data-i18n-attr="aria-label" data-i18n="warehouse.scan_barcode"
                        style="padding:8px 12px;font-size:18px;">📷</button>
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-material-btn" style="margin-bottom:12px;margin-top:10px;" data-i18n="warehouse.add_material"></button>` : ''}
            <div class="list-group" id="materials-list"></div>
        `;

        container.querySelector('#tab-products').addEventListener('click', () => window.router.navigate('/finished-products'));

        // «Хом ашё омбори» — возврат к списку материалов из любой подвкладки.
        // Раньше кнопка не имела обработчика: после «Омбор ҳаракати» она
        // выглядела активной, но клик ничего не делал, и материалы приходилось
        // возвращать кнопкой «Фаол».
        // Подсветка главных вкладок («Хом ашё омбори» / «Тайёр маҳсулот»)
        // должна соответствовать контенту: при «Омбор ҳаракати»/«Архивга»
        // «Хом ашё омбори» не должен оставаться подсвеченным.
        const setMaterialsTabActive = (active) => {
            container.querySelector('#tab-materials').classList.toggle('active', active);
        };
        const showMaterials = () => {
            container.querySelectorAll('[data-wtab]').forEach((b) => {
                const active = b.dataset.wtab === 'active';
                b.classList.toggle('active', active);
                b.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            setMaterialsTabActive(true);
            container.querySelector('#tab-materials')?.setAttribute('aria-selected', 'true');
            container.querySelector('#tab-products')?.setAttribute('aria-selected', 'false');
            this.tab = 'active';
            container.querySelector('.search-box').style.display = '';
            const addBtn = container.querySelector('#add-material-btn');
            if (addBtn) addBtn.style.display = '';
            this.loadMaterials();
        };
        container.querySelector('#tab-materials').addEventListener('click', () => showMaterials());

        container.querySelectorAll('[data-wtab]').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('[data-wtab]').forEach((b) => {
                    const active = b === btn;
                    b.classList.toggle('active', active);
                    b.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                this.tab = btn.dataset.wtab;
                setMaterialsTabActive(this.tab === 'active');
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
        searchInput.addEventListener('input', window.ui.debounce(() => {
            this.search = searchInput.value;
            this.loadMaterials();
        }, 300));

        if (canEdit) {
            container.querySelector('#add-material-btn').addEventListener('click', () => this.openForm());
        }

        const scanBtn = container.querySelector('#scan-barcode-btn');
        if (scanBtn) {
            scanBtn.addEventListener('click', () => this.openBarcodeScanner());
        }

        window.i18n.applyTranslations();
        await this.loadMaterials();
        this.loadSummary();
    }

    /** Итоговые показатели склада: общий остаток и стоимость (для owner). */
    async loadSummary() {
        const wrap = document.getElementById('warehouse-summary');
        if (!wrap || window.listStates.gone(wrap)) return;
        try {
            const data = await window.api.request('/warehouse/raw-materials/summary/');
            const totalEl = document.getElementById('summary-total');
            if (totalEl) totalEl.textContent = window.ui.qty(data.total_quantity);
            const valueEl = document.getElementById('summary-value');
            if (valueEl) valueEl.textContent = window.ui.money(data.total_value ?? 0);
            wrap.style.display = 'flex';
        } catch (e) {
            /* итоги некритичны */
        }
    }

    /**
     * Сканер штрихкодов и QR-кодов.
     *
     * Раньше это был макет: тёмный прямоугольник с эмодзи и анимацией, а обе
     * кнопки — «Фонарик» и «Галерея» — не имели ни одного обработчика. Нажатие
     * не делало ничего (подтверждено пользователем).
     *
     * Теперь окно показывает живое изображение с камеры и распознаёт код через
     * встроенный в браузер BarcodeDetector (Chrome/Android). Где его нет
     * (Safari) — предлагается ввести код вручную. Найденный код уходит в поиск
     * по складу.
     */
    openBarcodeScanner() {
        const t = (k) => window.ui.t(k);
        const modal = window.ui.modal('warehouse.scan_barcode', `
            <div class="scanner-modal" style="text-align:center;padding:10px 0;">
                <div class="scanner-box" id="scanner-box" style="position:relative;width:100%;max-width:280px;height:200px;margin:0 auto 15px;background:#0f172a;border-radius:12px;overflow:hidden;display:flex;align-items:center;justify-content:center;border:2px solid var(--primary);">
                    <video id="scanner-video" playsinline muted style="display:none;"></video>
                    <div style="position:absolute;top:0;left:0;right:0;bottom:0;border:2px dashed rgba(255,255,255,0.4);margin:20px;border-radius:8px;pointer-events:none;"></div>
                    <span id="scanner-placeholder" style="font-size:32px;">📷</span>
                </div>
                <p class="text-sm text-muted" data-i18n="warehouse.scan_hint"></p>
                <p class="text-sm scanner-status" id="scanner-status"></p>
                <div style="display:flex;gap:10px;justify-content:center;margin-top:15px;">
                    <button class="btn btn-secondary btn-sm" type="button" id="scanner-torch">🔦 <span data-i18n="warehouse.flashlight"></span></button>
                    <button class="btn btn-secondary btn-sm" type="button" id="scanner-gallery">🖼️ <span data-i18n="warehouse.gallery"></span></button>
                </div>
                <input type="file" id="scanner-file" accept="image/*" style="display:none;">
                <form id="scanner-manual" style="display:flex;gap:8px;margin-top:14px;">
                    <input name="code" class="form-control" data-i18n-attr="placeholder,aria-label" data-i18n="warehouse.scan_manual" style="flex:1 1 auto;min-width:0;">
                    <button type="submit" class="btn btn-primary btn-sm" style="flex:0 0 auto;" data-i18n="common.search"></button>
                </form>
            </div>
        `);

        const video = modal.querySelector('#scanner-video');
        const placeholder = modal.querySelector('#scanner-placeholder');
        const status = modal.querySelector('#scanner-status');
        const torchBtn = modal.querySelector('#scanner-torch');
        const fileInput = modal.querySelector('#scanner-file');
        const say = (text, danger = false) => {
            status.textContent = text;
            status.className = `text-sm scanner-status ${danger ? 'text-danger' : 'text-muted'}`;
        };

        let stream = null;
        let track = null;
        let stopped = false;
        const detector = 'BarcodeDetector' in window ? new window.BarcodeDetector() : null;

        const stop = () => {
            stopped = true;
            if (stream) stream.getTracks().forEach((s) => s.stop());
            stream = null;
            track = null;
        };
        // Камеру надо гасить при любом способе закрытия окна (крестик, фон,
        // Escape, «Назад»), поэтому следим за исчезновением окна из DOM.
        const watcher = new MutationObserver(() => {
            if (!modal.isConnected) { stop(); watcher.disconnect(); }
        });
        watcher.observe(document.body, { childList: true });

        const found = (code) => {
            stop();
            const input = document.querySelector('#material-search');
            window.ui.closeModal(modal);
            if (input) {
                input.value = code;
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
            window.toast.success(code);
        };

        const scanLoop = async () => {
            if (stopped || !detector) return;
            try {
                const codes = await detector.detect(video);
                if (codes && codes.length && codes[0].rawValue) return found(codes[0].rawValue);
            } catch (e) { /* кадр не разобран — пробуем следующий */ }
            if (!stopped) setTimeout(scanLoop, 400);
        };

        (async () => {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                say(t('warehouse.scan_no_camera'), true);
                return;
            }
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: { ideal: 'environment' } },
                });
                if (stopped) { stop(); return; }
                track = stream.getVideoTracks()[0];
                video.srcObject = stream;
                video.style.display = 'block';
                placeholder.style.display = 'none';
                await video.play();
                // Фонарик есть далеко не у всех камер — кнопку прячем, чтобы не
                // повторять историю с нажатием «в никуда».
                const torchSupported = !!(track.getCapabilities && track.getCapabilities().torch);
                if (!torchSupported) torchBtn.style.display = 'none';
                say(detector ? t('warehouse.scan_hint') : t('warehouse.scan_no_detector'), !detector);
                scanLoop();
            } catch (e) {
                // Камеры нет — фонарику светить нечем, кнопку убираем, чтобы
                // она не осталась нажимаемой «в никуда».
                torchBtn.style.display = 'none';
                say(t('warehouse.scan_no_camera'), true);
            }
        })();

        let torchOn = false;
        torchBtn.addEventListener('click', async () => {
            if (!track) return;
            try {
                torchOn = !torchOn;
                await track.applyConstraints({ advanced: [{ torch: torchOn }] });
                torchBtn.classList.toggle('btn-primary', torchOn);
            } catch (e) {
                say(t('warehouse.scan_no_torch'), true);
            }
        });

        // Ручной ввод — единственный рабочий путь там, где браузер не умеет
        // распознавать коды (Windows-версия Chrome, Safari): обещание «введите
        // код вручную» должно быть чем-то подкреплено.
        modal.querySelector('#scanner-manual').addEventListener('submit', (e) => {
            e.preventDefault();
            const code = new FormData(e.target).get('code').trim();
            if (code) found(code);
        });

        modal.querySelector('#scanner-gallery').addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) return;
            if (!detector) { say(t('warehouse.scan_no_detector'), true); return; }
            try {
                const bitmap = await createImageBitmap(file);
                const codes = await detector.detect(bitmap);
                bitmap.close();
                if (codes && codes.length && codes[0].rawValue) found(codes[0].rawValue);
                else say(t('warehouse.scan_not_found'), true);
            } catch (e) {
                say(t('warehouse.scan_not_found'), true);
            }
        });
    }

    async loadMaterials() {
        const listEl = document.getElementById('materials-list');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(listEl)) return;
        window.listStates.skeleton(listEl);
        try {
            let query = `?is_archived=${this.tab === 'archive'}`;
            if (this.search) query += `&search=${encodeURIComponent(this.search)}`;
            const response = await window.api.request(`/warehouse/raw-materials/${query}`);
            const materials = response.results || response;

            if (!materials.length) {
                const canEdit = window.currentUser?.is_owner || window.currentUser?.is_admin;
                const cta = canEdit ? `<button type="button" class="btn btn-primary btn-sm" id="empty-add-material" data-i18n="warehouse.add_material"></button>` : '';
                window.listStates.empty(listEl, window.ui.t('common.no_data'), cta);
                const btn = listEl.querySelector('#empty-add-material');
                if (btn) btn.addEventListener('click', () => this.openForm());
                window.i18n.applyTranslations();
                return;
            }
            listEl.innerHTML = materials.map((m) => this.renderRow(m)).join('');
            listEl.querySelectorAll('[data-id]').forEach((row) => {
                row.addEventListener('click', () => {
                    const material = materials.find((m) => m.id === Number(row.dataset.id));
                    this.openDetail(material);
                });
                row.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        row.click();
                    }
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadMaterials());
        }
    }

    renderRow(m) {
        return `
            <div class="list-row" role="button" tabindex="0" data-id="${m.id}">
                <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                    <div class="thumb">${m.photo ? `<img src="${window.ui.escape(m.photo)}" alt="">` : '🪨'}</div>
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
                <div class="thumb" style="width:56px;height:56px;">${m.photo ? `<img src="${window.ui.escape(m.photo)}" alt="">` : '🪨'}</div>
                <div>
                    <div style="font-weight:600;font-size:16px;">${window.ui.escape(m.name)}</div>
                    <div class="text-sm text-muted">${window.ui.escape(m.stone_type || '')}</div>
                </div>
            </div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border);">
                ${this.detailRow('warehouse.quantity', `${window.ui.qty(m.quantity)} ${window.ui.t('units.' + m.unit)}`, m.is_low_stock)}
                ${this.detailRow('warehouse.required_for_orders', window.ui.qty(m.required_for_orders))}
                ${this.detailRow('warehouse.available', window.ui.qty(m.available_quantity))}
                ${this.detailRow('warehouse.min_stock', window.ui.qty(m.min_stock))}
                ${this.detailRow('warehouse.barcode', m.barcode)}
                ${this.detailRow('warehouse.storage_zone', m.storage_zone_display)}
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
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px;">
                    <button class="btn btn-secondary btn-sm" id="edit-material" data-i18n="common.edit"></button>
                    ${m.is_archived ? '' : `<button class="btn btn-success btn-sm" id="income-material" data-i18n="warehouse.incoming"></button>`}
                    ${m.is_archived ? '' : `<button class="btn btn-danger btn-sm" id="outgoing-material" data-i18n="warehouse.outgoing"></button>`}
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
            modal.querySelector('#outgoing-material')?.addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openOutgoingForm(m);
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
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(listEl)) return;
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
                        <input name="quantity" type="number" step="0.001" min="0" class="form-control"
                               ${m ? 'disabled' : 'required'} value="${m?.quantity ?? ''}">
                        ${m ? `<small class="text-muted" data-i18n="warehouse.quantity_readonly_hint"></small>` : ''}</div>
                    <div class="form-group"><label data-i18n="warehouse.min_stock"></label>
                        <input name="min_stock" type="number" step="0.001" min="0" class="form-control" value="${m?.min_stock ?? 0}"></div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="warehouse.barcode"></label>
                        <input name="barcode" class="form-control" value="${window.ui.escape(m?.barcode || '')}"></div>
                    <div class="form-group"><label data-i18n="warehouse.storage_zone"></label>
                        <select name="storage_zone" class="form-control">
                            <option value="" data-i18n="common.select"></option>
                            <option value="a" ${m?.storage_zone === 'a' ? 'selected' : ''} data-i18n="warehouse.zone_a"></option>
                            <option value="b" ${m?.storage_zone === 'b' ? 'selected' : ''} data-i18n="warehouse.zone_b"></option>
                            <option value="c" ${m?.storage_zone === 'c' ? 'selected' : ''} data-i18n="warehouse.zone_c"></option>
                            <option value="other" ${m?.storage_zone === 'other' ? 'selected' : ''} data-i18n="warehouse.zone_other"></option>
                        </select></div>
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
                <div class="form-group"><label data-i18n="warehouse.photo"></label>
                    <input name="photo" type="file" accept="image/*" class="form-control">
                    ${m?.photo ? `<small class="text-muted" data-i18n="warehouse.photo_replace_hint"></small>` : ''}</div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#material-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            // formBody сам выберет multipart, если приложили фото: JSON.stringify
            // выбрасывал файл, и картинка не доходила до сервера.
            const body = await window.ui.formBody(e.target);
            if (body instanceof FormData) {
                if (!body.get('arrival_date')) body.delete('arrival_date');
            }
            const payload = body instanceof FormData ? body : (() => {
                const data = JSON.parse(body);
                if (!data.arrival_date) delete data.arrival_date;
                return JSON.stringify(data);
            })();
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (m) {
                        await window.api.request(`/warehouse/raw-materials/${m.id}/`, {
                            method: 'PATCH', body: payload,
                        });
                    } else {
                        await window.api.request('/warehouse/raw-materials/', {
                            method: 'POST', body: payload,
                        });
                    }
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadMaterials();
                    this.loadSummary();
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
                <div class="form-group"><label data-i18n="warehouse.document_number"></label>
                    <input name="document_number" class="form-control"></div>
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
                    this.loadSummary();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    /**
     * Расход/списание сырья (макет «Материални чиқариш»).
     *
     * Тип движения: расход (outgoing), потеря/брак (loss) или корректировка
     * (adjustment). Списывается только доступное количество: зарезервированное
     * под заказы сырьё сервер не даст списать (POST .../outgoing/).
     */
    openOutgoingForm(m) {
        const today = new Date().toISOString().slice(0, 10);
        const modal = window.ui.modal('warehouse.outgoing', `
            <p style="margin-bottom:12px;font-weight:600;">${window.ui.escape(m.name)}</p>
            <form id="outgoing-form">
                <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                    <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required
                           max="${window.ui.qty(m.available_quantity)}"></div>
                <div class="form-group"><label data-i18n="warehouse.outgoing_type"></label>
                    <select name="movement_type" class="form-control">
                        <option value="outgoing" data-i18n="warehouse.movement_outgoing"></option>
                        <option value="loss" data-i18n="warehouse.movement_loss"></option>
                        <option value="adjustment" data-i18n="warehouse.movement_adjustment"></option>
                    </select></div>
                <div class="form-group"><label data-i18n="warehouse.document_number"></label>
                    <input name="document_number" class="form-control"></div>
                <div class="form-group"><label data-i18n="warehouse.outgoing_date"></label>
                    <input name="outgoing_date" type="date" class="form-control" value="${today}" max="${today}"></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="reason" class="form-control"></div>
                <button type="submit" class="btn btn-danger btn-block" data-i18n="warehouse.outgoing"></button>
            </form>
        `);
        modal.querySelector('#outgoing-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            Object.keys(data).forEach((k) => { if (data[k] === '') delete data[k]; });
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/warehouse/raw-materials/${m.id}/outgoing/`, {
                        method: 'POST',
                        body: JSON.stringify(data),
                    });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadMaterials();
                    this.loadSummary();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

}

window.WarehouseComponent = new WarehouseComponent();
