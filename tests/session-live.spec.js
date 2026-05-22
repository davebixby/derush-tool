// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sebastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';
const TEST_PROJECT = process.env.DERUSH_TEST_PROJECT || 'Drift_Club';

test.describe('Session live (leader / follower)', () => {
    test.skip(!TEST_PASS, 'DERUSH_TEST_PASS non défini');

    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        await expect(page.locator('#screenProjects')).toBeVisible();
        const projectItem = page.locator('.proj-item', { hasText: TEST_PROJECT }).first();
        if (await projectItem.count() > 0) await projectItem.click();
        else await page.locator('.proj-item').first().click();
        await expect(page.locator('#wsProjName')).toBeVisible({ timeout: 10000 });
    });

    test('bouton session affiche initialement "Diriger la session"', async ({ page }) => {
        const btn = page.locator('#sessionBtn');
        await expect(btn).toBeVisible();
        await expect(btn).toContainText('Diriger la session');
    });

    test('endpoint /session/state retourne le leader courant', async ({ request, page }) => {
        const pid = await page.evaluate(() => currentProjectId);
        const r = await request.get(`/api/project/${pid}/session/state`);
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d).toHaveProperty('leader');
    });

    test('start_leading → bouton devient "Arrêter de diriger"', async ({ page }) => {
        const btn = page.locator('#sessionBtn');
        await btn.click();
        // Attendre que le state se propage via WS
        await expect(btn).toContainText('Arrêter de diriger', { timeout: 3000 });
        // Cleanup : stop leading
        await btn.click();
        await expect(btn).toContainText('Diriger la session', { timeout: 3000 });
    });

    test('un 2e onglet voit le leader et peut suivre', async ({ browser, page, request }) => {
        const pid = await page.evaluate(() => currentProjectId);
        // Onglet 1 : devient leader
        await page.locator('#sessionBtn').click();
        await expect(page.locator('#sessionBtn')).toContainText('Arrêter de diriger', { timeout: 3000 });

        // Onglet 2 : nouveau contexte (= autre browser instance)
        const ctx2 = await browser.newContext();
        const page2 = await ctx2.newPage();
        await page2.goto('/');
        await page2.fill('#loginUser', TEST_USER);
        await page2.fill('#loginPass', TEST_PASS);
        await page2.getByRole('button', { name: 'Se connecter' }).click();
        await expect(page2.locator('#screenProjects')).toBeVisible();
        const projItem = page2.locator('.proj-item', { hasText: TEST_PROJECT }).first();
        if (await projItem.count() > 0) await projItem.click();
        else await page2.locator('.proj-item').first().click();
        await expect(page2.locator('#wsProjName')).toBeVisible({ timeout: 10000 });

        // Le 2e onglet devrait voir le leader = Sebastien
        const btn2 = page2.locator('#sessionBtn');
        await expect(btn2).toContainText(/Suivre|Arrêter/, { timeout: 5000 });

        // Cleanup
        await ctx2.close();
        await page.locator('#sessionBtn').click();  // stop leading
        await expect(page.locator('#sessionBtn')).toContainText('Diriger la session', { timeout: 3000 });
    });

    test('start_leading sans auth retourne 401/403', async ({ request, page }) => {
        const pid = await page.evaluate(() => currentProjectId);
        // Pas d'header Authorization
        const r = await request.post(`/api/project/${pid}/session/start_leading`);
        expect([401, 403]).toContain(r.status());
    });
});
