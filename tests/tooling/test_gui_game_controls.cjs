// Real application functions, with delayed HTTP replies to exercise races.
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const app = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

const gameRecordSchema = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '../../schemas/thai-makhos-game-v1.schema.json'),
    'utf8',
  ),
);

function schemaTypeMatches(value, type) {
  if (type === 'null') return value === null;
  if (type === 'array') return Array.isArray(value);
  if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
  if (type === 'integer') return Number.isInteger(value);
  return typeof value === type;
}

function validateSchema(value, definition, location = 'root') {
  if (definition.$ref) {
    const segments = definition.$ref.replace(/^#\//, '').split('/');
    let target = gameRecordSchema;
    for (const segment of segments) target = target[segment];
    validateSchema(value, target, location);
    return;
  }
  if (definition.oneOf) {
    let matches = 0;
    for (const candidate of definition.oneOf) {
      try {
        validateSchema(value, candidate, location);
        matches += 1;
      } catch (_error) {}
    }
    assert.equal(matches, 1, location + ' must match exactly one schema');
    return;
  }
  if (Object.hasOwn(definition, 'const')) {
    assert.deepEqual(value, definition.const, location + ' has the wrong constant');
  }
  if (definition.enum) {
    assert.ok(
      definition.enum.some(candidate => candidate === value),
      location + ' is outside the enum',
    );
  }
  if (definition.type) {
    const types = Array.isArray(definition.type) ? definition.type : [definition.type];
    assert.ok(
      types.some(type => schemaTypeMatches(value, type)),
      location + ' has the wrong type',
    );
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    for (const required of definition.required || []) {
      assert.ok(Object.hasOwn(value, required), location + ' is missing ' + required);
    }
    const properties = definition.properties || {};
    if (definition.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        assert.ok(Object.hasOwn(properties, key), location + ' forbids ' + key);
      }
    }
    for (const [key, child] of Object.entries(value)) {
      if (properties[key]) validateSchema(child, properties[key], location + '.' + key);
    }
  }
  if (Array.isArray(value)) {
    if (definition.minItems !== undefined) {
      assert.ok(value.length >= definition.minItems, location + ' has too few items');
    }
    if (definition.items) {
      value.forEach((child, index) => validateSchema(child, definition.items, location + '[' + index + ']'));
    }
  }
  if (typeof value === 'string') {
    if (definition.minLength !== undefined) {
      assert.ok(value.length >= definition.minLength, location + ' is too short');
    }
    if (definition.pattern) {
      assert.match(value, new RegExp(definition.pattern), location + ' misses the pattern');
    }
  }
  if (typeof value === 'number') {
    if (definition.minimum !== undefined) {
      assert.ok(value >= definition.minimum, location + ' is below minimum');
    }
    if (definition.maximum !== undefined) {
      assert.ok(value <= definition.maximum, location + ' is above maximum');
    }
    if (definition.exclusiveMinimum !== undefined) {
      assert.ok(value > definition.exclusiveMinimum, location + ' is below exclusiveMinimum');
    }
  }
}


function fixture(initial) {
  if (!initial) {
    const board = Array(32).fill(0); board[24] = 2; board[0] = 1;
    initial = {board, turn: 'black', reversible_plies: 7, terminal: false,
      legal_moves: [{notation: '25-21', start: 24, end: 20}]};
  }
  const requests = [];
  const elements = new Map();
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({console: {error() {}}, AbortController,
    setTimeout(fn) {timers.set(++timerId, fn); return timerId;},
    clearTimeout(id) {timers.delete(id);},
    document: {addEventListener() {}, getElementById(id) {
      if (!elements.has(id)) elements.set(id, {value: '', textContent: '', style: {}, classList: {toggle() {}}});
      return elements.get(id);
    }},
    fetch(url, options) {
      if (url === '/api/state') return Promise.resolve({ok: true, json: async () => initial});
      return new Promise(resolve => requests.push({url, options, resolve}));
    },
  });
  vm.runInContext(app, context);
  const run = code => vm.runInContext(code, context);
  const value = code => JSON.parse(JSON.stringify(run(code)));
  run(`renderBoard = () => {}; updateMoveHistoryUI = () => {}; updateEvalUI = () => {};
       updateGameState(${JSON.stringify(initial)}); gameState.gameMode = 'edit';
       gameState.startPosition = generatePositionString();
       gameState.startReversiblePlies = gameState.reversiblePlies;
       gameState.positionHistory = [gameState.startPosition]; updateGameControls();`);
  function reply(url, data, ok=true) {
    const request = requests.find(r => r.url === url && !r.done);
    assert.ok(request, `missing request ${url}`);
    request.done = true;
    request.resolve({ok, json: async () => data});
  }
  async function move(data) {
    const pending = run('attemptUserMove(gameState.legalMoves[0].start, gameState.legalMoves[0].end)');
    reply('/api/apply-move', data);
    await pending;
  }
  function adjudicate(result='draw') {
    elements.get('select-game-result').value = result;
    run('adjudicateGame()');
  }
  return {initial, requests, elements, timers, run, value, reply, move, adjudicate};
}

