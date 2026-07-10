/**
 * FinishedProductsComponent - страница готовой продукции.
 * Отображает список товаров с учетом резервов под заказы.
 */
class FinishedProductsComponent {
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="warehouse.finished_title">Тайёр маҳсулот</h1>
                <button id="add-product-btn" class="btn btn-primary" data-i18n="warehouse.add_product">Добавить товар</button>
            </header>

            <div class="card" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 2px solid #eee;">
                            <th style="padding: 10px;" data-i18n="warehouse.name">Название</th>
                            <th style="padding: 10px;" data-i18n="warehouse.category">Категория</th>
                            <th style="padding: 10px;" data-i18n="warehouse.quantity">Количество</th>
                            <th style="padding: 10px;" data-i18n="warehouse.reserved">Резерв</th>
                            <th style="padding: 10px;" data-i18n="warehouse.unit">Единица</th>
                        </tr>
                    </thead>
                    <tbody id="products-list">
                        <tr><td colspan="5" style="padding: 10px; text-align: center;" data-i18n="common.loading">Загрузка...</td></tr>
                    </tbody>
                </table>
            </div>
        `;

        await this.loadProducts(container);
    }

    async loadProducts(container) {
        const listEl = container.querySelector('#products-list');
        window.listStates.tableLoading(listEl, 5);
        try {
            const data = await window.api.request('/warehouse/finished-products/');

            if (data.results && data.results.length > 0) {
                listEl.innerHTML = data.results.map(p => `
                    <tr style="border-bottom: 1px solid #eee; ${p.is_low_stock ? 'background-color: #ffebee;' : ''}">
                        <td style="padding: 10px;">${p.name}</td>
                        <td style="padding: 10px;">${p.category}</td>
                        <td style="padding: 10px; font-weight: bold; color: ${p.is_low_stock ? 'red' : 'inherit'}">${p.available_quantity}</td>
                        <td style="padding: 10px;">${p.reserved_for_orders}</td>
                        <td style="padding: 10px;">${p.unit_display}</td>
                    </tr>
                `).join('');
            } else {
                window.listStates.tableEmpty(listEl, 5, 'No finished products found');
                window.i18n.applyTranslations();
            }
        } catch (e) {
            console.error('Failed to load products', e);
            window.listStates.tableError(listEl, 5, 'Unable to load products', () => this.loadProducts(container));
            window.i18n.applyTranslations();
        }
    }
}

window.FinishedProductsComponent = new FinishedProductsComponent();
