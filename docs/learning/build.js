// Builds the Mesiri Field Guide PDFs: src/NN-name.html -> pdf/NN-name.pdf (A4, with page numbers).
// Run from the repo root: node docs/learning/build.js [name-filter]
// Uses the Playwright that is installed with the dev tools (require('playwright')).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const dir = __dirname;
  const filter = process.argv[2] || '';
  const files = fs.readdirSync(path.join(dir, 'src')).filter((f) => f.endsWith('.html') && f.includes(filter));
  const browser = await chromium.launch();
  for (const file of files) {
    const page = await browser.newPage();
    await page.goto(`file://${path.join(dir, 'src', file)}`, { waitUntil: 'networkidle' });
    const title = await page.title();
    const out = path.join(dir, 'pdf', file.replace(/\.html$/, '.pdf'));
    await page.pdf({
      path: out,
      format: 'A4',
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<span></span>',
      footerTemplate: `<div style="width:100%;font:8px 'Noto Sans',sans-serif;color:#8a8178;padding:0 15mm;display:flex;justify-content:space-between"><span>${title} · Draft, internal</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
      margin: { top: '16mm', bottom: '18mm', left: '15mm', right: '15mm' },
    });
    console.log('built', path.relative(process.cwd(), out));
    await page.close();
  }
  await browser.close();
})();
