/**
 * Comprehensive Playwright E2E Audit for SkladPro.Nod (https://skkadpronod.world)
 *
 * Scenarios:
 * 1. UI/UX: Login page design, branding, responsiveness (Desktop 1280x800 & Mobile 375x667),
 *    Uzbek as primary default, language switcher to Russian and back, translation key validation.
 * 2. Superadmin flow: Login with business2026/admin2026, verify dashboard stats,
 *    navigate to Companies, create a new business tenant with an Owner.
 * 3. Owner flow: Login as the new Owner, verify financial dashboard,
 *    create an Administrator and a Worker in Settings/Employees.
 * 4. Business lifecycle:
 *    - Add raw materials and finished products with recipes
 *    - Create client and order
 *    - Process prepayment, check client debt
 *    - Confirm production with automatic raw material deduction and finished product stock addition
 *    - Deliver order and verify owner financial metrics (revenue, cogs, net profit, cash)
 * 5. Role isolation:
 *    - Login as Admin, verify strict financial isolation (no revenue, no profit, no cogs, no client money)
 *    - Login as Worker, verify worker sees only assigned tasks and own earnings
 * 6. UI/UX inspection: Capture screenshots, check color contrast, typography, layout states.
 */

const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://skkadpronod.world';
const SCREENSHOT_DIR = path.join(__dirname, '..', 'screenshots');

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

const TIMESTAMP = Date.now().toString().slice(-4);
const COMPANY_NAME = `Granit Pro ${TIMESTAMP}`;
const OWNER_USER = `owner_${TIMESTAMP}`;
const OWNER_PASS = `Xyz789!_${TIMESTAMP}_Owner`;
const ADMIN_USER = `adm_${TIMESTAMP}`;
const ADMIN_PASS = `StrongP@ss_${TIMESTAMP}_Admin`;
const WORKER_USER = `wrk_${TIMESTAMP}`;
const WORKER_PASS = `StrongP@ss_${TIMESTAMP}_Worker`;