function quietChild(f) {
  const board = [...f.initial.board]; board[24] = 0; board[20] = 2;
  return {board, turn: 'red', reversible_plies: 8, terminal: false,
    legal_moves: [{notation: '1-5', start: 0, end: 4}]};
}

test('undo removes exactly one ply, restoring board, side, clock and history', async () => {
  const f = fixture(); const first = quietChild(f);
  await f.move(first);
  const board = [...first.board]; board[0] = 0; board[4] = 1;
  await f.move({board, turn: 'black', reversible_plies: 9, legal_moves: []});
  f.run('undoLastPly()');
  assert.deepEqual(f.value('gameState.board'), first.board);
  assert.equal(f.run('gameState.turn'), 'red');
  assert.equal(f.run('gameState.reversiblePlies'), 8);
  assert.equal(f.run('gameState.moveHistory.length'), 1);
  assert.equal(f.run('gameState.positionHistory.length'), 2);
  assert.equal(f.run('gameState.isPaused'), true);
  assert.deepEqual(f.value('gameState.lastMove'), {start: 24, end: 20});
  f.run('undoLastPly()');
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
  assert.equal(f.run('gameState.reversiblePlies'), 7);
  assert.equal(f.run('gameState.positionHistory.length'), 1);
  assert.equal(f.elements.get('btn-undo-move').disabled, true);
  f.run('undoLastPly()');
  assert.equal(f.run('gameState.moveHistory.length'), 0);
});

for (const scenario of [
  {name: 'multi-capture win', pieces: [[24,2],[21,1],[14,1]], start:24, end:10, notation:'25x18x11', captures:[21,14], promotes:false},
  {name: 'promotion capture', pieces: [[8,2],[5,1],[6,1]], start:8, end:1, notation:'9x2', captures:[5], promotes:true},
]) {
  test(`undo restores every captured piece and original rank: ${scenario.name}`, async () => {
    const board = Array(32).fill(0);
    for (const [square, piece] of scenario.pieces) board[square] = piece;
    const move = {...scenario};
    const f = fixture({board, turn:'black', reversible_plies:23, legal_moves:[move]});
    const child = [...board]; child[move.start] = 0;
    for (const square of move.captures) child[square] = 0;
    child[move.end] = move.promotes ? 4 : 2;
    await f.move({board:child, turn:'red', reversible_plies:0, legal_moves:[],
      terminal:!move.promotes, winner:!move.promotes ? 'black' : null, reason:'no_legal_move'});
    f.run('undoLastPly()');
    assert.deepEqual(f.value('gameState.board'), board);
    assert.deepEqual(f.value('gameState.legalMoves'), [move]);
    assert.equal(f.run('gameState.reversiblePlies'), 23);
    assert.equal(f.run('gameState.isGameOver'), false);
    assert.equal(f.run('gameState.result'), null);
    assert.equal(f.run('gameState.moveHistory.length'), 0);
  });
}

test('undo reopens a rules draw and removes only its final repetition entry', async () => {
  const f = fixture(); const child = quietChild(f);
  await f.move({...child, terminal:true, winner:null, reason:'repetition'});
  assert.equal(f.run('gameState.result.source'), 'rules');
  f.run('undoLastPly()');
  assert.equal(f.run('gameState.isGameOver'), false);
  assert.deepEqual(f.value('gameState.positionHistory'), [f.run('gameState.startPosition')]);
  assert.equal(f.elements.get('btn-save-game').disabled, true);
});

