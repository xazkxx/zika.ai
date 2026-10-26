const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8019';
(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'Admin123'})}).then(r=>r.json());
  const T = login.access_token;
  const st = await fetch(`${BASE}/api/v1/system/attachment-storage`, {headers:{Authorization:`Bearer ${T}`}}).then(r=>r.json());
  const name = st.backups[0].name;
  const browser = await puppeteer.launch({executablePath: CHROME, headless:false, args:['--no-sandbox']});
  const page = await browser.newPage();
  await page.goto(BASE + '/', {waitUntil:'domcontentloaded'});
  const out = await page.evaluate(async ({name, T, BASE}) => {
    const url = `${BASE}/api/v1/system/attachment-backup/${encodeURIComponent(name)}`;
    const r1 = await fetch(url, {headers: {Authorization: `Bearer ${T}`}});
    const b1 = await r1.blob();
    const r2 = await fetch(url);
    const v = await fetch(`${BASE}/version.json`);
    const vbody = await v.text();
    // 只剩一个 zip 后缀、但路径不存在的探针：看 404 会不会也被吃成 204
    const r404 = await fetch(`${BASE}/api/v1/system/attachment-backup/no-such-file.zip`);
    return {status: r1.status, type: r1.headers.get('content-type'), size: b1.size, len: r1.headers.get('content-length'), noAuthStatus: r2.status,
            versionStatus: v.status, versionLen: vbody.length, probe404: r404.status};
  }, {name, T, BASE});
  console.log(out);
  await browser.close();
})();
