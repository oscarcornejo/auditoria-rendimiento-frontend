// Uso: node run_collect.js <url> <salida.json>   (Playwright + collect_browser.js)
const { chromium } = require("playwright"); const fs = require("fs");
(async () => {
  const [url, out = "browser-collect.json"] = process.argv.slice(2);
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.6, isMobile: true });
  const p = await ctx.newPage(); await p.goto(url, { waitUntil: "networkidle" });
  const r = await p.evaluate(fs.readFileSync(__dirname + "/collect_browser.js", "utf8"));
  fs.writeFileSync(out, JSON.stringify(r, null, 2)); fs.writeFileSync(out.replace(/\.json$/, "-hallazgos.json"), JSON.stringify(r.hallazgos, null, 2));
  console.log(JSON.stringify(r.metricas), "\nhallazgos:", r.hallazgos.length); await b.close();
})();