test('late human reply cannot overwrite a new game', async () => {
  const f = fixture();
  const pending = f.run('attemptUserMove(24, 20)');
  await f.run('startNewGame()');
  f.reply('/api/apply-move', quietChild(f)); await pending;
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
  assert.equal(f.run('gameState.moveHistory.length'), 0);
});

test('adjudication cancels an in-flight human move, retaining the last completed ply', async () => {
  const f = fixture(); const pending = f.run('attemptUserMove(24, 20)');
  f.adjudicate('red');
  f.reply('/api/apply-move', quietChild(f)); await pending;
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
  assert.equal(f.run('gameState.moveHistory.length'), 0);
  assert.equal(f.run('gameState.result.winner'), 'red');
  assert.equal(f.requests[0].options.signal.aborted, true);
});

test('undo cancels late bot apply and leaves the bot paused until explicit resume', async () => {
  const f = fixture(); const child = quietChild(f);
  await f.move(child); f.run("gameState.gameMode = 'bot'");
  const pending = f.run('triggerBotSearch()');
  f.reply('/api/bestmove', {bestmove:'1-5'}); await tick();
  f.run('undoLastPly()');
  f.reply('/api/apply-move', {...f.initial, turn:'black'}); await pending;
  f.run('checkBotTurn()');
  assert.equal(f.requests.filter(r => r.url === '/api/bestmove').length, 1);
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
  assert.equal(f.timers.size, 0);
  f.run('resumeGame()');
  assert.equal(f.requests.filter(r => r.url === '/api/bestmove').length, 2);
  f.adjudicate(); f.reply('/api/bestmove', {bestmove:'25-21'}); await tick();
});

test('adjudication drains bot-vs-bot timer and blocks further moves', async () => {
  const f = fixture(); f.run("gameState.gameMode = 'bot'");
  const pending = f.run('triggerBotSearch()');
  f.reply('/api/bestmove', {bestmove:'25-21'}); await tick();
  f.reply('/api/apply-move', quietChild(f)); await pending;
  assert.equal(f.timers.size, 1);
  f.adjudicate('black');
  assert.equal(f.timers.size, 0);
  f.run('checkBotTurn(); resumeGame()');
  assert.equal(f.requests.filter(r => r.url === '/api/bestmove').length, 1);
  const record = JSON.parse(f.run('buildGameRecord()'));
  assert.equal(record.result.source, 'user');
  assert.equal(record.result.winner, 'black');
  assert.equal(record.rules_result.terminal, false);
});


test('GUI and saved game records satisfy thai-makhos-game-v1 schema', async () => {
  const f = fixture();
  f.run("gameState.gameMode = 'bot'");
  const pending = f.run('triggerBotSearch()');
  f.reply('/api/bestmove', {
    bestmove: '25-21',
    provenance_version: 'search-v1',
    requested_time_ms: 1000,
    elapsed_ms: 9,
    request_elapsed_ms: 10.5,
    pre_search_setup_ms: 1.25,
    depth_limit: 64,
    depth: 12,
    common_depth: 11,
    selective_root: true,
    nodes: 12345,
    score: 7,
    pv: ['25-21', '1-5'],
    wdl: 'UNKNOWN',
    tablebase_hits: 0,
    threads: 12,
    hash_mb: 512,
    hash_allocated_mb: 510.5,
    mode: 'win',
    rules_profile: 'project',
    search_backend: 'native-endgame',
    native_library: 'build/makhos_native.dll',
    native_library_sha256: 'a'.repeat(64),
    native_search_abi: 5,
    nnue_enabled: true,
    nnue_feature_abi: 'thai-makhos-shared-137-v1',
    nnue_model: 'build/model_a.mknnue',
    nnue_model_sha256: 'b'.repeat(64),
    nnue_source_model_sha256: 'c'.repeat(64),
    native_tablebase_ready: true,
    native_tablebase_error: null,
    tb3: {ready: true, state: 'ready', error: null},
    runtime_isolation: 'interactive-exclusive-v1',
    native_error: null,
    evaluator_used: 'nnue',
    release_id: 'nnue-v1-20260908',
    release_manifest_sha256: 'd'.repeat(64),
  });
  await tick();
  f.reply('/api/apply-move', quietChild(f));
  await pending;
  f.adjudicate();

  const guiRecord = JSON.parse(f.run('buildGameRecord()'));
  assert.doesNotThrow(() => validateSchema(guiRecord, gameRecordSchema));

  const savedRecord = {
    ...guiRecord,
    game_id: 'e'.repeat(16),
    saved_at: '2026-09-25T17:00:00+00:00',
  };
  assert.doesNotThrow(() => validateSchema(savedRecord, gameRecordSchema));
});

