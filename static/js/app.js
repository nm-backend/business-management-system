document.addEventListener('DOMContentLoaded', async () => {
    // Check auth
    try {
        const user = await window.api.getMe();
        document.getElementById('user-info').textContent = user.full_name || user.username;
        
        // Hide certain links based on role
        if (!user.is_owner && !user.is_admin) {
            // Worker view - hide items that workers shouldn't see
            const financeLink = document.querySelector('[href="#/finance"]');
            if(financeLink) financeLink.parentElement.style.display = 'none';
        }
    } catch (e) {
        // API client handles redirect to login
        return;
    }

    document.getElementById('logout-btn').addEventListener('click', () => {
        window.api.logout();
    });

    // Register routes
    window.router.addRoute('/', window.DashboardComponent);
    window.router.addRoute('/warehouse', window.WarehouseComponent);
    window.router.addRoute('/finished-products', window.FinishedProductsComponent);
    window.router.addRoute('/clients', window.ClientsComponent);
    window.router.addRoute('/orders', window.OrdersComponent);
    window.router.addRoute('/production', window.ProductionComponent);
    window.router.addRoute('/finance', window.FinanceComponent);
    window.router.addRoute('/messages', window.MessagesComponent);
    
    // Initial route
    window.router.handleRoute();

    // Highlight active nav link
    const updateActiveNav = () => {
        const hash = window.location.hash || '#/';
        document.querySelectorAll('.nav-link').forEach(link => {
            link.style.opacity = link.getAttribute('href') === hash ? '1' : '0.7';
        });
    };
    
    window.addEventListener('hashchange', updateActiveNav);
    updateActiveNav();
});
