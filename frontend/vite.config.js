import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const BACKEND = 'http://127.0.0.1:8000';

/**
 * ============================================================================
 * 版本号自动化（2026-10-19）
 * ============================================================================
 * 以前每次发版要手改两处：package.json 的 version + public/sw.js 的 CACHE_VERSION，
 * 漏改 sw.js 的后果特别阴：新 JS 发下去了，但老 Service Worker 还拿旧壳，
 * 用户刷新看到的还是旧页面 → 被当成"改了没生效"。
 *
 * 现在只跑 `npm run build`，下面三件事自动完成：
 *   1. `public/sw.js` 的 `CACHE_VERSION = 'erp-pwa-vNN'` **自增 1**（v51 → v52）；
 *   2. 当前时间做成构建时间戳 `YYYY-MM-DD HH:mm`；
 *   3. 写一份 `dist/version.json`，供 Python 后端（含打包后的 exe）读取同一份标识。
 *
 * 页面上的短标因此变成：`v52 · 2026-10-19 17:15 · 寨卡`
 *   v52        = 缓存代号（决定浏览器要不要换壳，必须每次 +1）
 *   2026-...   = 构建时间（一眼看出是不是刚打的包）
 *   寨卡       = 品牌名，换品牌改下面 BRAND 或设环境变量 ERP_BRAND
 *
 * ⚠️ 只有 `vite build` 会自增；`vite dev` / `vite preview` 只读不自增
 *    （否则每改一行代码热更新都把缓存代号顶掉，本地开发就乱了）。
 * ⚠️ `package.json` 的 version 仍然保留，但它是**业务版本**（1.0.0），
 *    只在发大版本时手改，日常打包不用碰。
 * ============================================================================
 */

// 品牌名：页脚版本条的最后一段
const BRAND = process.env.ERP_BRAND || '寨卡';

const SW_FILE = fileURLToPath(new URL('./public/sw.js', import.meta.url));
// 故意用**单引号 + 分号**严格匹配：格式一旦被人改动就立刻报错停下，
// 绝不"悄悄不匹配、静默跳过自增" —— 那正是最危险的失败方式。
const SW_CACHE_RE = /const CACHE_VERSION = 'erp-pwa-v(\d+)';/;

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));

const now = new Date();
const pad = (value) => String(value).padStart(2, '0');
const buildStamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
const buildAt = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

let commitHash = 'nogit';
try {
  commitHash = execSync('git rev-parse --short HEAD', {
    cwd: new URL('.', import.meta.url),
    stdio: ['ignore', 'pipe', 'ignore'],
  })
    .toString()
    .trim();
} catch {
  // 没装 git / 不是仓库：保留 nogit，不影响构建
}

/** 读当前缓存代号（不自增），dev / preview 用。 */
function readSwCacheNumber() {
  const text = readFileSync(SW_FILE, 'utf8');
  const matched = text.match(SW_CACHE_RE);
  if (!matched) {
    throw new Error(
      [
        '【版本号】读不到 public/sw.js 里的缓存代号。',
        "  期望这一行长这样：const CACHE_VERSION = 'erp-pwa-v51';",
        `  实际文件：${SW_FILE}`,
        '  找不到就无法自增，构建已中止（否则发出去的是老壳缓存）。',
      ].join('\n'),
    );
  }
  return Number(matched[1]);
}

/** 缓存代号 +1 并写回 public/sw.js，返回新数字。只在 build 时调用。 */
function bumpSwCacheNumber() {
  const text = readFileSync(SW_FILE, 'utf8');
  const matched = text.match(SW_CACHE_RE);
  if (!matched) {
    throw new Error(
      [
        '【版本号】读不到 public/sw.js 里的缓存代号，构建已中止。',
        "  期望这一行长这样：const CACHE_VERSION = 'erp-pwa-v51';",
        `  实际文件：${SW_FILE}`,
      ].join('\n'),
    );
  }
  const next = Number(matched[1]) + 1;
  // 只替换那一处，其余字节原样保留（sw.js 是 CRLF，别整体重写换行符）
  writeFileSync(SW_FILE, text.replace(SW_CACHE_RE, `const CACHE_VERSION = 'erp-pwa-v${next}';`), 'utf8');
  return next;
}

/**
 * 把版本标识写成 dist/version.json。
 *
 * 为什么需要这个文件：前端靠 define 注入（编译期常量，dist 里没有明文），
 * 后端 Python 拿不到。写一份 JSON 放在 dist 里，Python 和 exe 就能读到**同一份**
 * 标识（exe 打包时 frontend/dist 整个被打进 _internal，这个文件跟着走）。
 */
function versionManifestPlugin(manifest) {
  let outDir = null;
  return {
    name: 'erp-version-manifest',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    writeBundle() {
      if (!outDir) return;
      writeFileSync(resolve(outDir, 'version.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
    },
  };
}

export default defineConfig(({ command }) => {
  // dev/serve 不自增，只读当前值，避免本地开发把缓存代号一路顶飞
  const isBuild = command === 'build';
  const cacheNumber = isBuild ? bumpSwCacheNumber() : readSwCacheNumber();
  const cacheLabel = `v${cacheNumber}`;

  const manifest = {
    app_version: pkg.version || '0.0.0',
    cache: cacheLabel,
    build: buildStamp,
    build_at: buildAt,
    brand: BRAND,
    commit: commitHash,
  };

  return {
    plugins: [react(), versionManifestPlugin(manifest)],
    define: {
      __APP_VERSION__: JSON.stringify(manifest.app_version),
      __APP_CACHE__: JSON.stringify(cacheLabel),
      __APP_BRAND__: JSON.stringify(BRAND),
      __APP_BUILD__: JSON.stringify(buildStamp),
      __APP_BUILD_AT__: JSON.stringify(buildAt),
      __APP_HASH__: JSON.stringify(commitHash),
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: BACKEND,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 4173,
      proxy: {
        '/api': {
          target: BACKEND,
          changeOrigin: true,
        },
      },
    },
  };
});
