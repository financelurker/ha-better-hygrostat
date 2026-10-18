// Take README screenshots from the local demo instance.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');

const BASE = 'http://127.0.0.1:8123';
const OUT = process.argv[2] || 'out';
const ONLY = process.argv[3] ? process.argv[3].split(',') : null;
const session = JSON.parse(fs.readFileSync('session.json', 'utf8'));
fs.mkdirSync(OUT, { recursive: true });

const want = (name) => !ONLY || ONLY.includes(name);

async function login(page) {
  await page.goto(BASE + '/');
  await page.waitForSelector('input[name="username"], ha-auth-flow', { timeout: 30000 });
  await page.locator('input[name="username"]').fill('demo');
  await page.locator('input[name="password"]').fill('demo-pass-2026');
  await page.keyboard.press('Enter');
  await page.waitForURL(/lovelace|home|overview/, { timeout: 30000 });
}

async function settle(page, ms = 2500) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function moreInfo(page, entityId) {
  await page.evaluate((id) => {
    const ha = document.querySelector('home-assistant');
    ha.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: id }, bubbles: true, composed: true }));
  }, entityId);
  await settle(page, 3000);
}

async function shotDialog(page, file) {
  // crop to the dialog surface if we can find it, else the full viewport
  const candidates = ['wa-dialog [part="dialog"]', 'ha-dialog .mdc-dialog__surface', 'ha-md-dialog'];
  for (const sel of candidates) {
    const all = page.locator(sel);
    const n = await all.count();
    for (let i = 0; i < n; i++) {
      const box = await all.nth(i).boundingBox();
      if (box && box.width > 100 && box.height > 100) {
        const vp = page.viewportSize();
        const clip = {
          x: Math.max(0, box.x), y: Math.max(0, box.y),
          width: Math.min(vp.width - Math.max(0, box.x), box.width),
          height: Math.min(vp.height - Math.max(0, box.y), box.height),
        };
        await page.screenshot({ path: `${OUT}/${file}`, clip });
        console.log('dialog', file, sel, JSON.stringify(clip));
        return;
      }
    }
  }
  await page.screenshot({ path: `${OUT}/${file}` });
  console.log('dialog (full)', file);
}

async function clickText(page, text) {
  await page.getByText(text, { exact: true }).first().click({ force: true });
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-proxy-server'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 2, colorScheme: 'light' });
  const page = await ctx.newPage();
  await login(page);

  if (want('dashboard')) {
    await page.goto(BASE + '/office-demo/office');
    await settle(page, 5000);
    await page.screenshot({ path: `${OUT}/dashboard.png` });
    console.log('dashboard');
  }

  if (want('more-info')) {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto(BASE + '/office-demo/office');
    await settle(page);
    await moreInfo(page, 'humidifier.office');
    await shotDialog(page, 'more-info.png');
    await page.keyboard.press('Escape');
  }

  if (want('device')) {
    await page.setViewportSize({ width: 1400, height: 1500 });
    await page.goto(`${BASE}/config/devices/device/${session.device_id}`);
    await settle(page, 5000);
    await page.screenshot({ path: `${OUT}/device.png` });
    console.log('device');
  }

  if (want('config-flow')) {
    await page.setViewportSize({ width: 1400, height: 1100 });
    await page.goto(`${BASE}/config/integrations/dashboard/add?domain=better_hygrostat`);
    await settle(page, 4000);
    // "Do you want to set up Better Hygrostat?" -> OK
    const ok = page.getByRole('button', { name: /^ok$/i }).first();
    if (await ok.count()) { await ok.click({ force: true }); await settle(page, 3000); }
    await shotDialog(page, 'config-flow.png');
    await page.keyboard.press('Escape');
  }

  if (want('options')) {
    await page.setViewportSize({ width: 1400, height: 1300 });
    await page.goto(`${BASE}/config/integrations/integration/better_hygrostat`);
    await settle(page, 3000);
    const btn = page.getByRole('button', { name: /configure/i }).first();
    if (await btn.count()) {
      await btn.click({ force: true });
    } else {
      await page.locator('ha-icon-button[label*="Configure" i], ha-button:has-text("Configure")').first().click();
    }
    await settle(page, 2500);
    await shotDialog(page, 'options-menu.png');
    for (const [label, file] of [
      ['Windows & doors', 'options-windows.png'],
      ['Season & condensation', 'options-season.png'],
      ['Maintenance & Home Keeper', 'options-maintenance.png'],
    ]) {
      await clickText(page, label);
      await settle(page, 2500);
      await shotDialog(page, file);
      await page.getByRole('button', { name: /^(submit|next)$/i }).first().click({ force: true });
      await settle(page, 2000);
    }
    await page.keyboard.press('Escape');
  }

  if (want('home-keeper')) {
    await page.setViewportSize({ width: 1400, height: 800 });
    await page.goto(`${BASE}/home-keeper`);
    await settle(page, 5000);
    await page.screenshot({ path: `${OUT}/home-keeper-tasks.png` });
    console.log('home-keeper tasks');
  }

  if (want('mobile')) {
    const m = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, colorScheme: 'light', isMobile: true, hasTouch: true });
    const mp = await m.newPage();
    await login(mp);
    await mp.goto(BASE + '/office-demo/office');
    await settle(mp, 5000);
    await mp.screenshot({ path: `${OUT}/dashboard-mobile.png` });
    console.log('mobile');
  }

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
