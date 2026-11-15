// Records the demo video: one job from inbox to approved proposal to client reply, with a caption bar.
//   node scripts/record-demo.mjs http://localhost:8002 http://localhost:8102 ../../docs/images
// Needs the API (serving the built app) and GigSim running. Output: <outdir>/demo.webm
import { chromium } from "@playwright/test";
import { mkdirSync, readdirSync, renameSync } from "node:fs";
import { join } from "node:path";

const [BASE = "http://localhost:8002", GIGSIM = "http://localhost:8102", OUT = "../../docs/images"] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });
const tmp = join(OUT, "_rec");
mkdirSync(tmp, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 760 }, recordVideo: { dir: tmp, size: { width: 1280, height: 760 } }, colorScheme: "dark" });
const page = await ctx.newPage();
const wait = (ms) => page.waitForTimeout(ms);

async function caption(text, ms = 2600) {
  await page.evaluate((t) => {
    let el = document.getElementById("__cap");
    if (!el) {
      el = document.createElement("div");
      el.id = "__cap";
      el.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:99999;background:rgba(15,17,21,.92);color:#fff;" +
        "font:600 17px/1.35 system-ui,Segoe UI,sans-serif;padding:10px 18px;border-radius:12px;max-width:1050px;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.4);border:1px solid #7c9cff";
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  await wait(ms);
}

const id = Math.random().toString(36).slice(2, 8);
await page.goto(`${BASE}/login`);
await caption("GigBid: a multi-agent freelancing copilot. It finds jobs you can win, proves your fit, and never sends anything without you.", 4200);
await page.getByRole("button", { name: /create an account/i }).click();
await page.getByLabel("Name").fill("Sara Malik");
await page.getByLabel("Email").fill(`demo-${id}@example.com`);
await page.getByLabel(/^Password/).fill(`demo-pass-${id}-x`);
await caption("Sign up, then onboarding: choose a persona (or your own portfolio), a marketplace, rates and a Connects budget.", 2600);
await page.getByRole("button", { name: "Create account" }).click();
await page.getByTestId("persona-ai_ml").click();
await wait(800);
await page.getByTestId("onboarding-next").click();
await caption("Marketplace: GigSim (simulated clients who reply, negotiate and hire) or Upwork through its official MCP server.", 2800);
await page.getByTestId("onboarding-next").click();
await caption("Rates, categories to scout and the weekly Connects budget.", 2200);
await page.getByTestId("onboarding-next").click();
await page.waitForURL(/inbox/);
await caption("The job inbox comes straight from the marketplace, through the Marketplace MCP server.", 2600);

await page.getByTestId("scout").click();
await caption("Scout: the analysis agents run on new jobs in parallel. Results stream in live over Server-Sent Events.", 4500);
await page.locator("text=Review proposal").first().waitFor({ timeout: 60000 });
await wait(1500);
await caption("Each job gets a fit score, a risk badge, a recommended action, a price and its Connects cost.", 3500);

const firstReview = page.getByRole("link", { name: "Review proposal" }).first();
const href = await firstReview.getAttribute("href");
const jobId = href.split("bid-u")[1].split("-").slice(1).join("-");
await page.goto(`${BASE}/jobs/${jobId}`);
await caption("Job detail: what the client needs (including implied skills), the risk report, and the evidence for each requirement.", 4200);
await page.mouse.wheel(0, 500);
await wait(1800);
await page.goto(`${BASE}${href.replace("/studio/", "/runs/")}`);
await caption("Agent run viewer: every node checkpointed, with latency, model and cost. Any run can be replayed from any step.", 4000);

await page.goto(`${BASE}${href}`);
await page.getByTestId("draft-preview").waitFor();
await caption("Proposal studio: every claim is grounded. Hover or focus a highlighted claim to see the work that proves it.", 3000);
const claim = page.getByTestId("claim").first();
await claim.focus();
await wait(3500);
await caption("The Critic's score and notes, the Compliance verdict, and the claim check sit beside the draft. Nothing has been sent yet.", 3800);

await page.getByTestId("toggle-edit").click();
const box = page.getByTestId("draft-text");
await box.fill((await box.inputValue()) + "\n\nEmail me at sara.dev@example.com to move faster.");
await caption("Edit the draft. Every edit is re-checked by the Compliance Guard and diffed for style memory.", 2600);
await page.getByTestId("save-edit").click();
await page.getByText("no_contact_details").waitFor({ timeout: 30000 });
await caption("Compliance removed the contact details automatically. Repeated edit patterns become style rules.", 3800);
await page.getByTestId("approve").click();
await page.getByText("Submitted").first().waitFor({ timeout: 30000 });
await caption("Approved: submitted exactly once (idempotent writes, Postgres checkpoints survive crashes).", 3200);

await page.goto(`${BASE}/pipeline`);
await caption("Pipeline: cards move by themselves as the marketplace reports views, replies, interviews and hires.", 3500);
for (let i = 0; i < 25; i++) {
  await page.getByRole("button", { name: /Check marketplace now/ }).click();
  await wait(2000);
  const replied = await page.getByTestId("col-replied").innerText();
  if (/\b[1-9]\b/.test(replied.split("\n")[0])) break;
}
await caption("The simulated client replied. GigBid has already drafted a reply.", 2800);

await page.goto(`${BASE}/messages`);
await page.locator(".thread-item").first().click();
await page.getByTestId("reply-approval").waitFor({ timeout: 45000 });
await caption("Client Liaison: it classifies the message (question, negotiation, interview, scam), drafts a grounded reply, and offers free slots from your calendar.", 5000);
const send = page.getByTestId("send-reply");
if (await send.isVisible()) {
  await send.click();
  await caption("Approved and sent. The offered slots are held as tentative on the calendar.", 3200);
}

await page.goto(`${BASE}/analytics`);
await caption("Analytics: reply and hire rates by category, Connects against outcomes, cost and latency per proposal.", 3200);
await page.goto(`${BASE}/settings`);
await page.getByTestId("memory").scrollIntoViewIfNeeded();
await caption("Settings: autonomy (it never auto-sends), budgets, saved searches, connected accounts, and a viewer for what GigBid has learned.", 4200);
await caption("GigBid: LangGraph agents, three MCP servers, measured RAG, human approval at every write.", 3500);

await ctx.close();
await browser.close();
const file = readdirSync(tmp).find((f) => f.endsWith(".webm"));
renameSync(join(tmp, file), join(OUT, "demo.webm"));
console.log("wrote", join(OUT, "demo.webm"));
