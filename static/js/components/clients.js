/**
 * ClientsComponent - Мижозлар
 */
class ClientsComponent {
    async render(container) {
        document.getElementById('page-title').textContent = 'Мижозлар архиви';
        
        container.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <div style="position: relative; width: 80%;">
                    <input type="text" class="form-control" placeholder="Қидириш..." style="padding-left: 35px; border-radius: 20px;">
                    <span style="position: absolute; left: 12px; top: 12px; font-size: 14px;">🔍</span>
                </div>
                <span class="nav-icon" style="font-size: 20px; color: var(--text-muted);">⚡</span>
            </div>
            
            <div id="clients-list">
                <div style="text-align: center; padding: 20px; color: var(--text-muted);">Загрузка...</div>
            </div>
        `;

        await this.loadClients();
    }

    async loadClients() {
        const listContainer = document.getElementById('clients-list');
        try {
            const data = await window.api.request('/api/v1/clients/clients/');
            const clients = data.results || data;
            
            if (clients.length === 0) {
                listContainer.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">Мижозлар йўқ</div>`;
                return;
            }

            listContainer.innerHTML = clients.map(client => this.renderClientCard(client)).join('');
        } catch (error) {
            listContainer.innerHTML = `<div class="alert-box">Ошибка загрузки клиентов</div>`;
        }
    }

    renderClientCard(client) {
        // According to mockup: if unpaid, badge is red "Тўлови мавжуд (архив)" or active
        // If paid, green "Тўлови ёпилган"
        let badgeColor = client.has_debt ? 'var(--danger-color)' : 'var(--success-color)';
        let badgeText = client.has_debt ? 'Тўлови мавжуд' : 'Тўлови ёпилган';
        let bgLight = client.has_debt ? '#ffebeb' : '#e5f7ed';

        // Debt value only visible to Owner
        let debtDisplay = client.total_debt !== undefined 
            ? `<div style="font-size: 16px; font-weight: 700; margin-top: 4px;">${client.total_debt} сўм</div>` 
            : '';

        return `
            <div class="card" style="border-left: 4px solid ${badgeColor};">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="font-size: 15px; font-weight: 600;">${client.name}</div>
                        ${debtDisplay}
                        <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">
                            Охирги фаолият: ${new Date(client.updated_at).toLocaleDateString()}
                        </div>
                    </div>
                    <div style="background-color: ${bgLight}; color: ${badgeColor}; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">
                        ${badgeText}
                    </div>
                </div>
            </div>
        `;
    }
}

window.ClientsComponent = new ClientsComponent();
