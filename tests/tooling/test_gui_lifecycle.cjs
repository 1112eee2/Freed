// Exercise real browser lifecycle code with delayed HTTP completions.
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const app = fs.readFileSync(require('node:path').join(__dirname, '../../web/app.js'), 'utf8');

function fixture() {
  const initial = {board: Array(32).fill(0), turn: 'black', reversible_plies: 0, legal_moves: []};
  initial.board[24] = 2; initial.board[0] = 1;
  const changed = {...initial, board: [...initial.board], turn: 'red'};
  changed.board[24] = 0; changed.board[20] = 2;
  let releaseSearch, releaseApply;
  const elements = new Map();
  const context = vm.createContext({console, AbortController, setTimeout, clearTimeout,
    document: {addEventListener() {}, getElementById(id) {
      if (!elements.has(id)) elements.set(id, {textContent: '', style: {}, classList: {toggle() {}}});
      return elements.get(id);
    }},
    fetch: async (path) => {
      if (path === '/api/bestmove') return new Promise(resolve => {releaseSearch = resolve;});
      if (path === '/api/apply-move') return new Promise(resolve => {releaseApply = resolve;});
      return {ok: true, json: async () => initial};
    },
  });
  vm.runInContext(app, context);
  vm.runInContext(`renderBoard = () => {}; updateMoveHistoryUI = () => {};
    updatePlayerLabels = () => {}; updateTurnBadges = () => {}; checkBotTurn = () => {};
    updateEvalUI = () => {}; gameState.board = Array(32).fill(0);
    gameState.board[24] = 2; gameState.board[0] = 1;
    gameState.legalMoves = [{notation: '25-21', start:24, end:20}];`, context);
  const response = data => ({ok: true, json: async () => data});
  return {context, initial, changed, elements,
    search: () => releaseSearch(response({bestmove:'25-21', pv: ['25-21']})),
    apply: () => releaseApply(response(changed)),
    hasApply: () => Boolean(releaseApply)};
}

test('late bestmove from a previous game cannot apply or change the board', async () => {
  const f = fixture();
  const pending = vm.runInContext('triggerBotSearch()', f.context);
  await vm.runInContext('startNewGame()', f.context);
  f.search();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.hasApply(), false, 'stale bestmove issued apply-move');
  await pending;
  assert.deepEqual(Array.from(vm.runInContext('gameState.board', f.context)), f.initial.board);
});

test('late apply-move response cannot overwrite a newly started game', async () => {
  const f = fixture();
  const pending = vm.runInContext('triggerBotSearch()', f.context);
  f.search();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.hasApply(), true);
  await vm.runInContext('startNewGame()', f.context);
  f.apply(); await pending;
  assert.deepEqual(Array.from(vm.runInContext('gameState.board', f.context)), f.initial.board);
  assert.equal(vm.runInContext('gameState.moveHistory.length', f.context), 0);
});

test('switching to edit mode invalidates an outstanding engine result', async () => {
  const f = fixture();
  const pending = vm.runInContext('triggerBotSearch()', f.context);
  vm.runInContext("setMode('edit')", f.context);
  f.search(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.hasApply(), false);
  await pending;
});