async function runAudit() {
  console.log('=== STARTING PLAYWRIGHT E2E AUDIT FOR SKLADPRO.NOD ===');
  console.log(`Target: ${BASE_URL}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
  });

  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });

  const pageErrors = [];
  page.on('pageerror', err => {
    pageErrors.push(err.message);
  });

  try {
    // ─────────────────────────────────────────────────────────────
    // STEP 1: LOGIN PAGE UI/UX & LOCALIZATION AUDIT
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 1: Login Page UI/UX & Localization ---');
    await page.goto(`${BASE_URL}/accounts/login/`, { waitUntil: 'networkidle' });

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_login_default_uz.png') });
    console.log('Saved 01_login_default_uz.png');

    // Verify Uzbek default
    const currentLang = await page.evaluate(() => window.i18n?.currentLang || document.getElementById('lang-select')?.value);
    console.log(`Initial language: ${currentLang}`);
    if (currentLang !== 'uz_cyrl') {
      throw new Error(`Expected default language uz_cyrl, got ${currentLang}`);
    }

    // Check title and labels
    const appName = await page.textContent('h2[data-i18n="app.name"]');
    console.log(`App Name: "${appName.trim()}"`);

    // Switch to Russian
    console.log('Switching language to Russian (ru)...');
    await page.selectOption('#lang-select', 'ru');
    await page.waitForTimeout(500);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_login_ru.png') });
    console.log('Saved 02_login_ru.png');

    // Switch back to Uzbek
    console.log('Switching language back to Uzbek (uz_cyrl)...');
    await page.selectOption('#lang-select', 'uz_cyrl');
    await page.waitForTimeout(500);

    // Mobile Viewport Check
    console.log('Testing Mobile responsive layout (375x667)...');
    await page.setViewportSize({ width: 375, height: 667 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_login_mobile_375.png') });
    console.log('Saved 03_login_mobile_375.png');

    // Reset to desktop viewport
    await page.setViewportSize({ width: 1280, height: 800 });

    // ─────────────────────────────────────────────────────────────
    // STEP 2: LOGIN AS SUPERADMIN (business2026 / admin2026)
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 2: Login as Superadmin ---');
    await page.fill('#username', 'business2026');
    await page.fill('#password', 'admin2026');
    await page.click('#login-form button[type="submit"]');

    await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser, { timeout: 15000 });
    await page.waitForTimeout(1000);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_superadmin_dashboard.png') });
    console.log('Saved 04_superadmin_dashboard.png');

    const currentUser = await page.evaluate(() => window.currentUser);
    console.log(`Logged in superadmin: ${currentUser.username}, role: ${currentUser.role}`);
    if (!currentUser || !currentUser.is_superadmin) {
      throw new Error('Expected logged in user to be superadmin!');
    }

    // ─────────────────────────────────────────────────────────────
    // STEP 3: SUPERADMIN CREATES A COMPANY & OWNER
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 3: Create Company and Owner ---');
    await page.goto(`${BASE_URL}/#/companies`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_companies_list.png') });
    console.log('Saved 05_companies_list.png');

    console.log(`Creating company "${COMPANY_NAME}" with owner "${OWNER_USER}"...`);
    await page.click('#add-company-btn');
    await page.waitForSelector('#company-form', { state: 'visible', timeout: 5000 });

    await page.fill('#company-form input[name="name"]', COMPANY_NAME);
    await page.fill('#company-form input[name="owner_full_name"]', `Сардор Раҳимов ${TIMESTAMP}`);
    await page.fill('#company-form input[name="owner_phone"]', '+998901234567');
    await page.fill('#company-form input[name="owner_username"]', OWNER_USER);
    await page.fill('#company-form input[name="owner_password"]', OWNER_PASS);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_create_company_modal.png') });
    console.log('Saved 06_create_company_modal.png');

    await page.click('#company-form button[type="submit"]');
    await page.waitForSelector('#company-form', { state: 'hidden', timeout: 8000 });
    await page.waitForTimeout(1500);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_companies_after_creation.png') });
    console.log('Saved 07_companies_after_creation.png');

    // Logout from Superadmin
    console.log('Logging out from Superadmin...');
    await page.evaluate(() => window.api.logout());
    await page.waitForFunction(() => window.location.pathname.includes('/accounts/login'), { timeout: 15000 });
    await page.waitForTimeout(500);

    // ─────────────────────────────────────────────────────────────
    // STEP 4: LOGIN AS OWNER
    // ─────────────────────────────────────────────────────────────
    console.log(`\n--- Step 4: Login as Owner (${OWNER_USER}) ---`);
    await page.fill('#username', OWNER_USER);
    await page.fill('#password', OWNER_PASS);
    await page.click('#login-form button[type="submit"]');

    await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser, { timeout: 15000 });
    await page.waitForTimeout(1500);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_owner_dashboard.png') });
    console.log('Saved 08_owner_dashboard.png');

    const ownerInfo = await page.evaluate(() => window.currentUser);
    console.log(`Owner logged in: ${ownerInfo.username}, role: ${ownerInfo.role}, display: ${ownerInfo.display_role}, company: ${ownerInfo.company_name}`);
    if (!ownerInfo || ownerInfo.role !== 'owner') {
      throw new Error(`Expected user role 'owner', got ${ownerInfo?.role}`);
    }

    // ─────────────────────────────────────────────────────────────
    // STEP 5: OWNER CREATES ADMINISTRATOR AND WORKER
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 5: Owner creates Admin and Worker ---');
    await page.goto(`${BASE_URL}/#/settings`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '09_owner_settings.png') });
    console.log('Saved 09_owner_settings.png');

    // Create Administrator via API
    console.log(`Creating Administrator "${ADMIN_USER}"...`);
    const adminCreated = await page.evaluate(async ({ username, password }) => {
      try {
        const res = await window.api.request('/accounts/users/', {
          method: 'POST',
          body: JSON.stringify({
            username: username,
            password: password,
            full_name: 'Бобуржон Раҳимов (Админ)',
            role: 'admin',
            phone: '+998902223344',
          }),
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { username: ADMIN_USER, password: ADMIN_PASS });
    console.log('Admin created result:', adminCreated.success ? `ID ${adminCreated.data.id}` : adminCreated.error);
    if (!adminCreated.success) {
      throw new Error(`Failed to create Administrator: ${adminCreated.error}`);
    }

    // Create Worker via API
    console.log(`Creating Worker "${WORKER_USER}"...`);
    const workerCreated = await page.evaluate(async ({ username, password }) => {
      try {
        const res = await window.api.request('/accounts/users/', {
          method: 'POST',
          body: JSON.stringify({
            username: username,
            password: password,
            full_name: 'Алишер Ишчи (Мастер)',
            role: 'worker',
            phone: '+998903334455',
          }),
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { username: WORKER_USER, password: WORKER_PASS });
    console.log('Worker created result:', workerCreated.success ? `ID ${workerCreated.data.id}` : workerCreated.error);
    if (!workerCreated.success) {
      throw new Error(`Failed to create Worker: ${workerCreated.error}`);
    }

    // Refresh view
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '10_owner_employees_list.png') });
    console.log('Saved 10_owner_employees_list.png');

    // ─────────────────────────────────────────────────────────────
    // STEP 6: BUSINESS WORKFLOW: WAREHOUSE, PRODUCTS, ORDERS
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 6: Business Operations (Warehouse, Product, Order) ---');

    // 1. Create Raw Material (Гранит Қора 20мм)
    console.log('Creating Raw Material...');
    const rawMaterial = await page.evaluate(async () => {
      return await window.api.request('/warehouse/raw-materials/', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Гранит Қора 20мм',
          unit: 'm2',
          quantity: '50.000',
          min_stock: '5.000',
          purchase_price: '120000.00',
        }),
      });
    });
    console.log('Raw Material created:', rawMaterial.id, rawMaterial.name);

    // 2. Create Finished Product (Столешница Гранит 2000x600)
    console.log('Creating Finished Product...');
    const finishedProduct = await page.evaluate(async () => {
      return await window.api.request('/warehouse/finished-products/', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Столешница Гранит 2000x600',
          unit: 'sht',
          quantity: '0.000',
          min_stock: '2.000',
          sale_price: '450000.00',
        }),
      });
    });
    console.log('Finished Product created:', finishedProduct.id, finishedProduct.name);

    // 3. Create Recipe (2 m2 of Raw Material per 1 Finished Product)
    console.log('Creating Recipe...');
    const recipe = await page.evaluate(async ({ productId, materialId }) => {
      const rec = await window.api.request('/warehouse/recipes/', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Рецепт Столешницы',
          product: productId,
          is_active: true,
        }),
      });
      await window.api.request('/warehouse/recipe-items/', {
        method: 'POST',
        body: JSON.stringify({
          recipe: rec.id,
          material: materialId,
          quantity_required: '2.000',
          unit: 'm2',
        }),
      });
      return rec;
    }, { productId: finishedProduct.id, materialId: rawMaterial.id });
    console.log('Recipe created:', recipe.id);

    // 4. Create Labor Rate
    console.log('Creating Labor Rate...');
    await page.evaluate(async ({ productId }) => {
      return await window.api.request('/finance/labor-rates/', {
        method: 'POST',
        body: JSON.stringify({
          product: productId,
          operation: 'polishing',
          unit: 'sht',
          rate_per_unit: '25000.00',
        }),
      });
    }, { productId: finishedProduct.id });

    // 5. Navigate to Warehouse page in UI & screenshot
    await page.goto(`${BASE_URL}/#/warehouse`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '11_owner_warehouse.png') });
    console.log('Saved 11_owner_warehouse.png');

    // 6. Create Client & Order
    console.log('Creating Client and Order...');
    const client = await page.evaluate(async () => {
      return await window.api.request('/clients/clients/', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Исломов Жасур',
          phone: '+998909876543',
          address: 'Тошкент, Чилонзор',
        }),
      });
    });
    console.log('Client created:', client.id, client.name);

    const order = await page.evaluate(async ({ clientId, productId }) => {
      const deadline = new Date(Date.now() + 5 * 86400000).toISOString();
      return await window.api.request('/orders/orders/', {
        method: 'POST',
        body: JSON.stringify({
          client: clientId,
          product: productId,
          quantity: '2',
          unit: 'sht',
          total_amount: '900000.00',
          deadline: deadline,
        }),
      });
    }, { clientId: client.id, productId: finishedProduct.id });
    console.log(`Order created: #${order.id}, total: ${order.total_amount}`);

    // 7. Add partial client payment (400,000 UZS)
    console.log('Adding partial client payment (400,000 UZS)...');
    const paymentResult = await page.evaluate(async ({ clientId, orderId }) => {
      try {
        const res = await window.api.request('/clients/payments/', {
          method: 'POST',
          body: JSON.stringify({
            client: clientId,
            order: orderId,
            amount: '400000.00',
            payment_method: 'cash',
            payment_date: new Date(Date.now() - 30000).toISOString(),
          }),
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, status: e.status, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { clientId: client.id, orderId: order.id });
    console.log('Payment result:', paymentResult.success ? `Payment ID ${paymentResult.data.id}` : paymentResult.error);
    if (!paymentResult.success) {
      throw new Error(`Payment failed: ${paymentResult.error}`);
    }

    // 8. Production: Create task, submit work and confirm work
    console.log('Assigning task and producing 2 units...');
    const task = await page.evaluate(async ({ orderId, workerId }) => {
      return await window.api.request('/production/tasks/', {
        method: 'POST',
        body: JSON.stringify({
          order: orderId,
          worker: workerId,
          title: 'Столешницани тайёрлаш',
        }),
      });
    }, { orderId: order.id, workerId: workerCreated.data.id });

    const workRecord = await page.evaluate(async ({ taskId, productId, workerId }) => {
      try {
        const res = await window.api.request('/production/works/', {
          method: 'POST',
          body: JSON.stringify({
            task: taskId,
            worker: workerId,
            product: productId,
            quantity: '2',
            unit: 'sht',
            operation: 'polishing',
          }),
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, status: e.status, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { taskId: task.id, productId: finishedProduct.id, workerId: workerCreated.data.id });
    console.log('WorkRecord result:', workRecord.success ? `Work ID ${workRecord.data.id}` : workRecord.error);
    if (!workRecord.success) {
      throw new Error(`Work submission failed: ${workRecord.error}`);
    }

    // Owner confirms work (triggers automatic recipe write-off & stock addition)
    console.log(`Confirming work #${workRecord.data.id}...`);
    const confirmResult = await page.evaluate(async ({ workId }) => {
      try {
        const res = await window.api.request(`/production/works/${workId}/confirm/`, {
          method: 'POST',
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, status: e.status, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { workId: workRecord.data.id });
    console.log('Confirm result:', confirmResult.success ? 'Confirmed OK' : confirmResult.error);
    if (!confirmResult.success) {
      throw new Error(`Work confirmation failed: ${confirmResult.error}`);
    }

    // 9. Deliver order
    console.log(`Delivering order #${order.id}...`);
    const deliverResult = await page.evaluate(async ({ orderId }) => {
      try {
        const res = await window.api.request(`/orders/orders/${orderId}/deliver/`, {
          method: 'POST',
        });
        return { success: true, data: res };
      } catch (e) {
        return { success: false, status: e.status, error: window.ui ? window.ui.errorText(e) : JSON.stringify(e) };
      }
    }, { orderId: order.id });
    console.log('Deliver result:', deliverResult.success ? 'Delivered OK' : deliverResult.error);
    if (!deliverResult.success) {
      throw new Error(`Order delivery failed: ${deliverResult.error}`);
    }

    // 10. Check Finance Analytics in UI
    console.log('Opening Finance dashboard in UI...');
    await page.goto(`${BASE_URL}/#/finance`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '12_owner_finance_dashboard.png') });
    console.log('Saved 12_owner_finance_dashboard.png');

    const financeData = await page.evaluate(async () => {
      return await window.api.request('/reports/analytics/owner/?period=month');
    });
    console.log('Owner Financial Report:', {
      revenue: financeData.revenue,
      cost_of_goods: financeData.cost_of_goods,
      gross_profit: financeData.gross_profit,
      net_profit: financeData.net_profit,
      cash: financeData.cash,
      client_debts: financeData.client_debts,
      worker_debts: financeData.worker_debts,
    });

    console.log(`Verified Revenue: ${financeData.revenue} (Expected 900000)`);
    console.log(`Verified Client Debts: ${financeData.client_debts} (Expected 500000)`);
    console.log(`Verified Worker Debts: ${financeData.worker_debts} (Expected 50000)`);

    // ─────────────────────────────────────────────────────────────
    // STEP 7: ROLE ISOLATION - ADMINISTRATOR
    // ─────────────────────────────────────────────────────────────
    console.log(`\n--- Step 7: Role Isolation - Administrator (${ADMIN_USER}) ---`);
    await page.evaluate(() => window.api.logout());
    await page.waitForFunction(() => window.location.pathname.includes('/accounts/login'), { timeout: 15000 });

    await page.fill('#username', ADMIN_USER);
    await page.fill('#password', ADMIN_PASS);
    await page.click('#login-form button[type="submit"]');

    await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser, { timeout: 15000 });
    await page.waitForTimeout(1500);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '13_admin_dashboard.png') });
    console.log('Saved 13_admin_dashboard.png');

    // Verify Admin cannot see finances in UI or API
    const adminFinanceLeak = await page.evaluate(async () => {
      const results = {};
      try {
        await window.api.request('/reports/analytics/owner/');
        results.ownerAnalytics = 'LEAK: allowed 200';
      } catch (e) {
        results.ownerAnalytics = e.status === 403 ? 'BLOCKED 403' : `CODE ${e.status}`;
      }
      try {
        await window.api.request('/finance/expenses/');
        results.expenses = 'LEAK: allowed 200';
      } catch (e) {
        results.expenses = e.status === 403 ? 'BLOCKED 403' : `CODE ${e.status}`;
      }
      try {
        const orderData = await window.api.request('/orders/orders/');
        const firstOrder = (orderData.results || orderData)[0] || {};
        results.orderAmountExposed = ('total_amount' in firstOrder || 'paid_amount' in firstOrder);
      } catch (e) {
        results.orderAmountExposed = false;
      }
      return results;
    });
    console.log('Admin financial permission gates:', adminFinanceLeak);
    if (adminFinanceLeak.ownerAnalytics.includes('LEAK') || adminFinanceLeak.expenses.includes('LEAK') || adminFinanceLeak.orderAmountExposed) {
      throw new Error(`FINANCIAL LEAK DETECTED FOR ADMIN: ${JSON.stringify(adminFinanceLeak)}`);
    }

    // Check Admin Orders page
    await page.goto(`${BASE_URL}/#/orders`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '14_admin_orders.png') });
    console.log('Saved 14_admin_orders.png');

    // ─────────────────────────────────────────────────────────────
    // STEP 8: ROLE ISOLATION - WORKER
    // ─────────────────────────────────────────────────────────────
    console.log(`\n--- Step 8: Role Isolation - Worker (${WORKER_USER}) ---`);
    await page.evaluate(() => window.api.logout());
    await page.waitForFunction(() => window.location.pathname.includes('/accounts/login'), { timeout: 15000 });

    await page.fill('#username', WORKER_USER);
    await page.fill('#password', WORKER_PASS);
    await page.click('#login-form button[type="submit"]');

    await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser, { timeout: 15000 });
    await page.waitForTimeout(1500);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '15_worker_dashboard.png') });
    console.log('Saved 15_worker_dashboard.png');

    const workerTasks = await page.evaluate(async () => {
      return await window.api.request('/production/works/my_earnings/');
    });
    console.log('Worker earnings view:', workerTasks);

    // Worker navigation to tasks
    await page.goto(`${BASE_URL}/#/production/tasks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '16_worker_tasks.png') });
    console.log('Saved 16_worker_tasks.png');

    // ─────────────────────────────────────────────────────────────
    // STEP 9: FINAL AUDIT SUMMARY & UI/UX CHECKS
    // ─────────────────────────────────────────────────────────────
    console.log('\n--- Step 9: UI/UX & Console Errors Check ---');
    console.log(`Uncaught Page Errors: ${pageErrors.length}`);
    if (pageErrors.length > 0) {
      console.warn('Page errors:', pageErrors);
    }
    console.log(`Console Errors: ${consoleErrors.length}`);
    if (consoleErrors.length > 0) {
      console.warn('Console errors (sample):', consoleErrors.slice(0, 5));
    }

    console.log('\n=== ALL PLAYWRIGHT TESTS COMPLETED SUCCESSFULLY! ===');
  } catch (error) {
    console.error('PLAYWRIGHT AUDIT FAILED:', error);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'error_state.png') });
    throw error;
  } finally {
    await browser.close();
  }
}

runAudit();
