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
                ${user.is_owner ? row('finance.labor_rate_per_unit',
                    p.labor_rate ? window.ui.money(p.labor_rate)
                                 : `<span class="text-danger" data-i18n="finance.labor_rate_missing"></span>`) : ''}
                ${row('warehouse.description', p.description)}
            </div>
            ${canEdit ? `
                <button class="btn btn-secondary btn-sm btn-block" id="product-recipes" style="margin-top:10px;" data-i18n="warehouse.recipes"></button>` : ''}
            ${canEdit ? `
                <div style="display:flex;gap:10px;margin-top:10px;">
                    <button class="btn btn-secondary btn-sm" id="edit-product" style="flex:1;" data-i18n="common.edit"></button>
                    ${p.is_archived ? '' : `<button class="btn btn-success btn-sm" id="income-product" style="flex:1;" data-i18n="warehouse.incoming"></button>`}
                </div>
                ${user.is_owner ? `
                    <button class="btn btn-secondary btn-sm btn-block" id="archive-product" style="margin-top:10px;"
                        data-i18n="${p.is_archived ? 'common.restore' : 'common.archive'}"></button>` : ''}` : ''}
        `);

        if (canEdit) {
            modal.querySelector('#product-recipes')?.addEventListener('click', () => {
                this.openRecipes(p);
            });
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

    /**
     * Рецепты товара: список с составом и «Керак / Колдик» по материалам.
     *
     * Макет «Тайёр маҳсулот»: у товара виден рецепт (RCP-001) с материалами
     * и требуемым количеством; здесь же рецепты создаются и редактируются.
     * Backend-эндпоинты /warehouse/recipes/ и /warehouse/recipe-items/ уже
     * существовали, но UI для них не было.
     */
    async openRecipes(p) {
        const modal = window.ui.modal('warehouse.recipes', `<div id="recipes-body"></div>`);
        const body = modal.querySelector('#recipes-body');

        const load = async () => {
            window.listStates.loading(body, window.ui.t('common.loading'));
            try {
                const [recipesResp, materialsResp] = await Promise.all([
                    window.api.request(`/warehouse/recipes/?product=${p.id}&page_size=100`),
                    window.api.request('/warehouse/raw-materials/?is_archived=false&page_size=200'),
                ]);
                const recipes = recipesResp.results || recipesResp;
                const materials = materialsResp.results || materialsResp;
                const materialMap = Object.fromEntries(materials.map((m) => [String(m.id), m]));

                body.innerHTML = `
                    <button class="btn btn-primary btn-block" id="add-recipe-btn" style="margin-bottom:12px;" data-i18n="warehouse.add_recipe"></button>
                    ${recipes.length ? recipes.map((r) => this.renderRecipeRow(r, materialMap)).join('')
                        : `<div class="card list-state" data-i18n="common.no_data"></div>`}
                `;
                body.querySelector('#add-recipe-btn').addEventListener('click', () => this.openRecipeForm(p));
                body.querySelectorAll('[data-edit-recipe]').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        const recipe = recipes.find((r) => String(r.id) === btn.dataset.editRecipe);
                        this.openRecipeForm(p, recipe);
                    });
                });
                body.querySelectorAll('[data-activate-recipe]').forEach((btn) => {
                    btn.addEventListener('click', async () => {
                        const id = btn.dataset.activateRecipe;
                        try {
                            await window.api.request(`/warehouse/recipes/${id}/`, {
                                method: 'PATCH', body: JSON.stringify({ is_active: true }),
                            });
                            window.toast.success(window.ui.t('common.success'));
                            await load();
                        } catch (error) {
                            window.toast.error(window.ui.errorText(error));
                        }
                    });
                });
                window.i18n.applyTranslations();
            } catch (e) {
                window.listStates.error(body, window.ui.t('common.error'), () => load());
            }
        };
        await load();
    }

    renderRecipeRow(r, materialMap) {
        const items = (r.items || []).map((item) => {
            const m = materialMap[String(item.material)];
            const available = m ? m.available_quantity : null;
            const ok = available !== null && available >= Number(item.quantity_required);
            return `
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm">${window.ui.escape(item.material_name || '-')}</span>
                    <span class="text-sm text-muted">
                        <span data-i18n="warehouse.recipe_required"></span>: ${window.ui.qty(item.quantity_required)} <span data-i18n="units.${item.unit}"></span>
                        ${available !== null
                            ? `· <span data-i18n="warehouse.recipe_available"></span>: <span class="${ok ? '' : 'text-danger'}">${window.ui.qty(available)} <span data-i18n="units.${m.unit}"></span></span>`
                            : ''}
                    </span>
                </div>`;
        }).join('');

        return `
            <div class="card" style="margin-bottom:10px;">
                <div class="card-title" style="margin-bottom:4px;">
                    <span>${window.ui.escape(r.name || r.product_name || '-')}</span>
                    ${r.is_active ? `<span class="badge badge-ready" data-i18n="common.active"></span>` : ''}
                </div>
                ${items ? `<div class="list-group" style="box-shadow:none;border:1px solid #efeff4;">${items}</div>` : ''}
                <div style="display:flex;gap:10px;margin-top:10px;">
                    <button class="btn btn-secondary btn-sm" style="flex:1;" data-edit-recipe="${r.id}" data-i18n="common.edit"></button>
                    ${r.is_active ? '' : `<button class="btn btn-success btn-sm" style="flex:1;" data-activate-recipe="${r.id}" data-i18n="warehouse.recipe_activate"></button>`}
                </div>
            </div>`;
    }

    /** Форма рецепта: название, активность и строки состава (материал + количество). */
    async openRecipeForm(p, recipe = null) {
        const materialsResp = await window.api.request('/warehouse/raw-materials/?is_archived=false&page_size=200');
        const materials = materialsResp.results || materialsResp;

        const itemRow = (item = {}) => `
            <div class="recipe-item-row" style="display:grid;grid-template-columns:1fr 1fr auto;gap:8px;margin-bottom:8px;">
                <select name="material" class="form-control" required>
                    <option value="" data-i18n="common.select"></option>
                    ${materials.map((m) => `<option value="${m.id}" ${String(m.id) === String(item.material || '') ? 'selected' : ''}>${window.ui.escape(m.name)}</option>`).join('')}
                </select>
                <input name="quantity_required" type="number" step="0.001" min="0.001" class="form-control" required
                       placeholder="${window.ui.t('production.quantity')}" value="${item.quantity_required ?? ''}">
                <button type="button" class="icon-btn recipe-item-remove" aria-label="${window.ui.t('common.delete')}">🗑️</button>
            </div>`;

        const modal = window.ui.modal(recipe ? 'common.edit' : 'warehouse.add_recipe', `
            <form id="recipe-form">
                <div class="form-group"><label data-i18n="warehouse.recipe_name"></label>
                    <input name="name" class="form-control" required value="${window.ui.escape(recipe?.name || '')}"></div>
                <div class="form-group">
                    <label style="display:flex;align-items:center;gap:8px;">
                        <input type="checkbox" name="is_active" ${recipe?.is_active ? 'checked' : ''}>
                        <span data-i18n="warehouse.recipe_active"></span>
                    </label>
                </div>
                <div class="form-group"><label data-i18n="warehouse.recipe_items"></label>
                    <div id="recipe-items">${(recipe?.items || []).map((i) => itemRow(i)).join('') || itemRow()}</div>
                    <button type="button" class="btn btn-secondary btn-sm btn-block" id="add-item-row" style="margin-top:6px;" data-i18n="warehouse.recipe_add_item"></button>
                </div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        const addRow = () => {
            const wrap = modal.querySelector('#recipe-items');
            wrap.insertAdjacentHTML('beforeend', itemRow());
            bindRemove();
        };
        const bindRemove = () => {
            modal.querySelectorAll('.recipe-item-remove').forEach((btn) => {
                btn.onclick = () => btn.closest('.recipe-item-row').remove();
            });
        };
        bindRemove();
        modal.querySelector('#add-item-row').addEventListener('click', addRow);

        modal.querySelector('#recipe-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const name = form.querySelector('[name=name]').value.trim();
            const isActive = form.querySelector('[name=is_active]').checked;
            await window.ui.submitGuard(form.querySelector('button[type=submit]'), async () => {
                try {
                    let savedRecipe = recipe;
                    if (recipe) {
                        await window.api.request(`/warehouse/recipes/${recipe.id}/`, {
                            method: 'PATCH', body: JSON.stringify({ name, is_active: isActive }),
                        });
                    } else {
                        const created = await window.api.request('/warehouse/recipes/', {
                            method: 'POST', body: JSON.stringify({ product: p.id, name, is_active: isActive }),
                        });
                        savedRecipe = created;
                    }
                    // Строки состава: обновляем существующие (по id), создаём новые.
                    const rows = [...form.querySelectorAll('.recipe-item-row')];
                    for (const rowEl of rows) {
                        const itemId = rowEl.dataset.itemId;
                        const data = {
                            material: rowEl.querySelector('[name=material]').value,
                            quantity_required: rowEl.querySelector('[name=quantity_required]').value,
                        };
                        if (!data.material) continue;
                        if (itemId) {
                            await window.api.request(`/warehouse/recipe-items/${itemId}/`, {
                                method: 'PATCH', body: JSON.stringify(data),
                            });
                        } else {
                            await window.api.request('/warehouse/recipe-items/', {
                                method: 'POST',
                                body: JSON.stringify({ ...data, recipe: savedRecipe.id }),
                            });
                        }
                    }
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.openRecipes(p);
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
                        <input name="quantity" type="number" step="0.001" min="0" class="form-control"
                               ${p ? 'disabled' : 'required'} value="${p?.quantity ?? ''}">
                        ${p ? `<small class="text-muted" data-i18n="warehouse.quantity_readonly_hint"></small>` : ''}</div>
                    <div class="form-group"><label data-i18n="warehouse.min_stock"></label>
                        <input name="min_stock" type="number" step="0.001" min="0" class="form-control" value="${p?.min_stock ?? 0}"></div>
                </div>
                <div class="form-group">
                    <label data-i18n="warehouse.reserved"></label>
                    <input type="text" class="form-control" value="${window.ui.qty(p?.reserved_for_orders ?? 0)}" disabled>
                    <small class="text-muted" data-i18n="warehouse.reserved_hint"></small>
                </div>
                ${isOwner ? `
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                        <div class="form-group"><label data-i18n="warehouse.cost_price"></label>
                            <input name="cost_price" type="number" step="0.01" min="0" class="form-control" value="${p?.cost_price ?? 0}"></div>
                        <div class="form-group"><label data-i18n="warehouse.sale_price"></label>
                            <input name="sale_price" type="number" step="0.01" min="0" class="form-control" value="${p?.sale_price ?? 0}"></div>
                    </div>
                    <div class="form-group"><label data-i18n="finance.labor_rate_per_unit"></label>
                        <input name="labor_rate" type="number" step="0.01" min="0" class="form-control"
                               value="${p?.labor_rate ?? ''}">
                        <small class="text-muted" data-i18n="finance.labor_rate_hint"></small></div>` : ''}
                <div class="form-group"><label data-i18n="warehouse.description"></label>
                    <textarea name="description" class="form-control" rows="2">${window.ui.escape(p?.description || '')}</textarea></div>
                <div class="form-group"><label data-i18n="warehouse.photo"></label>
                    <input name="photo" type="file" accept="image/*" class="form-control">
                    ${p?.photo ? `<small class="text-muted" data-i18n="warehouse.photo_replace_hint"></small>` : ''}</div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#product-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            // formBody сам выберет multipart, если приложили фото: JSON.stringify
            // выбрасывал файл, и картинка не доходила до сервера.
            const body = await window.ui.formBody(e.target);
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (p) {
                        await window.api.request(`/warehouse/finished-products/${p.id}/`, {
                            method: 'PATCH', body,
                        });
                    } else {
                        await window.api.request('/warehouse/finished-products/', {
                            method: 'POST', body,
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
