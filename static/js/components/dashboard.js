class DashboardComponent {
    async render(container) {
        document.getElementById('page-title').textContent = 'Бош панел';
        
        container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">Загрузка...</div>`;
        
        try {
            const user = await window.api.getMe();
            if (user.is_owner) {
                this.renderOwnerDashboard(container);
            } else if (user.is_admin) {
                this.renderAdminDashboard(container);
            } else {
                this.renderWorkerDashboard(container);
            }
        } catch (error) {
            container.innerHTML = `<div class="alert-box">Ошибка загрузки профиля</div>`;
        }
    }

    renderOwnerDashboard(container) {
        container.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <span class="text-sm text-muted">01.05.2024 - 31.05.2024</span>
                <span class="nav-icon" style="font-size: 16px;">🔽</span>
            </div>
            
            <div class="card" style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <div class="metric-title">Даромад</div>
                    <div class="metric-value">125 750 000 сўм</div>
                </div>
                <div class="text-success font-bold" style="font-size: 13px;">↑ 12.5%</div>
            </div>
            
            <div class="card" style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <div class="metric-title">Соф фойда</div>
                    <div class="metric-value">38 450 000 сўм</div>
                </div>
                <div class="text-success font-bold" style="font-size: 13px;">↑ 18.3%</div>
            </div>
            
            <div class="card" style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <div class="metric-title">Касса қолдиғи</div>
                    <div class="metric-value">42 300 000 сўм</div>
                </div>
                <div class="text-muted font-bold" style="font-size: 18px;">></div>
            </div>
        `;
    }

    renderAdminDashboard(container) {
        container.innerHTML = `
            <div style="margin-bottom: 15px;">
                <h3 style="font-size: 16px; margin-bottom: 5px;">Хуш келибсиз, Админ!</h3>
                <span class="text-sm text-muted">Бугунги кўрсаткичлар</span>
            </div>
            
            <div class="metrics-grid">
                <div class="metric-card green">
                    <div class="metric-title">Янги буюртмалар</div>
                    <div class="metric-value">12</div>
                </div>
                <div class="metric-card yellow">
                    <div class="metric-title">Иш жараёнида</div>
                    <div class="metric-value">7</div>
                </div>
                <div class="metric-card blue">
                    <div class="metric-title">Бугун ишга топширилган</div>
                    <div class="metric-value">23</div>
                </div>
                <div class="metric-card purple">
                    <div class="metric-title">Ишчилар мулоҳазалари</div>
                    <div class="metric-value">17</div>
                </div>
            </div>
            
            <div class="alert-box" style="justify-content: space-between;">
                <span>⚠️ Материал етарли эмас (5 тур)</span>
                <span style="font-size: 16px;">></span>
            </div>
        `;
    }

    renderWorkerDashboard(container) {
        container.innerHTML = `
            <div style="margin-bottom: 15px;">
                <h3 style="font-size: 16px; margin-bottom: 5px;">Ассалому алайкум!</h3>
                <span class="text-sm text-muted">Бугунги вазифаларим</span>
            </div>
            <div class="metrics-grid">
                <div class="metric-card blue">
                    <div class="metric-title">Бугунги соат</div>
                    <div class="metric-value">18 соат</div>
                </div>
                <div class="metric-card green">
                    <div class="metric-title">Вазифалар</div>
                    <div class="metric-value">5 та</div>
                </div>
            </div>
        `;
    }
}

window.DashboardComponent = new DashboardComponent();
