const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8019';
(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin123'})}).then(r=>r.json());
  const T = login.access_token;
  const browser = await puppeteer.launch({executablePath: CHROME, headless:'new', args:['--no-sandbox']});
  const page = await browser.newPage();
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  const out = await page.evaluate(async ({T, BASE}) => {
    const probe = async (url) => {
      const r = await fetch(url, {headers:{Authorization:`Bearer ${T}`}});
      const b = await r.blob();
      return {status: r.status, size: b.size, disp: r.headers.get('content-disposition'), ct: r.headers.get('content-type')};
    };
    return {
      csv: await probe(`${BASE}/api/v1/reports/daily-export`),
      json: await probe(`${BASE}/api/v1/system/attachment-storage`),
    };
  }, {T, BASE});
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})();
