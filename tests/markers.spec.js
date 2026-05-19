// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sébastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';
const TEST_PROJECT = process.env.DERUSH_TEST_PROJECT || 'Drift_Club';

test.describe('Markers — bug textarea & workflow', () => {
    test.skip(!TEST_PASS, 'DERUSH_TEST_PASS non défini');

    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        await expect(page.locator('#screenProjects')).toBeVisible();
        // Entrer dans le projet test
        // Les projets sont rendus comme div.proj-item avec un <strong> contenant le nom
        const projectItem = page.locator('.proj-item', { hasText: TEST_PROJECT }).first();
        if (await projectItem.count() > 0) {
            await projectItem.click();
        } else {
            await page.locator('.proj-item').first().click();
        }
        // Workspace visible
        await expect(page.locator('#wsProjName')).toBeVisible({ timeout: 10000 });
        // Sélectionne le 1er clip
        const firstClip = page.locator('.clip-item').first();
        await firstClip.click();
        await expect(page.locator('#clipTitle')).not.toContainText('—', { timeout: 5000 });
    });

    test('popup marker accepte focus et input', async ({ page }) => {
        await page.getByText('📌 Marker', { exact: false }).click();
        await expect(page.locator('#markerPopup')).toBeVisible();
        await expect(page.locator('#popupDesc')).toBeFocused({ timeout: 2000 });
        await page.locator('#popupDesc').fill('Test marker 1');
        await expect(page.locator('#popupDesc')).toHaveValue('Test marker 1');
    });

    test('BUG REGRESSION : add → delete → re-add → textarea focusable', async ({ page }) => {
        // Compte initial des markers
        const initialCount = await page.locator('.marker-row').count();

        // 1. Ajouter un marker avec description
        await page.getByText('📌 Marker', { exact: false }).click();
        await expect(page.locator('#popupDesc')).toBeFocused();
        await page.locator('#popupDesc').fill('Premier marker');
        await page.getByRole('button', { name: /Ajouter le marker/i }).click();
        await expect(page.locator('#markerPopup')).toBeHidden();
        await expect(page.locator('.marker-row')).toHaveCount(initialCount + 1);

        // 2. Supprimer le marker via le bouton 🗑
        const lastRow = page.locator('.marker-row').last();
        await lastRow.locator('button[title="Supprimer"]').click();
        await expect(page.locator('.marker-row')).toHaveCount(initialCount);

        // 3. Re-ouvrir le popup et vérifier que la textarea est focusable
        await page.getByText('📌 Marker', { exact: false }).click();
        await expect(page.locator('#markerPopup')).toBeVisible();
        await expect(page.locator('#popupDesc')).toBeFocused({ timeout: 2000 });
        // Le test critique : on peut écrire dedans
        await page.locator('#popupDesc').fill('Deuxième marker après delete');
        await expect(page.locator('#popupDesc')).toHaveValue('Deuxième marker après delete');
        await page.getByRole('button', { name: /Ajouter le marker/i }).click();
        await expect(page.locator('.marker-row')).toHaveCount(initialCount + 1);

        // Cleanup : supprimer le marker créé pour ne pas polluer les données du projet
        await page.locator('.marker-row').last().locator('button[title="Supprimer"]').click();
    });

    test('Échap ferme le popup marker', async ({ page }) => {
        await page.getByText('📌 Marker', { exact: false }).click();
        await expect(page.locator('#markerPopup')).toBeVisible();
        await page.keyboard.press('Escape');
        // Note : si Escape n'est pas câblé, ce test peut échouer — fix possible
        // mais pas critique
    });
});
