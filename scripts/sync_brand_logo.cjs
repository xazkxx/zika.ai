#!/usr/bin/env node
/**
 * 同步品牌 Logo（v1.81.0）
 * ---------------------------------------------------------------------------
 * 用户把原图丢在 `data/brand/logo_ui.png`（不进 git、不进安装包），
 * 但浏览器只能 GET 静态目录里的东西，所以构建前要拷一份到 `frontend/public/`。
 *
 * 三条口径：
 *   1. **没图不是错误**：只打印一行提示，构建照常继续，界面回退到内置矢量 mark。
 *   2. **不主动删旧图**：上次同步过去、这次原图被移走时，保留旧图并提示 ——
 *      否则一次误删就会让用户以为"Logo 功能坏了"。
 *   3. **只认白名单文件名**：避免有人把 `logo_ui - 副本 (2).png` 也当成正式图。
 */
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const BRAND_DIR = path.join(ROOT, 'data', 'brand');
const TARGET = path.join(ROOT, 'frontend', 'public', 'logo.png');
const NAMES = ['logo_ui.png', 'logo_ui.jpg', 'logo_ui.jpeg', 'logo_ui.webp'];

// 内容嗅探（v1.81.1 实测教训）：用户把 WebP 直接改名成 .png 丢进来。
// 浏览器靠内容嗅探照样显示，但"扩展名 .png + 内容 WebP"到 Word/PDF 那边会静默失效
// （python-docx 的 add_picture 不认 WebP，被 try/except 吞掉 → 页眉空白）。
// 构建时给一句人话提示，别等打出来的单据没有抬头才发现。
function looksLikeWebp(file) {
  try {
    const fd = fs.openSync(file, 'r');
    const head = Buffer.alloc(12);
    fs.readSync(fd, head, 0, 12, 0);
    fs.closeSync(fd);
    return (
      head.subarray(0, 4).toString('ascii') === 'RIFF' &&
      head.subarray(8, 12).toString('ascii') === 'WEBP'
    );
  } catch {
    return false;
  }
}


function main() {
  let source = null;
  for (const name of NAMES) {
    const candidate = path.join(BRAND_DIR, name);
    try {
      if (fs.statSync(candidate).isFile() && fs.statSync(candidate).size > 0) {
        source = candidate;
        break;
      }
    } catch {
      /* 不存在就继续看下一个 */
    }
  }

  if (!source) {
    if (fs.existsSync(TARGET)) {
      console.log('[brand] data/brand 里没有 logo_ui.*，沿用上次同步的 frontend/public/logo.png');
    } else {
      console.log('[brand] data/brand 里没有 logo_ui.*，界面将回退到内置矢量 mark（不影响构建）');
    }
    return;
  }

  if (looksLikeWebp(source)) {
    console.log('[brand] 注意：logo_ui 的内容其实是 WebP（只是扩展名叫 .png）。');
    console.log('[brand] 浏览器能显示，但 Word/PDF 认不出，构建前请先跑：');
    console.log('[brand]   .venv\\Scripts\\python.exe scripts\\normalize_brand_logo.py');
  }

  fs.mkdirSync(path.dirname(TARGET), { recursive: true });
  fs.copyFileSync(source, TARGET);
  const kb = (fs.statSync(TARGET).size / 1024).toFixed(1);
  console.log(`[brand] ${path.basename(source)} → frontend/public/logo.png（${kb} KB）`);
}

main();
