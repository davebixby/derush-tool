// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Smoke', () => {
    test('page de login charge avec les éléments attendus', async ({ page }) => {
        await page.goto('/');
        // Inputs login présents
        await expect(page.locator('#loginUser')).toBeVisible();
        await expect(page.locator('#loginPass')).toBeVisible();
        await expect(page.locator('#loginRemember')).toBeVisible();
        // Bouton Se connecter
        await expect(page.getByRole('button', { name: 'Se connecter' })).toBeVisible();
        // Lien Configuration (scopé au screen login car celui des projets est aussi présent dans le DOM mais caché)
        await expect(page.locator('#screenLogin a[href="/setup"]')).toBeVisible();
    });

    test('endpoint /api/version retourne une version valide', async ({ request }) => {
        const r = await request.get('/api/version');
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d.version).toMatch(/^\d+\.\d+\.\d+$/);
    });

    test('endpoint /api/changelog retourne des entries valides', async ({ request }) => {
        const r = await request.get('/api/changelog');
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d.current_version).toBeTruthy();
        expect(Array.isArray(d.entries)).toBeTruthy();
        if (d.entries.length > 0) {
            expect(d.entries[0]).toHaveProperty('version');
            expect(d.entries[0]).toHaveProperty('date');
            expect(d.entries[0]).toHaveProperty('body');
            expect(d.entries[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        }
    });

    test('endpoint /api/heartbeat répond OK', async ({ request }) => {
        const r = await request.post('/api/heartbeat');
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d.ok).toBeTruthy();
    });

    test('/api/profile retourne le statut du profil', async ({ request }) => {
        const r = await request.get('/api/profile');
        expect(r.ok()).toBeTruthy();
        const d = await r.json();
        expect(d).toHaveProperty('exists');
    });
});
