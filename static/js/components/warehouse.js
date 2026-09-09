/**
 * Склад сырья: список с поиском, низкие остатки красным,
 * добавление/редактирование (owner/admin), закупочные цены видит только owner.
 */
class WarehouseComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'warehouse.title');
        this.search = '';
        this.filters = {
            unit: '', condition: '', color: '', size: '', storage_zone: '', stock_severity: '',
        };
        this.stoneTypeFilter = '';
        this.warehouseFilter = '';
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
                <button class="tab-btn" role="tab" aria-selected="false" data-wtab="low" data-i18n="warehouse.min_leftovers"></button>
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
            <!-- «Тезкор маълумот» и «Склад якуний (бугун)» из макета:
                 раньше сводка показывала только остатки и стоимость. -->
            <div class="card" id="warehouse-quick" style="display:none;margin:0 0 10px;"></div>
            <!-- Переключатель складов из макета «Асосий омбор»: до появления
                 модели Warehouse склад был один и подразумевался неявно. -->
            <div class="form-group" id="warehouse-picker" style="display:none;margin-bottom:10px;">
                <label class="text-sm text-muted" data-i18n="warehouse.warehouse"></label>
                <select id="warehouse-select" class="form-control"></select>
            </div>
            <div id="warehouse-cells" class="u-mb-4"></div>
            <div id="stone-type-tabs" class="tabs" role="tablist" aria-label="Stone type filters" style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;"></div>
            <div class="search-box search-box--with-action">
                <div class="search-field">
                    <span class="search-icon" aria-hidden="true">${window.icon('search', 18)}</span>
                    <input type="text" id="material-search" class="form-control" data-i18n-attr="placeholder,aria-label" data-i18n="warehouse.search">
                </div>
                <button class="btn btn-secondary" id="scan-barcode-btn" type="button" data-i18n-attr="aria-label" data-i18n="warehouse.scan_barcode"
                        style="padding:8px 12px;font-size:18px;">${window.icon('camera', 20)}</button>
                <button class="btn btn-secondary" id="warehouse-filter-toggle" type="button" data-i18n="warehouse.filter"></button>
            </div>
            <div class="card" id="warehouse-filter-panel" style="display:none;margin:0 0 10px;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                    <div class="form-group u-m-0">
                        <label class="text-sm text-muted" data-i18n="warehouse.unit"></label>
                        <select id="filter-unit" class="form-control">
                            <option value="" data-i18n="common.all"></option>
                            ${window.ui.unitOptions('')}
                        </select>
                    </div>
                    <div class="form-group u-m-0">
                        <label class="text-sm text-muted" data-i18n="warehouse.condition"></label>
                        <select id="filter-condition" class="form-control">
                            <option value="" data-i18n="common.all"></option>
                            ${['excellent', 'good', 'poor', 'critical'].map((c) =>
                                `<option value="${c}" data-i18n="material_conditions.${c}"></option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group u-m-0">
                        <label class="text-sm text-muted" data-i18n="warehouse.color"></label>
                        <input id="filter-color" class="form-control" data-i18n-attr="placeholder" data-i18n="warehouse.color">
                    </div>
                    <div class="form-group u-m-0">
                        <label class="text-sm text-muted" data-i18n="warehouse.size"></label>
                        <input id="filter-size" class="form-control" data-i18n-attr="placeholder" data-i18n="warehouse.size">
                    </div>
                    <div class="form-group u-m-0">
                        <label class="text-sm text-muted" data-i18n="warehouse.storage_zone"></label>
                        <select id="filter-zone" class="form-control">
                            <option value="" data-i18n="common.all"></option>
                            <option value="a" data-i18n="warehouse.zone_a"></option>
                            <option value="b" data-i18n="warehouse.zone_b"></option>
                            <option value="c" data-i18n="warehouse.zone_c"></option>
                            <option value="other" data-i18n="warehouse.zone_other"></option>
                        </select>
                    </div>
                </div>
                <button class="btn btn-secondary btn-sm btn-block u-mt-3" id="warehouse-filter-clear"
                        type="button" data-i18n="common.clear_filter"></button>
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-material-btn" style="margin-bottom:12px;margin-top:10px;" data-i18n="warehouse.add_material"></button>` : ''}
            ${canEdit ? `<button class="btn btn-success btn-block u-mb-5" id="receipt-doc-btn" data-i18n="warehouse.receipt_document"></button>` : ''}
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
            this.filters.stock_severity = '';
            this.setListChrome(container);
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
                if (this.tab === 'active' || this.tab === 'low') this.filters.stock_severity = '';
                setMaterialsTabActive(this.tab === 'active' || this.tab === 'low');
                this.setListChrome(container);
                if (this.tab === 'history') this.loadHistory();
                else this.loadMaterials();
            });
        });

        const searchInput = container.querySelector('#material-search');
        searchInput.addEventListener('input', window.ui.debounce(() => {
            this.search = searchInput.value;
            this.loadMaterials();
        }, 300));

        const filterToggle = container.querySelector('#warehouse-filter-toggle');
        const filterPanel = container.querySelector('#warehouse-filter-panel');
        if (filterToggle && filterPanel) {
            filterToggle.addEventListener('click', () => {
                filterPanel.style.display = filterPanel.style.display === 'none' ? '' : 'none';
            });
        }
        const applyFilters = () => {
            this.filters.unit = container.querySelector('#filter-unit')?.value || '';
            this.filters.condition = container.querySelector('#filter-condition')?.value || '';
            this.filters.color = (container.querySelector('#filter-color')?.value || '').trim();
            this.filters.size = (container.querySelector('#filter-size')?.value || '').trim();
            this.filters.storage_zone = container.querySelector('#filter-zone')?.value || '';
            this.loadMaterials();
        };
        ['#filter-unit', '#filter-condition', '#filter-zone'].forEach((sel) => {
            container.querySelector(sel)?.addEventListener('change', applyFilters);
        });
        ['#filter-color', '#filter-size'].forEach((sel) => {
            container.querySelector(sel)?.addEventListener('input', window.ui.debounce(applyFilters, 300));
        });
        container.querySelector('#warehouse-filter-clear')?.addEventListener('click', () => {
            this.filters = {
                unit: '', condition: '', color: '', size: '', storage_zone: '', stock_severity: '',
            };
            ['#filter-unit', '#filter-condition', '#filter-zone', '#filter-color', '#filter-size']
                .forEach((sel) => { const el = container.querySelector(sel); if (el) el.value = ''; });
            this.loadMaterials();
        });

        if (canEdit) {
            container.querySelector('#add-material-btn').addEventListener('click', () => this.openForm());
            container.querySelector('#receipt-doc-btn').addEventListener('click', () => this.openReceiptForm());
        }

        const scanBtn = container.querySelector('#scan-barcode-btn');
        if (scanBtn) {
            scanBtn.addEventListener('click', () => this.openBarcodeScanner());
        }

        window.i18n.applyTranslations();
        await this.loadWarehouses();
        await this.loadStoneTypes();
        await this.loadMaterials();
        this.loadSummary();
    }

    /**
     * Поиск и фильтр относятся к списку материалов; в истории движений они лишние.
     */
    setListChrome(container) {
        const isHistory = this.tab === 'history';
        const isArchive = this.tab === 'archive';
        const search = container.querySelector('.search-box');
        if (search) search.style.display = isHistory ? 'none' : '';
        const filterToggle = container.querySelector('#warehouse-filter-toggle');
        if (filterToggle) filterToggle.style.display = isHistory ? 'none' : '';
        const filterPanel = container.querySelector('#warehouse-filter-panel');
        if (filterPanel && isHistory) filterPanel.style.display = 'none';
        const addBtn = container.querySelector('#add-material-btn');
        if (addBtn) addBtn.style.display = (isHistory || isArchive) ? 'none' : '';
        const receiptBtn = container.querySelector('#receipt-doc-btn');
        if (receiptBtn) receiptBtn.style.display = (isHistory || isArchive) ? 'none' : '';
        const stoneTabs = container.querySelector('#stone-type-tabs');
        if (stoneTabs) stoneTabs.style.display = isHistory ? 'none' : 'flex';
    }

    /** Итоговые показатели склада: остатки по единицам и стоимость (для owner). */
    async loadSummary() {
        const wrap = document.getElementById('warehouse-summary');
        if (!wrap || window.listStates.gone(wrap)) return;
        try {
            const data = await window.api.request('/warehouse/raw-materials/summary/');
            const totalEl = document.getElementById('summary-total');
            if (totalEl) {
                const totals = data.unit_totals || [];
                if (!totals.length) {
                    totalEl.textContent = window.ui.qty(0);
                } else if (totals.length === 1) {
                    // Всё сырьё в одной единице — показываем честный общий остаток.
                    const t = totals[0];
                    totalEl.textContent = `${window.ui.qty(t.quantity)} ${window.ui.t('units.' + t.unit)}`;
                } else {
                    // Единицы разные — складывать их нельзя, показываем разбивку.
                    totalEl.innerHTML = totals.map((t) =>
                        `<div>${window.ui.qty(t.quantity)} ${window.ui.escape(window.ui.t('units.' + t.unit))}</div>`
                    ).join('');
                }
            }
            const valueEl = document.getElementById('summary-value');
            if (valueEl) valueEl.textContent = window.ui.money(data.total_value ?? 0);
            wrap.style.display = 'flex';
            // Разрез по видам нужен чипам: держим его на компоненте.
            this.typeTotals = Object.fromEntries(
                (data.type_totals || []).map((t) => [t.stone_type, t])
            );
            this.renderQuickStats(data);
            this.loadStoneTypes();
        } catch (e) {
            /* итоги некритичны */
        }
    }

    /**
     * «Тезкор маълумот» и «Склад якуний (бугун)» из макета «Хом ашё омбори».
     *
     * Цифры считает сервер по тем же правилам, что и карточка материала
     * (stock_severity), иначе шапка и список показывали бы разное.
     */
    renderQuickStats(data) {
        const box = document.getElementById('warehouse-quick');
        if (!box) return;
        const stats = data.quick_stats;
        const today = data.today;
        if (!stats && !today) { box.style.display = 'none'; return; }
        const chip = (labelKey, value, cls = '', severity = '') => `
            <button type="button" data-severity-filter="${severity}"
                    style="flex:1 1 100px;text-align:center;border:none;background:none;padding:0;
                           cursor:${severity ? 'pointer' : 'default'};">
                <div class="font-bold ${cls}">${window.ui.escape(String(value))}</div>
                <div class="text-sm text-muted" data-i18n="${labelKey}"></div>
            </button>`;
        box.innerHTML = `
            <div class="card-title u-mb-2"><span data-i18n="warehouse.quick_stats"></span></div>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
                ${chip('warehouse.types_count', data.types_count ?? 0)}
                ${chip('warehouse.materials_count', data.materials_count ?? 0)}
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:8px;">
                ${chip('warehouse.at_minimum', stats?.low_stock_count ?? 0, 'text-warning', 'low')}
                ${chip('warehouse.critical_low', stats?.critical_count ?? 0, 'text-danger', 'critical')}
                ${chip('warehouse.recent_arrivals', stats?.recent_arrivals_count ?? 0)}
                ${chip('warehouse.in_reserve', stats?.reserved_count ?? 0)}
            </div>
            ${today ? `
                <div class="text-sm text-muted u-mt-3">
                    <span data-i18n="warehouse.today_summary"></span>:
                    <span class="text-success">+${window.ui.qty(today.incoming)}</span>
                    <span data-i18n="warehouse.today_incoming"></span> ·
                    <span class="text-danger">−${window.ui.qty(today.outgoing)}</span>
                    <span data-i18n="warehouse.today_outgoing"></span>
                </div>` : ''}`;
        box.style.display = '';
        box.querySelectorAll('[data-severity-filter]').forEach((el) => {
            const severity = el.dataset.severityFilter;
            if (!severity) return;
            el.addEventListener('click', () => this.applySeverityFilter(severity));
        });
        window.i18n.applyTranslations();
    }

    /**
     * Чипы «на минимуме» / «критично» открывают список с той же градацией,
     * что считает шапка (stock_severity).
     */
    applySeverityFilter(severity) {
        this.tab = 'active';
        this.filters.stock_severity = severity;
        const root = document.getElementById('app-content')
            || document.getElementById('materials-list')?.parentElement;
        if (root) {
            root.querySelectorAll('[data-wtab]').forEach((b) => {
                const active = b.dataset.wtab === 'active';
                b.classList.toggle('active', active);
                b.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            this.setListChrome(root);
        }
        this.loadMaterials();
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
                    <span id="scanner-placeholder" style="font-size:32px;">${window.icon('camera', 32)}</span>
                </div>
                <p class="text-sm text-muted" data-i18n="warehouse.scan_hint"></p>
                <p class="text-sm scanner-status" id="scanner-status"></p>
                <div style="display:flex;gap:10px;justify-content:center;margin-top:15px;">
                    <button class="btn btn-secondary btn-sm" type="button" id="scanner-torch">${window.icon('zap', 16)} <span data-i18n="warehouse.flashlight"></span></button>
                    <button class="btn btn-secondary btn-sm" type="button" id="scanner-gallery">${window.icon('image', 16)} <span data-i18n="warehouse.gallery"></span></button>
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

    async loadStoneTypes() {
        const tabsEl = document.getElementById('stone-type-tabs');
        if (!tabsEl) return;
        try {
            const response = await window.api.request('/warehouse/raw-materials/?is_archived=false&page_size=500');
            const materials = response.results || [];
            const typeCounts = {};
            materials.forEach(m => {
                const type = m.stone_type || window.ui.t('common.other');
                typeCounts[type] = (typeCounts[type] || 0) + 1;
            });
            const types = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
            tabsEl.innerHTML = [
                `<button class="tab-btn ${!this.stoneTypeFilter ? 'active' : ''}" data-stone-type="">${window.ui.t('common.all')} (${materials.length})</button>`,
                // В макете на чипе стоит ОСТАТОК вида («Оқ мрамор 250.75 м²»),
                // а не число позиций. Сумму считает сервер; при смешанных
                // единицах внутри вида она равна null — тогда показываем
                // количество позиций, складывать м² с кг нельзя.
                ...types.map(([type, count]) => {
                    const totals = this.typeTotals?.[type];
                    const label = (totals && totals.quantity !== null && totals.quantity !== undefined)
                        ? `${window.ui.qty(totals.quantity)} ${window.ui.t('units.' + totals.unit)}`
                        : count;
                    return `<button class="tab-btn ${this.stoneTypeFilter === type ? 'active' : ''}" data-stone-type="${window.ui.escape(type)}">${window.ui.escape(type)} (${label})</button>`;
                })
            ].join('');
            tabsEl.querySelectorAll('[data-stone-type]').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.stoneTypeFilter = btn.dataset.stoneType;
                    tabsEl.querySelectorAll('[data-stone-type]').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    this.loadMaterials();
                });
            });
        } catch (e) {
            tabsEl.innerHTML = '';
        }
    }

    /**
     * Список складов и карта ячеек (макеты «Асосий омбор», «Омбордаги жойлашув»).
     *
     * Если склад один, селектор не показываем — лишний элемент управления в
     * интерфейсе, где выбирать не из чего.
     */
    async loadWarehouses() {
        const picker = document.getElementById('warehouse-picker');
        const select = document.getElementById('warehouse-select');
        if (!picker || !select) return;
        try {
            const response = await window.api.request('/warehouse/warehouses/?is_archived=false');
            const warehouses = response.results || response;
            this.warehouses = warehouses;
            if (warehouses.length < 2) {
                picker.style.display = 'none';
            } else {
                picker.style.display = '';
                select.innerHTML = `<option value="">${window.ui.escape(window.ui.t('warehouse.all_warehouses'))}</option>`
                    + warehouses.map((w) => `<option value="${w.id}">${window.ui.escape(w.name)}</option>`).join('');
                select.addEventListener('change', () => {
                    this.warehouseFilter = select.value;
                    this.loadMaterials();
                    this.loadCells();
                });
            }
            const preselected = warehouses.find((w) => w.is_default) || warehouses[0];
            this.currentWarehouse = preselected ? preselected.id : null;
            await this.loadCells();
        } catch (e) {
            // Карта складов некритична: список материалов должен открыться в любом случае.
            picker.style.display = 'none';
        }
    }

    /** Карта ячеек А-01…А-08 с занятостью (проценты считает сервер). */
    async loadCells() {
        const wrap = document.getElementById('warehouse-cells');
        if (!wrap || window.listStates.gone(wrap)) return;
        const warehouseId = this.warehouseFilter || this.currentWarehouse;
        if (!warehouseId) { wrap.innerHTML = ''; return; }
        try {
            const data = await window.api.request(`/warehouse/warehouses/${warehouseId}/occupancy/`);
            if (!data.cells || !data.cells.length) { wrap.innerHTML = ''; return; }
            wrap.innerHTML = `
                <div class="card u-m-0">
                    <div class="card-title u-mb-2">
                        <span data-i18n="warehouse.cells_map"></span>
                    </div>
                    <div class="text-sm text-muted u-mb-3">
                        <span data-i18n="warehouse.total_area"></span>: ${window.ui.qty(data.total_area)} m²
                        · <span data-i18n="warehouse.occupied"></span>: ${data.occupancy_percent}%
                        · <span data-i18n="warehouse.free"></span>: ${data.free_percent}%
                    </div>
                    <div class="cell-grid" style="display:flex;flex-wrap:wrap;gap:6px;">
                        ${data.cells.map((c) => `
                            <div class="cell-chip" style="flex:1 1 90px;padding:8px;border-radius:8px;
                                 background:var(--surface-2, #f5f5f7);text-align:center;">
                                <div class="font-bold">${window.ui.escape(c.code)}</div>
                                <div class="text-sm ${Number(c.occupancy_percent) >= 90 ? 'text-danger' : 'text-muted'}">
                                    ${c.occupancy_percent}%
                                </div>
                            </div>`).join('')}
                    </div>
                </div>`;
            window.i18n.applyTranslations();
        } catch (e) {
            wrap.innerHTML = '';
        }
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
            // Фильтр «Қайси омбор» из макета.
            if (this.warehouseFilter) query += `&warehouse=${encodeURIComponent(this.warehouseFilter)}`;
            // Вид камня — серверный фильтр: отбор текущей страницы врал бы
            // начиная со второй (тот же класс, что у вкладок истории).
            if (this.stoneTypeFilter) query += `&stone_type=${encodeURIComponent(this.stoneTypeFilter)}`;
            if (this.tab === 'low') query += '&stock_severity=below_min';
            else if (this.filters && this.filters.stock_severity) {
                query += `&stock_severity=${encodeURIComponent(this.filters.stock_severity)}`;
            }
            const filters = this.filters || {};
            ['unit', 'condition', 'color', 'size', 'storage_zone'].forEach((key) => {
                if (filters[key]) query += `&${key}=${encodeURIComponent(filters[key])}`;
            });
            const response = await window.api.request(`/warehouse/raw-materials/${query}`);
            const materials = response.results || [];

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
                <div class="u-row">
                    <div class="thumb">${m.photo ? `<img src="${window.ui.escape(m.photo)}" alt="" onerror="this.parentElement.innerHTML=window.icon('layers', 36)">` : window.icon('layers', 36)}</div>
                    <div class="u-minw-0">
                        <div class="u-title-sm">${window.ui.escape(m.name)}</div>
                        <div class="text-sm text-muted">${window.ui.escape([m.stone_type, m.size].filter(Boolean).join(' · ') || '-')}</div>
                    </div>
                </div>
                <div class="u-text-right u-shrink-0">
                    <div class="${m.is_low_stock ? 'text-danger' : ''} u-title-md">
                        ${window.ui.qty(m.quantity)} <span data-i18n="units.${m.unit}"></span>
                    </div>
                    ${this.severityLabel(m)}
                    ${m.cell_code ? `<div class="text-sm text-muted">${window.ui.escape(m.cell_code)}</div>` : ''}
                </div>
            </div>`;
    }

    /**
     * Подпись остатка по градации сервера (макет «Минимум қолдиқлар»).
     *
     * Раньше был единственный флаг is_low_stock, и «почти закончилось»
     * выглядело так же, как «уже не хватает под заказы».
     */
    severityLabel(m) {
        if (m.stock_severity === 'critical') {
            return `<div class="text-sm text-danger" data-i18n="warehouse.severity_critical"></div>`;
        }
        if (m.stock_severity === 'low' || m.is_low_stock) {
            return `<div class="text-sm text-warning" data-i18n="warehouse.severity_low"></div>`;
        }
        return '';
    }

    openDetail(m) {
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;
        // Количество: Жами колдик, Резерв, Ёш вазн
        const totalQty = m.quantity || 0;
        const reservedQty = m.reserved_quantity || 0;
        const availableQty = m.available_quantity || 0;
        const minStock = m.min_stock || 0;
        const maxStock = m.max_stock || totalQty * 1.3;
        const lowStock = m.is_low_stock;
        const statusBadge = m.is_archived 
            ? `<span class="badge badge-cancel">${window.ui.t('common.archived')}</span>` 
            : (lowStock ? `<span class="badge badge-warning">${window.ui.t('warehouse.critical')}</span>` : `<span class="badge badge-ready">${window.ui.t('common.active')}</span>`);
        
        const modal = window.ui.modal('warehouse.title', `
            ${m.photo ? `<div style="margin:-20px -20px 14px;border-radius:12px;overflow:hidden;height:180px;background:var(--bg-secondary);">
                <img src="${window.ui.escape(m.photo)}" alt="" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=\'display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;\'>' + window.icon('layers', 48) + '</div>'">
            </div>` : ''}
            <div class="u-row u-mb-14">
                <div class="thumb u-thumb-lg">${m.photo ? `<img src="${window.ui.escape(m.photo)}" alt="" onerror="this.parentElement.innerHTML=window.icon('layers', 36)">` : window.icon('layers', 36)}</div>
                <div style="flex:1;min-width:0;">
                    <div class="u-title-lg">${window.ui.escape(m.name)}</div>
                    <div class="text-sm text-muted">${window.ui.escape(m.stone_type || '')} · ${window.ui.escape(m.color || '')}</div>
                </div>
                ${statusBadge}
            </div>
            <!-- Разбивка количества по макету -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
                <div class="card" style="margin:0;padding:10px;${lowStock ? 'border-color:var(--danger-color);' : ''}">
                    <div class="text-sm text-muted" data-i18n="warehouse.total_stock"></div>
                    <div style="font-weight:700;font-size:18px;${lowStock ? 'color:var(--danger-color);' : ''}">${window.ui.qty(totalQty)} <span data-i18n="units.${m.unit}"></span></div>
                </div>
                <div class="card u-card-compact">
                    <div class="text-sm text-muted" data-i18n="warehouse.min_stock"></div>
                    <div style="font-weight:700;font-size:18px;">${window.ui.qty(minStock)} <span data-i18n="units.${m.unit}"></span></div>
                </div>
                <div class="card u-card-compact">
                    <div class="text-sm text-muted" data-i18n="warehouse.reserved"></div>
                    <div style="font-weight:700;font-size:18px;">${window.ui.qty(reservedQty)} <span data-i18n="units.${m.unit}"></span></div>
                </div>
                <div class="card u-card-compact">
                    <div class="text-sm text-muted" data-i18n="warehouse.available"></div>
                    <div style="font-weight:700;font-size:18px;color:var(--success-color);">${window.ui.qty(availableQty)} <span data-i18n="units.${m.unit}"></span></div>
                </div>
            </div>
            <!-- Характеристики -->
            <div class="list-group u-card-flat">
                ${this.detailRow('warehouse.barcode', m.barcode)}
                ${this.detailRow('warehouse.size', m.size)}
                ${this.detailRow('warehouse.thickness', m.thickness)}
                ${this.detailRow('warehouse.color', m.color)}
                ${this.detailRow('warehouse.storage_zone', m.storage_zone_display)}
                ${this.detailRow('warehouse.storage_location', m.storage_location)}
                ${this.detailRow('warehouse.warehouse', m.warehouse_name)}
                ${this.detailRow('warehouse.cell', m.cell_code)}
                ${this.detailRow('warehouse.condition', m.condition ? window.ui.t('material_conditions.' + m.condition) : '')}
                ${this.detailRow('warehouse.supplier', m.supplier)}
                ${this.detailRow('warehouse.arrival_date', m.arrival_date ? window.ui.date(m.arrival_date) : '')}
                ${user.is_owner ? this.detailRow('warehouse.purchase_price', window.ui.money(m.purchase_price)) : ''}
                ${user.is_owner ? this.detailRow('warehouse.avg_cost', window.ui.money(m.avg_cost_price)) : ''}
                ${user.is_owner && m.avg_cost_price != null && m.avg_cost_price !== ''
                    ? this.detailRow('warehouse.summary_value', window.ui.money(Number(m.quantity || 0) * Number(m.avg_cost_price || 0)))
                    : ''}
                ${this.detailRow('warehouse.comment', m.comment)}
            </div>
            <!-- Кнопки действий по макету -->
            ${canEdit && !m.is_archived ? `
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:14px;">
                    <button class="btn btn-success btn-sm" id="income-material" data-i18n="warehouse.incoming"></button>
                    <button class="btn btn-primary btn-sm" id="edit-material" data-i18n="common.edit"></button>
                    <button class="btn btn-danger btn-sm" id="outgoing-material" data-i18n="warehouse.outgoing"></button>
                </div>
                <!-- Возврат («Қайтарилган») отдельной кнопкой: раньше его
                     проводили обычным приходом и в истории он был неотличим
                     от новой поставки. -->
                <button class="btn btn-secondary btn-sm btn-block u-mt-3" id="return-material"
                        data-i18n="warehouse.return_material"></button>
                <button class="btn btn-secondary btn-sm btn-block u-mt-3" id="archive-material" data-i18n="common.archive"></button>` 
                : (canEdit ? `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px;">
                    <button class="btn btn-secondary btn-sm" id="edit-material" data-i18n="common.edit"></button>
                    <button class="btn btn-secondary btn-sm" id="archive-material" data-i18n="common.restore"></button>
                </div>` : '')}
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
            modal.querySelector('#return-material')?.addEventListener('click', () => {
                window.ui.closeModal(modal);
                this.openReturnForm(m);
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
            // Вкладки «Ҳаммаси / Келган / Ишлатилган / Қайтарилган» из макета.
            // Фильтрует СЕРВЕР: отбор загруженной страницы врал бы начиная со
            // второй страницы, а итоги считались бы по видимому куску.
            const category = this.historyCategory || '';
            const query = category ? `?page_size=50&category=${category}` : '?page_size=50';
            const [response, totals] = await Promise.all([
                window.api.request(`/warehouse/stock-movements/${query}`),
                window.api.request(`/warehouse/stock-movements/totals/${category ? `?category=${category}` : ''}`)
                    .catch(() => null),
            ]);
            const rows = response.results || response;

            const tabs = `
                <div class="tabs u-mb-4">
                    ${[['', 'warehouse.history_all'],
                       ['incoming', 'warehouse.history_incoming'],
                       ['outgoing', 'warehouse.history_outgoing'],
                       ['returned', 'warehouse.history_returned']].map(([value, key]) => `
                        <button class="tab-btn ${category === value ? 'active' : ''}"
                                data-history-tab="${value}" data-i18n="${key}"></button>`).join('')}
                </div>`;
            const totalsBlock = totals ? `
                <div class="card u-mt-4">
                    <div class="text-sm">
                        <span data-i18n="warehouse.total_incoming"></span>:
                        <span class="text-success">+${window.ui.qty(totals.incoming)}</span>
                        · <span data-i18n="warehouse.total_outgoing"></span>:
                        <span class="text-danger">−${window.ui.qty(totals.outgoing)}</span>
                        · <span data-i18n="warehouse.total_net"></span>:
                        <span class="font-bold">${window.ui.qty(totals.net)}</span>
                    </div>
                </div>` : '';

            const bindTabs = () => {
                listEl.querySelectorAll('[data-history-tab]').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        this.historyCategory = btn.dataset.historyTab;
                        this.loadHistory();
                    });
                });
            };

            if (!rows.length) {
                listEl.innerHTML = tabs + `<div class="card list-state" data-i18n="common.no_data"></div>` + totalsBlock;
                bindTabs();
                window.i18n.applyTranslations();
                return;
            }
            // Возврат («Қайтарилган») пополняет склад — знак и цвет как у прихода.
            const sign = (type) => (['outgoing', 'production_out', 'loss'].includes(type) ? '−' : '+');
            const colour = (type) => (['outgoing', 'production_out', 'loss'].includes(type) ? 'text-danger' : 'text-success');
            listEl.innerHTML = tabs + rows.map((r) => `
                <div class="list-row u-cursor-default">
                    <div class="u-minw-0">
                        <div class="u-title-sm">
                            ${window.ui.escape(r.material_name || r.product_name || '-')}
                        </div>
                        <div class="text-sm text-muted">
                            ${window.ui.escape(window.ui.t('movement_types.' + r.movement_type))}
                            · ${window.ui.datetime(r.created_at)}
                            ${r.created_by_name ? ` · ${window.ui.escape(r.created_by_name)}` : ''}
                            ${r.document_number ? ` · ${window.ui.escape(r.document_number)}` : ''}
                            ${r.related_order_id ? ` · ${window.ui.escape(window.ui.t('warehouse.outgoing_order'))} #${r.related_order_id}` : ''}
                        </div>
                    </div>
                    <div class="u-text-right u-shrink-0">
                        <div class="${colour(r.movement_type)} u-title-md">
                            ${sign(r.movement_type)}${window.ui.qty(r.quantity)}
                            ${r.unit ? `<span data-i18n="units.${r.unit}"></span>` : ''}
                        </div>
                    </div>
                </div>`).join('') + totalsBlock;
            bindTabs();
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadHistory());
        }
    }

    detailRow(labelKey, value, danger = false) {
        if (!value) return '';
        return `
            <div class="list-row u-cursor-default">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold ${danger ? 'text-danger' : ''} u-text-right">${window.ui.escape(String(value))}</span>
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
                <div class="u-grid-2">
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
                <div class="u-grid-2">
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
                <!-- Размещение и состояние партии (макеты «Асосий омбор» и
                     «Хом ашё омбори»): раньше место было только текстом, а
                     треснувшая плита выглядела как обычный остаток. -->
                <div class="u-grid-2">
                    <div class="form-group"><label data-i18n="warehouse.warehouse"></label>
                        <select name="warehouse" class="form-control" id="material-warehouse">
                            <option value="" data-i18n="common.select"></option>
                            ${(this.warehouses || []).map((w) => `
                                <option value="${w.id}" ${String(m?.warehouse) === String(w.id) ? 'selected' : ''}>
                                    ${window.ui.escape(w.name)}
                                </option>`).join('')}
                        </select></div>
                    <div class="form-group"><label data-i18n="warehouse.cell"></label>
                        <select name="cell" class="form-control" id="material-cell">
                            <option value="" data-i18n="common.select"></option>
                        </select></div>
                </div>
                <div class="form-group"><label data-i18n="warehouse.condition"></label>
                    <select name="condition" class="form-control">
                        <option value="" data-i18n="common.select"></option>
                        ${['excellent', 'good', 'poor', 'critical'].map((c) => `
                            <option value="${c}" ${m?.condition === c ? 'selected' : ''}
                                    data-i18n="material_conditions.${c}"></option>`).join('')}
                    </select></div>
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

        // Ячейки зависят от выбранного склада: показывать чужие бессмысленно —
        // сервер такое размещение отклонит.
        const whSelect = modal.querySelector('#material-warehouse');
        const cellSelect = modal.querySelector('#material-cell');
        const loadCellOptions = async (warehouseId, selected = '') => {
            cellSelect.innerHTML = `<option value=""></option>`;
            if (!warehouseId) return;
            try {
                const resp = await window.api.request(
                    `/warehouse/cells/?warehouse=${encodeURIComponent(warehouseId)}&is_archived=false`
                );
                const cells = resp.results || resp;
                cellSelect.innerHTML = `<option value=""></option>` + cells.map((c) => `
                    <option value="${c.id}" ${String(selected) === String(c.id) ? 'selected' : ''}>
                        ${window.ui.escape(c.code)}
                    </option>`).join('');
            } catch (err) {
                /* без ячеек форма всё равно работает */
            }
        };
        if (whSelect && cellSelect) {
            loadCellOptions(m?.warehouse || '', m?.cell || '');
            whSelect.addEventListener('change', () => loadCellOptions(whSelect.value));
        }

        modal.querySelector('#material-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            // formBody сам выберет multipart, если приложили фото: JSON.stringify
            // выбрасывал файл, и картинка не доходила до сервера.
            const body = await window.ui.formBody(e.target);
            // Пустые значения выпиливаем: DRF ждёт id или отсутствие поля,
            // пустая строка приводит к 400.
            const optional = ['arrival_date', 'warehouse', 'cell', 'condition'];
            if (body instanceof FormData) {
                optional.forEach((name) => { if (!body.get(name)) body.delete(name); });
            }
            const payload = body instanceof FormData ? body : (() => {
                const data = JSON.parse(body);
                optional.forEach((name) => { if (!data[name]) delete data[name]; });
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
            <p class="u-mb-5 u-strong">${window.ui.escape(m.name)}</p>
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
            <p class="u-mb-5 u-strong">${window.ui.escape(m.name)}</p>
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
                <!-- «Қайси мақсадда» и «Буюртма» из макета «Материални ишлатиш»:
                     без них списание анонимно — в истории не видно, на какой
                     заказ ушло сырьё. -->
                <div class="form-group"><label data-i18n="warehouse.outgoing_purpose"></label>
                    <select name="purpose" class="form-control">
                        <option value=""></option>
                        ${['production', 'sample', 'internal', 'write_off', 'other'].map((v) =>
                            `<option value="${v}" data-i18n="outgoing_purposes.${v}"></option>`).join('')}
                    </select></div>
                <div class="form-group" id="outgoing-order-group" style="display:none;">
                    <label data-i18n="warehouse.outgoing_order"></label>
                    <select name="order" class="form-control"><option value=""></option></select></div>
                <div class="form-group"><label data-i18n="warehouse.document_number"></label>
                    <input name="document_number" class="form-control"></div>
                <div class="form-group"><label data-i18n="warehouse.outgoing_date"></label>
                    <input name="outgoing_date" type="date" class="form-control" value="${today}" max="${today}"></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="reason" class="form-control"></div>
                <button type="submit" class="btn btn-danger btn-block" data-i18n="warehouse.outgoing"></button>
            </form>
        `);
        // Список заказов подгружаем только когда цель — производство:
        // для образца или внутренних нужд заказа нет.
        const purposeSelect = modal.querySelector('[name=purpose]');
        const orderGroup = modal.querySelector('#outgoing-order-group');
        const orderSelect = modal.querySelector('[name=order]');
        let ordersLoaded = false;
        purposeSelect?.addEventListener('change', async () => {
            const needsOrder = purposeSelect.value === 'production';
            orderGroup.style.display = needsOrder ? '' : 'none';
            if (!needsOrder || ordersLoaded) return;
            try {
                const resp = await window.api.request('/orders/orders/?is_archived=false&page_size=100');
                const orders = resp.results || resp;
                orderSelect.innerHTML = '<option value=""></option>' + orders.map((o) =>
                    `<option value="${o.id}">#${o.id} ${window.ui.escape(o.product_name || o.custom_product_name || '')}</option>`
                ).join('');
                ordersLoaded = true;
            } catch (error) {
                orderGroup.style.display = 'none';
            }
        });

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

    /**
     * Документ прихода: одна поставка — несколько материалов.
     *
     * Макет «Материални қабул қилиш» задаёт поставщика, номер и дату один раз,
     * а позиции добавляются кнопкой «Яна материал қўшиш». Раньше приход
     * оформлялся по одному материалу, и общие реквизиты приходилось вводить
     * заново на каждую позицию.
     */
    async openReceiptForm() {
        const isOwner = window.currentUser.is_owner;
        const today = new Date().toISOString().slice(0, 10);
        const resp = await window.api.request('/warehouse/raw-materials/?is_archived=false&page_size=200');
        const materials = resp.results || resp;

        const lineRow = () => `
            <div class="receipt-line" style="display:grid;grid-template-columns:1fr 90px ${isOwner ? '110px' : ''} auto;gap:8px;margin-bottom:8px;">
                <select name="material" class="form-control">
                    <option value=""></option>
                    ${materials.map((m) => `<option value="${m.id}">${window.ui.escape(m.name)}</option>`).join('')}
                </select>
                <input name="quantity" type="number" step="0.001" min="0.001" class="form-control"
                       placeholder="${window.ui.t('warehouse.quantity')}">
                ${isOwner ? `<input name="price_per_unit" type="number" step="0.01" min="0" class="form-control"
                       placeholder="${window.ui.t('warehouse.purchase_price')}">` : ''}
                <button type="button" class="icon-btn receipt-line-remove" aria-label="${window.ui.t('common.delete')}">${window.icon('trash', 16)}</button>
            </div>`;

        const modal = window.ui.modal('warehouse.receipt_document', `
            <form id="receipt-form">
                <div class="form-group"><label data-i18n="warehouse.supplier"></label>
                    <input name="supplier" class="form-control" maxlength="255"></div>
                <div class="form-group"><label data-i18n="warehouse.document_number"></label>
                    <input name="document_number" class="form-control" maxlength="100" placeholder="K-1258"></div>
                <div class="form-group"><label data-i18n="warehouse.arrival_date"></label>
                    <input name="receipt_date" type="date" class="form-control" value="${today}" max="${today}"></div>
                <div class="form-group"><label data-i18n="warehouse.receipt_lines"></label>
                    <div id="receipt-lines">${lineRow()}</div>
                    <button type="button" class="btn btn-secondary btn-sm btn-block u-mt-2" id="add-line"
                            data-i18n="warehouse.add_material_line"></button>
                </div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="comment" class="form-control"></div>
                <button type="submit" class="btn btn-success btn-block" data-i18n="warehouse.incoming"></button>
            </form>
        `);

        const bindRemove = () => {
            modal.querySelectorAll('.receipt-line-remove').forEach((btn) => {
                btn.onclick = () => {
                    const rows = modal.querySelectorAll('.receipt-line');
                    if (rows.length > 1) btn.closest('.receipt-line').remove();
                };
            });
        };
        bindRemove();
        modal.querySelector('#add-line').addEventListener('click', () => {
            modal.querySelector('#receipt-lines').insertAdjacentHTML('beforeend', lineRow());
            bindRemove();
        });
        window.i18n.applyTranslations();

        modal.querySelector('#receipt-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const lines = [...form.querySelectorAll('.receipt-line')].map((row) => {
                const material = row.querySelector('[name=material]').value;
                const quantity = row.querySelector('[name=quantity]').value;
                const price = row.querySelector('[name=price_per_unit]')?.value;
                if (!material || !quantity) return null;
                const line = { material, quantity };
                if (price) line.price_per_unit = price;
                return line;
            }).filter(Boolean);

            if (!lines.length) {
                window.toast.error(window.ui.t('common.error'));
                return;
            }
            const payload = {
                supplier: form.querySelector('[name=supplier]').value.trim(),
                document_number: form.querySelector('[name=document_number]').value.trim(),
                receipt_date: form.querySelector('[name=receipt_date]').value,
                comment: form.querySelector('[name=comment]').value.trim(),
                lines,
            };
            await window.ui.submitGuard(form.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/warehouse/goods-receipts/', {
                        method: 'POST', body: JSON.stringify(payload),
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

    /** Возврат материала на склад (вкладка «Қайтарилган» в истории движений). */
    openReturnForm(m) {
        const today = new Date().toISOString().slice(0, 10);
        const modal = window.ui.modal('warehouse.return_material', `
            <p class="u-mb-5 u-strong">${window.ui.escape(m.name)}</p>
            <form id="return-form">
                <div class="form-group"><label data-i18n="warehouse.quantity"></label>
                    <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required></div>
                <div class="form-group"><label data-i18n="warehouse.document_number"></label>
                    <input name="document_number" class="form-control"></div>
                <div class="form-group"><label data-i18n="warehouse.arrival_date"></label>
                    <input name="return_date" type="date" class="form-control" value="${today}" max="${today}"></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <input name="reason" class="form-control"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="warehouse.return_material"></button>
            </form>
        `);
        modal.querySelector('#return-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            Object.keys(data).forEach((k) => { if (data[k] === '') delete data[k]; });
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/warehouse/raw-materials/${m.id}/returned/`, {
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
