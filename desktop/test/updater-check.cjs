// Unit check of the updater without Electron: version order, release notes as plain text, the
// settings file, Strict offline, and that a run that can't install itself only points to the
// releases page. Run after `npm run build -w desktop`: node desktop/test/updater-check.cjs
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'recpro-upd-'));
const handlers = {};
const opened = [];
const fake = {
  app: { getVersion: () => '0.9.0', getPath: () => tmp, isPackaged: false },
  ipcMain: { handle: (name, fn) => (handlers[name] = fn) },
  shell: { openExternal: async (u) => opened.push(u) },
};
const load = Module._load;
Module._load = function (req, ...rest) {
  return req === 'electron' ? fake : load.call(this, req, ...rest);
};
const u = require(path.join(__dirname, '..', 'dist', 'test', 'updater.js'));

assert.ok(u.newer('0.10.0', '0.9.0'), '0.10 is newer than 0.9 (not a string compare)');
assert.ok(u.newer('v1.0.0', '0.9.9'));
assert.ok(!u.newer('0.9.0', '0.9.0') && !u.newer('0.8.5', '0.9.0'));
assert.strictEqual(u.plain('<h2>Text in photos</h2><p>IDs &amp; screenshots</p>'), 'Text in photos\nIDs & screenshots');
assert.match(u.friendly(new Error('getaddrinfo ENOTFOUND api.github.com')), /No internet/);

(async () => {
  let offline = false;
  const ev = {};
  u.init({ isDestroyed: () => false, webContents: { send: () => {} } }, { isOffline: async () => offline, allowed: () => true });
  let s = await handlers['updates:get'](ev);
  assert.strictEqual(s.mode, 'notify', 'nothing downloads until you choose to');
  assert.strictEqual(s.canInstall, false, 'a development run can’t replace itself');
  s = await handlers['updates:mode'](ev, 'off');
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(tmp, 'updates.json'), 'utf8')).mode, 'off');
  await handlers['updates:mode'](ev, 'nonsense');
  assert.strictEqual((await handlers['updates:get'](ev)).mode, 'off', 'unknown modes are ignored');
  offline = true;
  s = await handlers['updates:check'](ev);
  assert.strictEqual(s.status, 'error');
  assert.match(s.error, /Strict offline/, 'Strict offline stops even a check by hand');
  await handlers['updates:download'](ev);
  assert.ok(opened[0] && opened[0].startsWith('https://github.com/buildcool/RecPro/releases'), 'no installer here: the page opens');
  console.log('updater ok');
  process.exit(0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
