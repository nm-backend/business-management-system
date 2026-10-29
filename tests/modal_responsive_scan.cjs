/**
 * Modal & Form responsiveness and overflow scanner.
 * Opens all major modals on mobile (320px, 375px) and desktop (1280px)
 * and verifies that the modal fits in the viewport without horizontal overflow.
 */
const { chromium } = require('@playwright/test');

const BASE_URL = 'http://127.0.0.1:8000';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 375, height: 667 } });
  const page = await context.newPage();

  // Login as demo_owner
  await page.goto(`${BASE_URL}/accounts/login/`, { waitUntil: 'networkidle' });
  await page.fill('#username', 'demo_owner');
  await page.fill('#password', 'DemoPass123!');
  await page.click('#login-form button[type="submit"]');
  await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser);
  await page.waitForTimeout(500);

  const viewports = [
    { name: 'Mobile 320px', width: 320, height: 667 },
    { name: 'Mobile 375px', width: 375, height: 667 },
    { name: 'Desktop 1280px', width: 1280, height: 800 },
  ];

  console.log('=== TESTING MODALS AT DIFFERENT VIEWPORTS ===');

  for (const vp of viewports) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    console.log(`\nTesting at ${vp.name} (${vp.width}x${vp.height}):`);

    // 1. Order Form Modal
    await page.evaluate(() => { window.location.hash = '#/orders'; });
    await page.waitForTimeout(500);
    const addOrderBtn = await page.$('#add-order-btn');
    if (addOrderBtn) {
      await addOrderBtn.click();
      await page.waitForSelector('#order-form', { timeout: 3000 });
      const modalBox = await page.evaluate(() => {
        const modal = document.querySelector('.modal-content');
        if (!modal) return null;
        const r = modal.getBoundingClientRect();
        return {
          left: Math.round(r.left),
          right: Math.round(r.right),
          width: Math.round(r.width),
          viewportWidth: window.innerWidth,
          overflow: r.right > window.innerWidth || r.left < 0,
        };
      });
      console.log('  Order Modal:', modalBox);
      await page.click('.modal .close');
      await page.waitForTimeout(300);
    }

    // 2. Raw Material Modal
    await page.evaluate(() => { window.location.hash = '#/warehouse'; });
    await page.waitForTimeout(500);
    const addMatBtn = await page.$('#add-material-btn');
    if (addMatBtn) {
      await addMatBtn.click();
      await page.waitForSelector('#material-form', { timeout: 3000 });
      const modalBox = await page.evaluate(() => {
        const modal = document.querySelector('.modal-content');
        if (!modal) return null;
        const r = modal.getBoundingClientRect();
        return {
          left: Math.round(r.left),
          right: Math.round(r.right),
          width: Math.round(r.width),
          viewportWidth: window.innerWidth,
          overflow: r.right > window.innerWidth || r.left < 0,
        };
      });
      console.log('  Material Modal:', modalBox);
      await page.click('.modal .close');
      await page.waitForTimeout(300);
    }

    // 3. Client Modal
    await page.evaluate(() => { window.location.hash = '#/clients'; });
    await page.waitForTimeout(500);
    const addClientBtn = await page.$('#add-client-btn');
    if (addClientBtn) {
      await addClientBtn.click();
      await page.waitForSelector('#client-form', { timeout: 3000 });
      const modalBox = await page.evaluate(() => {
        const modal = document.querySelector('.modal-content');
        if (!modal) return null;
        const r = modal.getBoundingClientRect();
        return {
          left: Math.round(r.left),
          right: Math.round(r.right),
          width: Math.round(r.width),
          viewportWidth: window.innerWidth,
          overflow: r.right > window.innerWidth || r.left < 0,
        };
      });
      console.log('  Client Modal:', modalBox);
      await page.click('.modal .close');
      await page.waitForTimeout(300);
    }
  }

  await browser.close();
  console.log('\n=== MODAL TESTS COMPLETED ===');
}

run().catch(console.error);
