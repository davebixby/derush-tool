// @ts-check
const { test, expect } = require('@playwright/test');

const TEST_USER = process.env.DERUSH_TEST_USER || 'Sébastien';
const TEST_PASS = process.env.DERUSH_TEST_PASS || '';
const TEST_PROJECT = process.env.DERUSH_TEST_PROJECT || 'Drift_Club';

test.describe('Drawing → marker', () => {
    test.skip(!TEST_PASS, 'DERUSH_TEST_PASS non défini');

    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        await page.fill('#loginUser', TEST_USER);
        await page.fill('#loginPass', TEST_PASS);
        await page.getByRole('button', { name: 'Se connecter' }).click();
        const projectItem = page.locator('.proj-item', { hasText: TEST_PROJECT }).first();
        if (await projectItem.count() > 0) await projectItem.click();
        else await page.locator('.proj-item').first().click();
        await expect(page.locator('#wsProjName')).toBeVisible();
        await page.locator('.clip-item').first().click();
        await expect(page.locator('#clipTitle')).not.toContainText('—');
    });

    test('startDrawing → draw → Valider ouvre le popup marker avec drawing attaché', async ({ page }) => {
        const initialCount = await page.locator('.marker-row').count();

        // Active le mode dessin
        await page.getByText('🖌 Dessin', { exact: false }).click();
        await expect(page.locator('#drawTools')).toBeVisible();

        // Sélectionne l'outil free
        await page.locator('#toolFree').click();

        // Simule un dessin (drag sur le canvas)
        const canvas = page.locator('#drawCanvas');
        const box = await canvas.boundingBox();
        if (!box) throw new Error('Canvas pas dimensionné');
        await page.mouse.move(box.x + 100, box.y + 100);
        await page.mouse.down();
        await page.mouse.move(box.x + 200, box.y + 150);
        await page.mouse.move(box.x + 250, box.y + 100);
        await page.mouse.up();

        // Clique Valider
        await page.getByRole('button', { name: '✅ Valider' }).click();

        // Le popup marker doit s'ouvrir avec cat=D pré-sélectionné
        await expect(page.locator('#markerPopup')).toBeVisible();
        await expect(page.locator('#pcatD')).toHaveClass(/selected/);
        await expect(page.locator('#popupDesc')).toBeFocused({ timeout: 2000 });

        // Tape une description et confirme
        await page.locator('#popupDesc').fill('Annotation visuelle test');
        await page.getByRole('button', { name: /Ajouter le marker/i }).click();
        await expect(page.locator('#markerPopup')).toBeHidden();

        // Marker créé avec icône dessin 🖌
        const newRow = page.locator('.marker-row').last();
        await expect(newRow).toContainText('Annotation visuelle test');
        await expect(newRow.locator('[title="Dessin inclus"]')).toBeVisible();

        // Cleanup
        await newRow.locator('button[title="Supprimer"]').click();
    });
});
