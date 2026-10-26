const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8019';
(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin123'})}).then(r=>r.json());
  const T = login.access_token;
  // 传一个 1x1 的 png 当模板（内联返回，无 Content-Disposition: attachment）
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
  const form = new FormData();
  form.append('file', new Blob([png], {type:'image/png'}), '探针.png');
  form.append('name', '临时探针模板' + Date.now());
  const up = await fetch(`${BASE}/api/v1/contract-templates`, {method:'POST', headers:{Authorization:`Bearer ${T}`}, body: form});
  const created = await up.json();
  console.log('upload', up.status, created.id || created.detail);
  const browser = await puppeteer.launch({executablePath: CHROME, headless:false, args:['--no-sandbox']});
  const page = await browser.newPage();
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  const out = await page.evaluate(async ({id, T, BASE}) => {
    const r = await fetch(`${BASE}/api/v1/contract-templates/${id}/file`, {headers:{Authorization:`Bearer ${T}`}});
    const b = await r.blob();
    return {status: r.status, type: r.headers.get('content-type'), disp: r.headers.get('content-disposition'), size: b.size};
  }, {id: created.id, T, BASE});
  console.log('inline file:', out);
  await browser.close();
  const del = await fetch(`${BASE}/api/v1/contract-templates/${created.id}`, {method:'DELETE', headers:{Authorization:`Bearer ${T}`}});
  console.log('cleanup', del.status);
})();
