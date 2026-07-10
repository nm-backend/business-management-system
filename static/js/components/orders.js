/**
 * OrdersComponent - Управление заказами
 */
class OrdersComponent {
    async render(container) {
        document.getElementById('page-title').textContent = 'Буюртмалар';
        
        container.innerHTML = `
            <div class="tabs" style="display: flex; overflow-x: auto; margin-bottom: 15px; padding-bottom: 5px; gap: 10px;">
                <button class="btn btn-primary" style="padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px;">Барчаси</button>
                <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Янги</button>
                <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Иш жараёнида</button>
                <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Тайёр</button>
                <button class="btn" style="background: transparent; color: var(--text-muted); padding: 6px 12px; font-size: 13px; width: auto; border-radius: 20px; border: 1px solid #e5e5ea;">Бекор</button>
            </div>
            
            <div id="orders-list">
                <div style="text-align: center; padding: 20px; color: var(--text-muted);">Загрузка...</div>
            </div>
        `;

        await this.loadOrders();
    }

    async loadOrders() {
        const listContainer = document.getElementById('orders-list');
        try {
            const response = await window.api.request('/api/v1/orders/orders/');
            const orders = response.results || response;
            
            if (orders.length === 0) {
                listContainer.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">Буюртмалар йўқ</div>`;
                return;
            }

            listContainer.innerHTML = orders.map(order => this.renderOrderCard(order)).join('');
        } catch (error) {
            listContainer.innerHTML = `<div class="alert-box">Ошибка загрузки заказов</div>`;
        }
    }

    renderOrderCard(order) {
        let badgeClass = 'badge-new';
        let statusText = 'Янги';
        if (order.status === 'in_progress') { badgeClass = 'badge-progress'; statusText = 'Иш жараёнида'; }
        if (order.status === 'ready') { badgeClass = 'badge-ready'; statusText = 'Тайёр'; }
        if (order.status === 'cancelled') { badgeClass = 'badge-cancel'; statusText = 'Бекор'; }

        // Material shortage warning
        let shortageWarning = '';
        if (order.has_material_shortage) {
            shortageWarning = `<div style="color: var(--danger-color); font-size: 12px; font-weight: 500; margin-top: 8px;">⚠️ Материал етарли эмас</div>`;
        }

        return `
            <div class="card">
                <div class="card-title" style="margin-bottom: 4px;">
                    <span>#${order.id} ${order.client_name}</span>
                    <span class="badge ${badgeClass}">${statusText}</span>
                </div>
                <div style="font-size: 13px; color: var(--text-muted);">
                    ${order.product_name || order.custom_product_name} - ${order.quantity} ${order.unit}
                </div>
                ${shortageWarning}
                <div style="font-size: 11px; color: #a1a1aa; margin-top: 10px; text-align: right;">
                    ${new Date(order.created_at).toLocaleDateString()}
                </div>
            </div>
        `;
    }
}

window.OrdersComponent = new OrdersComponent();
