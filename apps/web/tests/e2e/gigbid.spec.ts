import { expect, test } from "@playwright/test";
import { analyseToStudio, setOutage, signUpAndOnboard } from "./helpers";

test.describe("GigBid", () => {
  test("onboarding: sign up, choose a persona, land on a ranked inbox", async ({ page }) => {
    await signUpAndOnboard(page, "ai_ml");
    await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
    await expect(page.locator("article.job").first()).toBeVisible();
    // Settings remember the onboarding choices.
    await page.getByRole("link", { name: "Settings" }).first().click();
    await expect(page.getByText("active (ai_ml)")).toBeVisible();
  });

  test("approving a proposal submits it once and moves it to the pipeline", async ({ page }) => {
    await signUpAndOnboard(page);
    await analyseToStudio(page, "j-00010");
    // Evidence is attached to claims, and the dry-run cost is shown before anything is sent.
    await expect(page.getByTestId("claim").first()).toBeVisible();
    await expect(page.getByText(/Dry-run preview/)).toBeVisible();
    await page.getByTestId("approve").click();
    await expect(page.getByText("Submitted").first()).toBeVisible();
    await page.getByRole("link", { name: "Pipeline" }).first().click();
    await expect(page.getByTestId("col-submitted")).toContainText("1");
  });

  test("rejecting needs a reason, and the reason shows in analytics", async ({ page }) => {
    await signUpAndOnboard(page);
    await analyseToStudio(page, "j-00001");
    await page.getByTestId("reject-open").click();
    await expect(page.getByTestId("reject-confirm")).toBeDisabled();
    await page.getByTestId("reject-reason").fill("budget too vague");
    await page.getByTestId("reject-confirm").click();
    await expect(page.getByText("Rejected").first()).toBeVisible();
    await page.getByRole("link", { name: "Analytics" }).first().click();
    await expect(page.getByText("budget too vague")).toBeVisible();
  });

  test("editing a draft re-checks it with compliance before it can be approved", async ({ page }) => {
    await signUpAndOnboard(page);
    await analyseToStudio(page, "j-00002");
    await page.getByTestId("toggle-edit").click();
    const box = page.getByTestId("draft-text");
    await box.fill((await box.inputValue()) + "\n\nEmail me at someone@example.com to move faster.");
    await page.getByTestId("save-edit").click();
    // The run resumes, compliance strips the contact details, and the draft comes back for approval.
    await expect(page.getByText("no_contact_details")).toBeVisible();
    await expect(page.getByTestId("draft-preview")).not.toContainText("someone@example.com");
    await expect(page.getByText("Your earlier edits")).toBeVisible();
    await expect(page.getByTestId("approve")).toBeEnabled();
  });

  test("marketplace outage shows the degraded-mode banner and analysed work stays visible", async ({ page }) => {
    await signUpAndOnboard(page);
    await setOutage(page, true);
    try {
      await page.goto("/inbox");
      await expect(page.getByTestId("degraded-banner")).toBeVisible();
      await expect(page.getByTestId("degraded-banner")).toContainText("Marketplace unavailable");
      await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible(); // the app still works
    } finally {
      await setOutage(page, false);
    }
    await page.reload();
    await expect(page.getByTestId("degraded-banner")).toHaveCount(0);
  });
});
