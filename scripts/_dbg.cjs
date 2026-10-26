const puppeteer = require('C:/Users/admi/node_modules/puppeteer-core');
(async () => {
  const b = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9223' });
  const pg = await b.newPage();
  const errs = [];
  pg.on('pageerror', (e) => errs.push('PAGEERR ' + e.message));
  pg.on('console', (m) => { if (m.type() === 'error') errs.push('CERR ' + m.text()); });
  await pg.goto('http://127.0.0.1:8010', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await new Promise((r) => setTimeout(r, 4000));
  const info = await pg.evaluate(() => ({
    title: document.title,
    inp: document.querySelectorAll('input').length,
    btns: document.querySelectorAll('button').length,
    forms: document.querySelectorAll('form').length,
    body: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 800),
  }));
  console.log('INFO ' + JSON.stringify(info));
  console.log('ERRORS ' + JSON.stringify(errs));
  await b.disconnect();
})().catch((e) => console.log('FAIL ' + e.message));
