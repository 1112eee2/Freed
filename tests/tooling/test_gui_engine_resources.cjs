// Custom Threads/Hash inputs: range checks, clamping and restored settings.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const app = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');

function fixture(saved = {}) {
  const elements = new Map([
    ['input-engine-threads', {value: '12', min: '1', max: '12'}],
    ['input-engine-hash', {value: '512', min: '4', max: '1024'}],
    ['select-engine-mode', {value: 'win', options: [{value: 'win'}, {value: 'draw'}]}],
  ]);
  const store = {'thai-makhos-engine-settings-v1': JSON.stringify(saved)};
  const context = vm.createContext({console,
    localStorage: {
      getItem: key => (Object.hasOwn(store, key) ? store[key] : null),
      setItem: (key, value) => { store[key] = value; },
    },
    document: {addEventListener() {}, getElementById(id) {
      if (!elements.has(id)) elements.set(id, {value: '', options: [], textContent: '', style: {}});
      return elements.get(id);
    }},
  });
  vm.runInContext(app, context);
  return {run: code => vm.runInContext(code, context), elements};
}

test('number inputs accept integers inside their own range only', () => {
  const f = fixture();
  const accepts = (id, value) => f.run(`settingAccepts(document.getElementById('${id}'), '${value}')`);
  assert.equal(accepts('input-engine-threads', '1'), true);
  assert.equal(accepts('input-engine-threads', '7'), true);
  assert.equal(accepts('input-engine-threads', '12'), true);
  assert.equal(accepts('input-engine-threads', '0'), false);
  assert.equal(accepts('input-engine-threads', '13'), false);
  assert.equal(accepts('input-engine-threads', '2.5'), false);
  assert.equal(accepts('input-engine-hash', '4'), true);
  assert.equal(accepts('input-engine-hash', '300'), true);
  assert.equal(accepts('input-engine-hash', '1024'), true);
  assert.equal(accepts('input-engine-hash', '3'), false);
  assert.equal(accepts('input-engine-hash', '2048'), false);
  assert.equal(accepts('select-engine-mode', 'draw'), true);
  assert.equal(accepts('select-engine-mode', 'lose'), false);
});

test('typed values are rounded and clamped; junk keeps the previous value', () => {
  const f = fixture();
  const read = (id, typed, previous) => f.run(
    `(() => { const e = document.getElementById('${id}'); e.value = ${JSON.stringify(typed)};
      return [readIntInput(e, ${previous}), e.value]; })()`);
  assert.deepEqual([...read('input-engine-threads', '7', 12)], [7, '7']);
  assert.deepEqual([...read('input-engine-threads', '99', 12)], [12, '12']);
  assert.deepEqual([...read('input-engine-threads', '0', 12)], [1, '1']);
  assert.deepEqual([...read('input-engine-threads', '3.6', 12)], [4, '4']);
  assert.deepEqual([...read('input-engine-threads', '', 6)], [6, '6']);
  assert.deepEqual([...read('input-engine-threads', 'abc', 6)], [6, '6']);
  assert.deepEqual([...read('input-engine-hash', '300', 512)], [300, '300']);
  assert.deepEqual([...read('input-engine-hash', '5000', 512)], [1024, '1024']);
  assert.deepEqual([...read('input-engine-hash', '1', 512)], [4, '4']);
});

test('saved custom values are restored; out-of-range saved values are ignored', () => {
  const kept = fixture({engineThreads: 7, engineHashMb: 300});
  kept.run('restoreSettings()');
  assert.equal(kept.run('gameState.engineThreads'), 7);
  assert.equal(kept.run('gameState.engineHashMb'), 300);
  assert.equal(kept.elements.get('input-engine-threads').value, '7');
  assert.equal(kept.elements.get('input-engine-hash').value, '300');

  const ignored = fixture({engineThreads: 64, engineHashMb: 2});
  ignored.run('restoreSettings()');
  assert.equal(ignored.run('gameState.engineThreads'), 12);
  assert.equal(ignored.run('gameState.engineHashMb'), 512);
});
