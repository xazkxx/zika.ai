const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8019';
(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin123'})}).then(r=>r.json());
  const T = login.access_token;
  const tpl = await fetch(`${BASE}/api/v1/contract-templates`, {headers:{Authorization:`Bearer ${T}`}}).then(r=>r.json());
  const list = Array.isArray(tpl) ? tpl : (tpl.items || []);
  console.log('templates:', list.length, list[0] && list[0].id, list[0] && list[0].name);
  const browser = await puppeteer.launch({executablePath: CHROME, headless:'new', args:['--no-sandbox']});
  const page = await browser.newPage();
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  if (list[0]) {
    const out = await page.evaluate(async ({id, T, BASE}) => {
      const r = await fetch(`${BASE}/api/v1/contract-templates/${id}/file`, {headers:{Authorization:`Bearer ${T}`}});
      const b = await r.blob();
      return {status: r.status, type: r.headers.get('content-type'), disp: r.headers.get('content-disposition'), size: b.size};
    }, {id: list[0].id, T, BASE});
    console.log('template file:', out);
  }
  await browser.close();
})();