test('double-click cannot apply one move twice', async () => {
  const f = fixture(); const first = f.run('attemptUserMove(24, 20)');
  await f.run('attemptUserMove(24, 20)');
  assert.equal(f.requests.length, 1);
  f.reply('/api/apply-move', quietChild(f)); await first;
  assert.equal(f.run('gameState.moveHistory.length'), 1);
});

test('save sends replayable history and result, prevents duplicates and retries errors', async () => {
  const f = fixture(); await f.move(quietChild(f)); f.adjudicate();
  const first = f.run('saveGameRecord()'); await f.run('saveGameRecord()');
  const saves = f.requests.filter(r => r.url === '/api/save-game');
  assert.equal(saves.length, 1);
  const record = JSON.parse(saves[0].options.body);
  assert.equal(record.moves.length, 1);
  assert.equal(record.position_history.length, 2);
  assert.equal(record.result.winner, null);
  f.reply('/api/save-game', {error:'disk full'}, false); await first;
  assert.equal(f.elements.get('btn-save-game').disabled, false);
  const retry = f.run('saveGameRecord()');
  f.reply('/api/save-game', {saved:true, path:'saved_games/example.json'}); await retry;
  assert.equal(f.run('gameState.savedPath'), 'saved_games/example.json');
  assert.equal(f.elements.get('btn-save-game').disabled, true);
  f.run('undoLastPly()');
  assert.equal(f.run('gameState.savedPath'), null);
  assert.equal(f.elements.get('save-game-status').textContent, '');
});

test('late save confirmation does not mark a new game as saved', async () => {
  const f = fixture(); f.adjudicate('black');
  const pending = f.run('saveGameRecord()');
  await f.run('startNewGame()');
  f.reply('/api/save-game', {saved:true, path:'saved_games/previous.json'}); await pending;
  assert.equal(f.run('gameState.savedPath'), null);
  assert.equal(f.run('gameState.result'), null);
  assert.equal(f.elements.get('save-game-status').textContent, '');
});

test('changing controllers after edit mode preserves repetition history and undo', async () => {
  const f = fixture(); await f.move(quietChild(f));
  const history = f.value('gameState.positionHistory');
  f.run('checkBotTurn = () => {}; setMode("human")');
  assert.deepEqual(f.value('gameState.positionHistory'), history);
  assert.equal(f.run('gameState.moveHistory.length'), 1);
  f.run('undoLastPly()');
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
});

test('TB3 readiness error pauses without moving and allows explicit resume', async () => {
  const f = fixture(); f.run("gameState.gameMode = 'bot'");
  const pending = f.run('triggerBotSearch()');
  f.reply('/api/bestmove', {error:'TB3 loading', tb3:{ready:false, state:'loading'}}, false);
  await pending;
  assert.equal(f.run('gameState.isPaused'), true);
  assert.equal(f.run('gameState.isBotThinking'), false);
  assert.equal(f.elements.get('btn-resume-game').disabled, false);
  assert.equal(f.requests.filter(r => r.url === '/api/apply-move').length, 0);
  assert.deepEqual(f.value('gameState.board'), f.initial.board);
  f.run('resumeGame()');
  assert.equal(f.requests.filter(r => r.url === '/api/bestmove').length, 2);
  f.adjudicate(); f.reply('/api/bestmove', {bestmove:'25-21'}); await tick();
});
