import { expect, type Page } from "@playwright/test";

export const GIGSIM = "http://localhost:8101";
const ADMIN = { "X-Admin-Token": "gigsim-admin" };

/** Test-only credentials, generated per test; never a real account. */
export function testUser() {
  const id = Math.random().toString(36).slice(2, 10);
  return { name: `E2E ${id}`, email: `e2e-${id}@example.com`, password: `e2e-pass-${id}-x` };
}

export async function signUpAndOnboard(page: Page, persona = "ai_ml") {
  const u = testUser();
  await page.goto("/login");
  await page.getByRole("button", { name: /create an account/i }).click();
  await page.getByLabel("Name").fill(u.name);
  await page.getByLabel("Email").fill(u.email);
  await page.getByLabel(/^Password/).fill(u.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await page.getByTestId(`persona-${persona}`).click();
  await page.getByTestId("onboarding-next").click(); // -> marketplace
  await page.getByTestId("onboarding-next").click(); // -> rates & filters
  await page.getByTestId("onboarding-next").click(); // finish (persona users skip uploads)
  await expect(page).toHaveURL(/\/inbox/);
  return u;
}

/** Analyse one job from its detail page and wait until the draft is ready for review. */
export async function analyseToStudio(page: Page, jobId: string) {
  await page.goto(`/jobs/${jobId}`);
  await page.getByRole("button", { name: "Analyse this job" }).click();
  const review = page.getByRole("link", { name: "Review proposal" }).first();
  await expect(review).toBeVisible();
  await review.click();
  await expect(page.getByRole("heading", { name: "Proposal studio" })).toBeVisible();
  await expect(page.getByTestId("draft-preview")).toBeVisible();
}

export async function setOutage(page: Page, on: boolean) {
  const r = await page.request.post(`${GIGSIM}/admin/outage`, { headers: ADMIN, data: { on } });
  expect(r.ok()).toBeTruthy();
}
