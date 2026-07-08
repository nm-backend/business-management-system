class DashboardComponent {
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="dashboard.welcome">Welcome</h1>
                <select id="lang-select-dash" class="form-control" style="width: auto;">
                    <option value="uz_cyrl">Ўзбекча</option>
                    <option value="ru">Русский</option>
                </select>
            </header>
            <div class="card">
                <h3 data-i18n="dashboard.business_overview">Business Overview</h3>
                <p>Dashboard is under construction.</p>
            </div>
        `;

        const langSelect = container.querySelector('#lang-select-dash');
        langSelect.value = window.i18n.currentLang;
        langSelect.addEventListener('change', (e) => {
            window.i18n.setLanguage(e.target.value);
        });
    }
}

window.DashboardComponent = new DashboardComponent();
