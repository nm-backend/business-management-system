/**
 * Full Multi-Role Pixel-by-Pixel Responsive Scanner
 * Tests SuperAdmin, Owner, Admin, and Worker across 1920 -> 320 px.
 */
const { chromium } = require('@playwright/test');

const BASE_URL = 'http://127.0.0.1:8000';

async function scanViewportOverflow(page, widths, routeName) {
  const overflows = [];
  for (const w of widths) {
    await page.setViewportSize({ width: w, height: 800 });
    const overflowInfo = await page.evaluate((width) => {
      const doc = document.documentElement;
      const body = document.body;
      const scrollW = Math.max(doc.scrollWidth, body.scrollWidth);
      const clientW = window.innerWidth;
      const diff = scrollW - clientW;
      if (diff > 1) {
        const allEls = Array.from(document.querySelectorAll('*'));
        const culprits = [];
        for (const el of allEls) {
          const r = el.getBoundingClientRect();
          if (r.right > clientW + 1) {
            culprits.push({
              tag: el.tagName,
              id: el.id,
              className: el.className,
              right: Math.round(r.right),
              excess: Math.round(r.right - clientW),
            });
          }
        }
        return {
          width,
          scrollW,
          clientW,
          diff: Math.round(diff),
          culprits: culprits.slice(0, 3),
        };
      }
      return null;
    }, w);

    if (overflowInfo) {
      overflows.push(overflowInfo);
    }
  }
  return overflows;
}

async function testRole(browser, username, password, roleName, routes, widths) {
  console.log(`\n=== TESTING ROLE: ${roleName} (${username}) ===`);
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto(`${BASE_URL}/accounts/login/`, { waitUntil: 'networkidle' });
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('#login-form button[type="submit"]');
  await page.waitForFunction(() => window.location.pathname === '/' && !!window.currentUser, { timeout: 10000 });
  await page.waitForTimeout(800);

  let totalOverflows = 0;
  for (const route of routes) {
    await page.evaluate((h) => { window.location.hash = h; }, route);
    await page.waitForTimeout(500);
    const overflows = await scanViewportOverflow(page, widths, route);
    if (overflows.length > 0) {
      console.log(`  Route "${route}": ${overflows.length} overflow points! First at ${overflows[0].width}px (excess: ${overflows[0].diff}px)`);
      totalOverflows += overflows.length;
    } else {
      console.log(`  Route "${route}": OK (0 overflow)`);
    }
  }

  await context.close();
  return totalOverflows;
}

async function run() {
  const browser = await chromium.launch({ headless: true });

  const widthsSet = new Set([
    1920, 1600, 1440, 1366, 1280, 1024, 768, 640, 585, 560, 480, 440, 430, 414, 390, 375, 360, 320
  ]);
  for (let w = 1920; w >= 320; w -= 10) {
    widthsSet.add(w);
  }
  const widths = Array.from(widthsSet).sort((a, b) => b - a);

  console.log(`Scanning across ${widths.length} viewport widths (1920px -> 320px)...`);

  let grandTotal = 0;

  // 1. Superadmin
  grandTotal += await testRole(
    browser, 'root', 'DemoPass123!', 'Superadmin',
    ['#/', '#/companies', '#/messages', '#/settings'],
    widths
  );

  // 2. Owner
  grandTotal += await testRole(
    browser, 'demo_owner', 'DemoPass123!', 'Owner',
    ['#/', '#/orders', '#/warehouse', '#/finished-products', '#/clients', '#/production', '#/sales', '#/finance', '#/messages', '#/subscription', '#/settings'],
    widths
  );

  // 3. Admin
  grandTotal += await testRole(
    browser, 'demo_admin', 'DemoPass123!', 'Admin',
    ['#/', '#/orders', '#/warehouse', '#/finished-products', '#/clients', '#/production', '#/messages', '#/subscription', '#/settings'],
    widths
  );

  // 4. Worker
  grandTotal += await testRole(
    browser, 'demo_worker', 'DemoPass123!', 'Worker',
    ['#/', '#/production', '#/warehouse', '#/messages', '#/settings'],
    widths
  );

  console.log(`\n==============================================`);
  console.log(`GRAND TOTAL OVERFLOW DEFECTS ACROSS ALL ROLES: ${grandTotal}`);
  console.log(`==============================================`);

  await browser.close();
}

run().catch(console.error);
