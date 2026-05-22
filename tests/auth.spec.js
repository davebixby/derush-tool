// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sébastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';

test.describe('Auth', () => {
    test.skip(!TEST_PASS, 'DERUSH_TEST_PASS non défini, tests authentifiés skipés');

    test('login fonctionne avec les credentials valides', async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        // Une fois loggé → écran "Mes projets" visible
        await expect(page.locator('#screenProjects')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('#myProjectsList')).toBeVisible();
    });

    test('login échoue avec mauvais password', async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', 'mot_de_passe_invalide_12345');
        await page.getByRole('button', { name: 'Se connecter' }).click();
        // Erreur visible
        await expect(page.locator('#loginError')).toBeVisible({ timeout: 3000 });
    });

    test('le footer projets affiche les liens et la version', async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        await expect(page.locator('#screenProjects')).toBeVisible();
        // Liens Nouveautés / Crashes / Configuration (rôle link pour éviter le match avec le h2 du modal)
        await expect(page.getByRole('link', { name: '📜 Nouveautés' })).toBeVisible();
        await expect(page.getByRole('link', { name: '🐞 Journal des erreurs' })).toBeVisible();
        // Version affichée
        await expect(page.locator('#appVersionLabel')).toContainText(/^v\d+\.\d+\.\d+$/);
    });
});
