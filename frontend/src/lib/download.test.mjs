/**
 * download.js 的单测（`node --test src/lib/download.test.mjs`）
 *
 * 守的是「落盘策略」的四条分支 —— 每一条弄错，用户都会以为导出坏了：
 *   · 支持 File System Access 且用户确认 → **直写磁盘**（文件不带 Mark-of-the-Web，
 *     Office 才不会把它丢进坏掉的「受保护视图」里报"文件已损坏"）；
 *   · 用户在另存为对话框点取消 → 返回 `cancelled`，**绝不能偷偷再下一次**
 *     （否则用户按取消反而多出一个文件，纯属惩罚）；
 *   · 手势过期 / 写入失败 / 非安全上下文 → 退回普通下载，用户至少拿到文件；
 *   · 0 字节 → 抛错，不静默存空文件。
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { canSaveWithPicker, saveBlobSmart } from './download.js';

/** 极简浏览器替身：只装这个模块真正用到的那几样东西。 */
function installStub({ picker, secure = true } = {}) {
  const state = { downloaded: [], revoked: [], pickerOptions: [], written: [], closed: 0 };
  globalThis.URL.createObjectURL = () => 'blob:stub';
  globalThis.URL.revokeObjectURL = (url) => state.revoked.push(url);
  globalThis.document = {
    createElement: () => ({
      href: '',
      download: '',
      click() {
        state.downloaded.push(this.download);
      },
      remove() {},
    }),
    body: { appendChild() {} },
  };
  globalThis.window = { isSecureContext: secure };
  if (picker) globalThis.window.showSaveFilePicker = picker;
  state.reset = () => {
    delete globalThis.window;
    delete globalThis.document;
    // ⚠️ 不能 delete 这两个：`saveBlob` 里有个 1 秒后才执行的 `revokeObjectURL` 回调，
    // 删掉它们会让那个回调在测试结束后抛未捕获异常（node --test 会判失败）。
    globalThis.URL.createObjectURL = () => 'blob:stub';
    globalThis.URL.revokeObjectURL = () => {};
  };
  return state;
}

/** 造一个 showSaveFilePicker：`failWith` 用来模拟 AbortError / NotAllowedError。 */
function makePicker(state, { failWith, writeFails = false } = {}) {
  return async (options) => {
    if (failWith) {
      const err = new Error('stub');
      err.name = failWith;
      throw err;
    }
    state.pickerOptions.push(options);
    return {
      name: options.suggestedName,
      async createWritable() {
        return {
          async write(blob) {
            if (writeFails) throw new Error('disk full');
            state.written.push(blob);
          },
          async close() {
            state.closed += 1;
          },
        };
      },
    };
  };
}

const bytes = () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]);

test('没有浏览器 API（Node 环境）时 canSaveWithPicker 为 false', () => {
  assert.equal(canSaveWithPicker(), false);
});

test('不支持 File System Access → 退回普通下载，文件名照传', async () => {
  const state = installStub();
  try {
    const result = await saveBlobSmart(bytes(), '发票清单_20261026_1840.xlsx');
    assert.equal(result.saved, 'download');
    assert.deepEqual(state.downloaded, ['发票清单_20261026_1840.xlsx']);
  } finally {
    state.reset();
  }
});

test('非安全上下文（局域网 IP 访问）即使有 API 也退回下载', async () => {
  const state = installStub({ secure: false, picker: async () => assert.fail('不该调用 picker') });
  try {
    const result = await saveBlobSmart(bytes(), 'a.xlsx');
    assert.equal(result.saved, 'download');
    assert.deepEqual(state.downloaded, ['a.xlsx']);
  } finally {
    state.reset();
  }
});

test('支持且用户确认 → 直写磁盘，且不触发浏览器下载', async () => {
  const state = installStub();
  globalThis.window.showSaveFilePicker = makePicker(state);
  try {
    const result = await saveBlobSmart(bytes(), '发票清单_20261026_1840.xlsx');
    assert.equal(result.saved, 'picker');
    assert.equal(state.closed, 1);
    assert.equal(state.written.length, 1);
    assert.deepEqual(state.downloaded, [], '直写磁盘就不该再走下载管道（否则照样带来源标记）');
    // xlsx 的类型要能填进对话框，否则用户会被迫手输扩展名
    assert.deepEqual(
      state.pickerOptions[0].types[0].accept['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
      ['.xlsx'],
    );
    assert.equal(state.pickerOptions[0].suggestedName, '发票清单_20261026_1840.xlsx');
  } finally {
    state.reset();
  }
});

test('用户在另存为里点取消 → cancelled，且绝不偷偷再下一份', async () => {
  const state = installStub();
  globalThis.window.showSaveFilePicker = makePicker(state, { failWith: 'AbortError' });
  try {
    const result = await saveBlobSmart(bytes(), '发票报表.xlsx');
    assert.equal(result.saved, 'cancelled');
    assert.deepEqual(state.downloaded, []);
  } finally {
    state.reset();
  }
});

test('手势过期（NotAllowedError）→ 退回下载，保留原因', async () => {
  const state = installStub();
  globalThis.window.showSaveFilePicker = makePicker(state, { failWith: 'NotAllowedError' });
  try {
    const result = await saveBlobSmart(bytes(), '发票报表.xlsx');
    assert.equal(result.saved, 'download');
    assert.equal(result.reason, 'NotAllowedError');
    assert.deepEqual(state.downloaded, ['发票报表.xlsx']);
  } finally {
    state.reset();
  }
});

test('写入磁盘失败 → 退回下载（用户至少拿到文件）', async () => {
  const state = installStub();
  globalThis.window.showSaveFilePicker = makePicker(state, { writeFails: true });
  try {
    const result = await saveBlobSmart(bytes(), '合同台账.xlsx');
    assert.equal(result.saved, 'download');
    assert.deepEqual(state.downloaded, ['合同台账.xlsx']);
  } finally {
    state.reset();
  }
});

test('0 字节必须抛错，不静默存空文件', async () => {
  const state = installStub();
  try {
    await assert.rejects(() => saveBlobSmart(new Blob([]), 'empty.xlsx'), /下载到的文件是空的/);
    assert.deepEqual(state.downloaded, []);
  } finally {
    state.reset();
  }
});
