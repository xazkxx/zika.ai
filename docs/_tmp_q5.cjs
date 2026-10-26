const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8019';
(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin123'})}).then(r=>r.json());
  const T = login.access_token;
  const st = await fetch(`${BASE}/api/v1/system/attachment-storage`, {headers:{Authorization:`Bearer ${T}`}}).then(r=>r.json());
  const name = st.backups[0].name;
  const browser = await puppeteer.launch({executablePath: CHROME, headless:'new', args:['--no-sandbox']});
  const page = await browser.newPage();
  page.on('requestfailed', r => console.log('  [reqfail]', r.url().slice(-40), r.failure() && r.failure().errorText));
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  const out = await page.evaluate(async ({name, T, BASE}) => {
    const url = `${BASE}/api/v1/system/attachment-backup/${encodeURIComponent(name)}`;
    const res = {};
    // 1) 默认 fetch
    try { const r = await fetch(url, {headers:{Authorization:`Bearer ${T}`}}); res.plain = {status:r.status, len:r.headers.get('content-length'), size:(await r.blob()).size}; } catch(e){ res.plain = 'ERR '+e.message; }
    // 2) no-store
    try { const r = await fetch(url, {cache:'no-store', headers:{Authorization:`Bearer ${T}`}}); res.noStore = {status:r.status, size:(await r.blob()).size}; } catch(e){ res.noStore = 'ERR '+e.message; }
    // 3) Range 前 1KB
    try { const r = await fetch(url, {headers:{Authorization:`Bearer ${T}`, Range:'bytes=0-1023'}}); res.range = {status:r.status, size:(await r.blob()).size}; } catch(e){ res.range = 'ERR '+e.message; }
    // 4) XHR
    res.xhr = await new Promise((resolve) => {
      const x = new XMLHttpRequest();
      x.open('GET', url);
      x.setRequestHeader('Authorization', `Bearer ${T}`);
      x.responseType = 'blob';
      x.onload = () => resolve({status:x.status, size:x.response ? x.response.size : -1});
      x.onerror = () => resolve({status:'error'});
      x.send();
    });
    return res;
  }, {name, T, BASE});
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})();
