// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sébastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';

test.describe('Changelog modal', () => {
    test.skip(!TEST_PASS, 'DERUSH_TEST_PASS non défini');

    test('la modal Nouveautés s\'ouvre via le lien footer et liste les versions', async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        await expect(page.locator('#screenProjects')).toBeVisible();

        // Clique sur le lien Nouveautés
        await page.getByRole('link', { name: '📜 Nouveautés' }).click();
        await expect(page.locator('#changelogModal')).toBeVisible();
        // Contenu chargé (au moins un h3 version)
        await expect(page.locator('#changelogBody h3').first()).toBeVisible();
        // Fermer
        await page.getByRole('button', { name: 'Fermer' }).first().click();
        await expect(page.locator('#changelogModal')).toBeHidden();
    });

    test('auto-open quand version diff de la dernière vue', async ({ page }) => {
        // Stub localStorage pour simuler une ancienne version vue
        await page.addInitScript(() => {
            localStorage.setItem('derush_last_seen_version', '0.0.1');
        });
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        // La modal doit s'ouvrir auto
        await expect(page.locator('#changelogModal')).toBeVisible({ timeout: 5000 });
    });
});
