// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sebastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';
const TEST_PROJECT = process.env.DERUSH_TEST_PROJECT || 'Drift_Club';

test.describe('Auto-détection plans', () => {
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

    test('bouton 🔍 Auto-plans ouvre le modal config', async ({ page }) => {
        await page.getByText('🔍 Auto-plans').click();
        await expect(page.locator('#autoDetectModal')).toBeVisible();
        // Slider sensibilité présent avec valeur défaut 0.25
        await expect(page.locator('#adThresh')).toBeVisible();
        await expect(page.locator('#adThreshVal')).toHaveText('0.25');
        // Bouton Lancer
        await expect(page.locator('#adStartBtn')).toBeVisible();
        // Fermer
        await page.getByRole('button', { name: 'Fermer' }).first().click();
        await expect(page.locator('#autoDetectModal')).toBeHidden();
    });

    test('slider sensibilité met à jour la valeur affichée', async ({ page }) => {
        await page.getByText('🔍 Auto-plans').click();
        const slider = page.locator('#adThresh');
        // Évalue côté browser : set value + dispatch input event
        await slider.evaluate(el => {
            el.value = '0.50';
            el.dispatchEvent(new Event('input'));
        });
        await expect(page.locator('#adThreshVal')).toHaveText('0.50');
    });

    test('endpoint /auto_detect retourne un objet', async ({ request, page }) => {
        // currentProjectId est en `let` au top-level → pas accessible via window.X
        // mais accessible directement dans page.evaluate() qui s'exécute dans le scope global
        const pid = await page.evaluate(() => currentProjectId);
        expect(pid).toBeTruthy();  // sanity check
        const r = await request.get(`/api/project/${pid}/auto_detect`);
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d).toHaveProperty('auto_detected');
        expect(typeof d.auto_detected).toBe('object');
    });

    test('endpoint /auto_detect/status retourne un statut', async ({ request, page }) => {
        const pid = await page.evaluate(() => currentProjectId);
        const r = await request.get(`/api/project/${pid}/auto_detect/status`);
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d).toHaveProperty('status');
        expect(['idle', 'running', 'done', 'error']).toContain(d.status);
    });
});
