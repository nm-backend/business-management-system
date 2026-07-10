/**
 * WarehouseComponent - Хом ашё омбори
 */
class WarehouseComponent {
    async render(container) {
        document.getElementById('page-title').textContent = 'Хом ашё омбори';
        
        container.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <div class="tabs" style="display: flex; overflow-x: auto; gap: 10px; padding-bottom: 5px;">
                    <button class="btn btn-primary" style="padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px;">Барча</button>
                    <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Мрамор</button>
                    <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Тош</button>
                    <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Бошқалар</button>
                </div>
                <span class="nav-icon" style="font-size: 20px; color: var(--text-muted); margin-left: 10px;">🔍</span>
            </div>
            
            <h4 style="font-size: 14px; font-weight: 600; margin: 15px 0 10px;">Мрамор (слэблар)</h4>
            <div id="materials-list">
                <div style="text-align: center; padding: 20px; color: var(--text-muted);">Загрузка...</div>
            </div>
        `;

        await this.loadMaterials();
    }

    async loadMaterials() {
        const listContainer = document.getElementById('materials-list');
        try {
            const data = await window.api.request('/api/v1/warehouse/raw-materials/');
            const materials = data.results || data;
            
            if (materials.length === 0) {
                listContainer.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">Материаллар йўқ</div>`;
                return;
            }

            listContainer.innerHTML = materials.map(m => this.renderMaterialItem(m)).join('');
        } catch (error) {
            listContainer.innerHTML = `<div class="alert-box">Ошибка загрузки склада</div>`;
        }
    }

    renderMaterialItem(material) {
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #e5e5ea;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div style="width: 40px; height: 40px; background-color: #e5e5ea; border-radius: 8px; flex-shrink: 0;">
                        ${material.photo ? `<img src="${material.photo}" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">` : ''}
                    </div>
                    <div>
                        <div style="font-size: 14px; font-weight: 600;">${material.name}</div>
                        <div style="font-size: 12px; color: var(--text-muted);">${material.size || 'Размер не указан'}</div>
                    </div>
                </div>
                <div style="font-size: 15px; font-weight: 600; color: ${material.is_low_stock ? 'var(--danger-color)' : 'inherit'}">
                    ${material.quantity} ${material.unit_display || material.unit}
                </div>
            </div>
        `;
    }
}

window.WarehouseComponent = new WarehouseComponent();
