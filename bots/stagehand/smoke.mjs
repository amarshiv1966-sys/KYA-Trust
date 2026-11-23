// P5: run Stagehand (the unseen framework, test only) once against the local bank.
// Setup:  cd bots/stagehand && npm init -y && npm install @browserbasehq/stagehand zod@~4.4.3 dotenv
// Run:    node smoke.mjs      (needs Chrome installed, the bank running, and a key in ../../.env)
import "dotenv/config";
import { localBrowser, Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod/v4";

const browser = await localBrowser.launch();
const stagehand = await Stagehand.create({
  browser,
  model: { modelName: process.env.KYA_STAGEHAND_MODEL, apiKey: process.env.OPENAI_API_KEY },
});

const [page] = await browser.context.pages();
await page.goto("http://localhost:5173/login");
await stagehand.act("type cust_0001 into the customer id field");
await stagehand.act("type demo1234 into the password field");
await stagehand.act("click the log in button");

const { data } = await stagehand.extract(
  "extract the account balance shown on the home page",
  z.object({ balance: z.string() }),
);
console.log("balance:", data.balance);

await stagehand.close();
await browser.close();
