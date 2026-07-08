class WarehouseComponent {
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="warehouse.title">Склад сырья</h1>
                <button id="add-material-btn" class="btn btn-primary" data-i18n="warehouse.add_material">Добавить материал</button>
            </header>
            
            <div class="card" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 2px solid #eee;">
                            <th style="padding: 10px;" data-i18n="warehouse.name">Название</th>
                            <th style="padding: 10px;" data-i18n="warehouse.stone_type">Тип камня</th>
                            <th style="padding: 10px;" data-i18n="warehouse.quantity">Количество</th>
                            <th style="padding: 10px;" data-i18n="warehouse.unit">Единица</th>
                        </tr>
                    </thead>
                    <tbody id="materials-list">
                        <tr><td colspan="4" style="padding: 10px; text-align: center;" data-i18n="common.loading">Загрузка...</td></tr>
                    </tbody>
                </table>
            </div>
        `;

        await this.loadMaterials(container);
    }

    async loadMaterials(container) {
        const listEl = container.querySelector('#materials-list');
        try {
            const data = await window.api.request('/warehouse/raw-materials/');
            
            if (data.results && data.results.length > 0) {
                listEl.innerHTML = data.results.map(m => `
                    <tr style="border-bottom: 1px solid #eee; ${m.is_low_stock ? 'background-color: #ffebee;' : ''}">
                        <td style="padding: 10px;">${m.name}</td>
                        <td style="padding: 10px;">${m.stone_type}</td>
                        <td style="padding: 10px; font-weight: bold; color: ${m.is_low_stock ? 'red' : 'inherit'}">${m.quantity}</td>
                        <td style="padding: 10px;">${m.unit_display}</td>
                    </tr>
                `).join('');
            } else {
                listEl.innerHTML = `<tr><td colspan="4" style="padding: 10px; text-align: center;" data-i18n="common.no_data">Нет данных</td></tr>`;
                window.i18n.applyTranslations();
            }
        } catch (e) {
            console.error('Failed to load materials', e);
            listEl.innerHTML = `<tr><td colspan="4" style="padding: 10px; text-align: center; color: red;" data-i18n="common.error">Ошибка загрузки</td></tr>`;
            window.i18n.applyTranslations();
        }
    }
}

window.WarehouseComponent = new WarehouseComponent();
