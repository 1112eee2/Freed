/**
 * Thai Makhos Engine Web GUI Frontend Application.
 * Handles drag-and-drop, click-to-move, board flip, bot thinking, bot vs bot, and move logging.
 */

// Board & Game State
let gameState = {
  board: [], // 32 squares representation (0..31)
  turn: 'black',
  reversiblePlies: 0,
  moveHistory: [],
  startPosition: null,
  startReversiblePlies: 0,
  positionHistory: [],
  legalMoves: [],
  selectedSquare: null,
  lastMove: null,
  isFlipped: false,
  gameMode: 'human', // 'human' or 'bot'
  humanSide: 'black', // 'black' or 'red'
  thinkTimeSec: 1.0,
  engineThreads: 1,
  engineHashMb: 64,
  engineMode: 'win',
  rulesProfile: 'project',
  isBotThinking: false,
  isGameOver: false,
  botVsBotTimer: null,
};

const SETTINGS_STORAGE_KEY = 'thai-makhos-engine-settings-v1';
let gameGeneration = 0;
let activeSearchController = null;

function invalidateSearch() {
  gameGeneration += 1;
  if (activeSearchController) activeSearchController.abort();
  activeSearchController = null;
  gameState.isBotThinking = false;
}

function restoreSettings() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) || '{}');
  } catch (_error) {
    saved = {};
  }
  const bindings = [
    ['select-human-side', 'humanSide', 'string'],
    ['select-think-time', 'thinkTimeSec', 'float'],
    ['select-engine-threads', 'engineThreads', 'int'],
    ['select-engine-hash', 'engineHashMb', 'int'],
    ['select-engine-mode', 'engineMode', 'string'],
    ['select-rules-profile', 'rulesProfile', 'string'],
  ];
  for (const [elementId, stateKey, type] of bindings) {
    const select = document.getElementById(elementId);
    const raw = saved[stateKey];
    if (raw === undefined) continue;
    const value = String(raw);
    if (![...select.options].some(option => option.value === value)) continue;
    select.value = value;
    gameState[stateKey] = type === 'int'
      ? parseInt(value, 10)
      : (type === 'float' ? parseFloat(value) : value);
  }
}

function persistSettings() {
  localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
    humanSide: gameState.humanSide,
    thinkTimeSec: gameState.thinkTimeSec,
    engineThreads: gameState.engineThreads,
    engineHashMb: gameState.engineHashMb,
    engineMode: gameState.engineMode,
    rulesProfile: gameState.rulesProfile,
  }));
}

// Piece constants matching Python backend
const EMPTY = 0;
const RED_MAN = 1;
const BLACK_MAN = 2;
const RED_KING = 3;
const BLACK_KING = 4;

// Playable squares index (0..31) to 8x8 row/col
function indexToCoord(sq) {
  const row = Math.floor(sq / 4);
  const offset = sq % 4;
  const col = offset * 2 + (row % 2 === 0 ? 1 : 0);
  return { row, col };
}

function coordToIndex(row, col) {
  if (row < 0 || row >= 8 || col < 0 || col >= 8) return null;
  if ((row + col) % 2 !== 1) return null;
  return row * 4 + Math.floor(col / 2);
}

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  setupUI();
  startNewGame();
  loadEngineIdentity();
});

function setupUI() {
  restoreSettings();

  // Mode selection
  document.getElementById('btn-mode-human').addEventListener('click', () => setMode('human'));
  document.getElementById('btn-mode-bot').addEventListener('click', () => setMode('bot'));
  document.getElementById('btn-mode-edit').addEventListener('click', () => setMode('edit'));

  // Settings
  document.getElementById('select-human-side').addEventListener('change', (e) => {
    invalidateSearch();
    gameState.humanSide = e.target.value;
    persistSettings();
    updatePlayerLabels();
    checkBotTurn();
  });

  document.getElementById('select-think-time').addEventListener('change', (e) => {
    gameState.thinkTimeSec = parseFloat(e.target.value);
    persistSettings();
  });

  document.getElementById('select-engine-threads').addEventListener('change', (e) => {
    gameState.engineThreads = parseInt(e.target.value, 10);
    persistSettings();
  });

  document.getElementById('select-engine-hash').addEventListener('change', (e) => {
    gameState.engineHashMb = parseInt(e.target.value, 10);
    persistSettings();
  });

  document.getElementById('select-engine-mode').addEventListener('change', (e) => {
    gameState.engineMode = e.target.value;
    persistSettings();
  });

  document.getElementById('select-rules-profile').addEventListener('change', (e) => {
    gameState.rulesProfile = e.target.value;
    persistSettings();
    startNewGame();
  });

  // Buttons
  document.getElementById('btn-new-game').addEventListener('click', () => startNewGame());
  document.getElementById('btn-flip-board').addEventListener('click', () => toggleFlipBoard());
  document.getElementById('btn-copy-game').addEventListener('click', () => copyGameRecord());
}

function setMode(mode) {
  invalidateSearch();
  const previousMode = gameState.gameMode;
  gameState.gameMode = mode;

  document.getElementById('btn-mode-human').classList.toggle('active', mode === 'human');
  document.getElementById('btn-mode-bot').classList.toggle('active', mode === 'bot');
  document.getElementById('btn-mode-edit').classList.toggle('active', mode === 'edit');

  const humanGroup = document.getElementById('group-human-side');
  humanGroup.style.display = mode === 'human' ? 'flex' : 'none';

  if (gameState.botVsBotTimer) {
    clearTimeout(gameState.botVsBotTimer);
    gameState.botVsBotTimer = null;
  }
  gameState.isBotThinking = false;

  if (mode === 'edit') {
    setStatusMessage('✏️ โหมดจัดกระดาน: คุณสามารถเดินหมากได้ทั้ง 2 ฝั่ง (เอนจิ้นปิดอยู่)');
    renderBoard();
  } else if (previousMode === 'edit') {
    // Retain current edited position when switching from edit to human/bot mode
    gameState.moveHistory = [];
    gameState.startPosition = generatePositionString();
    gameState.startReversiblePlies = gameState.reversiblePlies;
    gameState.positionHistory = [gameState.startPosition];
    updateMoveHistoryUI();
    setStatusMessage(`สลับโหมดเป็น ${mode === 'human' ? 'คน vs บอท' : 'บอท vs บอท'} พร้อมลุยต่อจากตำแหน่งนี้!`);
    renderBoard();
    checkBotTurn();
  } else {
    startNewGame();
  }
}

function toggleFlipBoard() {
  gameState.isFlipped = !gameState.isFlipped;

  const boardEl = document.getElementById('checkers-board');
  boardEl.classList.toggle('flipped', gameState.isFlipped);
  updatePlayerLabels();
  renderBoard();
}

function updatePlayerLabels() {
  const topDot = document.getElementById('dot-top');
  const topName = document.getElementById('name-top');
  const bottomDot = document.getElementById('dot-bottom');
  const bottomName = document.getElementById('name-bottom');

  if (gameState.isFlipped) {
    topDot.textContent = '⚫';
    topName.textContent = 'BLACK (ดำ)';
    bottomDot.textContent = '🔴';
    bottomName.textContent = 'RED (แดง)';
  } else {
    topDot.textContent = '🔴';
    topName.textContent = 'RED (แดง)';
    bottomDot.textContent = '⚫';
    bottomName.textContent = 'BLACK (ดำ)';
  }
  updateTurnBadges();
}

function updateTurnBadges() {
  const badgeTop = document.getElementById('badge-top');
  const badgeBottom = document.getElementById('badge-bottom');

  const topColor = gameState.isFlipped ? 'black' : 'red';
  const bottomColor = gameState.isFlipped ? 'red' : 'black';

  badgeTop.textContent = gameState.turn === topColor ? 'กำลังเดิน...' : '';
  badgeBottom.textContent = gameState.turn === bottomColor ? 'กำลังเดิน...' : '';
}

async function startNewGame() {
  invalidateSearch();
  const generation = gameGeneration;
  if (gameState.botVsBotTimer) {
    clearTimeout(gameState.botVsBotTimer);
    gameState.botVsBotTimer = null;
  }

  gameState.selectedSquare = null;
  gameState.lastMove = null;
  gameState.moveHistory = [];
  gameState.isGameOver = false;
  gameState.isBotThinking = false;

  // Request initial state from backend
  try {
    const res = await fetch('/api/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        first: 2,
        rules_profile: gameState.rulesProfile,
      }) // Black moves first
    });
    const data = await res.json();
    if (generation !== gameGeneration) return;
    if (!res.ok || data.error) throw new Error(data.error || 'Cannot start game');
    updateGameState(data);
    gameState.startPosition = generatePositionString();
    gameState.startReversiblePlies = gameState.reversiblePlies;
    gameState.positionHistory = [gameState.startPosition];
    renderBoard();
    updateMoveHistoryUI();
    setStatusMessage('เกมใหม่เริ่มแล้ว! ดำเดินก่อน');

    checkBotTurn();
  } catch (err) {
    console.error('Failed to start new game:', err);
    setStatusMessage('เกิดข้อผิดพลาดในการเชื่อมต่อเอนจิ้น');
  }
}

function updateGameState(data) {
  gameState.board = data.board;
  gameState.turn = data.turn;
  gameState.reversiblePlies = data.reversible_plies || 0;
  gameState.legalMoves = data.legal_moves || [];

  if (data.terminal) {
    gameState.isGameOver = true;
    if (data.winner) {
      const winnerName = data.winner === 'black' ? 'ดำ (BLACK)' : 'แดง (RED)';
      setStatusMessage(`🏆 จบเกม! ${winnerName} ชนะ (${data.reason})`);
    } else {
      setStatusMessage(`🤝 จบเกม! เสมอกัน (${data.reason})`);
    }
  } else {
    updateTurnBadges();
  }
}

// Position string format B:BM25,26:BK29:RM1,2:RK5
function generatePositionString() {
  const groups = [];
  const turnPrefix = gameState.turn === 'black' ? 'B' : 'R';

  const blackMen = [], blackKings = [], redMen = [], redKings = [];

  for (let sq = 0; sq < 32; sq++) {
    const p = gameState.board[sq];
    const sqNum = sq + 1;
    if (p === BLACK_MAN) blackMen.push(sqNum);
    else if (p === BLACK_KING) blackKings.push(sqNum);
    else if (p === RED_MAN) redMen.push(sqNum);
    else if (p === RED_KING) redKings.push(sqNum);
  }

  if (blackMen.length) groups.push(`BM${blackMen.join(',')}`);
  if (blackKings.length) groups.push(`BK${blackKings.join(',')}`);
  if (redMen.length) groups.push(`RM${redMen.join(',')}`);
  if (redKings.length) groups.push(`RK${redKings.join(',')}`);

  return `${turnPrefix}:${groups.join(':')}`;
}

// Render 8x8 Board
function renderBoard() {
  const boardEl = document.getElementById('checkers-board');
  boardEl.innerHTML = '';

  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const sqEl = document.createElement('div');
      sqEl.classList.add('square');

      const isDark = (r + c) % 2 === 1;
      sqEl.classList.add(isDark ? 'dark' : 'light');

      if (isDark) {
        const sqIndex = coordToIndex(r, c);
        sqEl.dataset.sq = sqIndex;

        // Coordinate number label (1..32)
        const coordLabel = document.createElement('span');
        coordLabel.classList.add('square-coord');
        coordLabel.textContent = sqIndex + 1;
        sqEl.appendChild(coordLabel);

        // Highlight selected square
        if (gameState.selectedSquare === sqIndex) {
          sqEl.classList.add('selected');
        }

        // Highlight last move
        if (gameState.lastMove && (gameState.lastMove.start === sqIndex || gameState.lastMove.end === sqIndex)) {
          sqEl.classList.add('last-move');
        }

        // Highlight legal target squares
        if (gameState.selectedSquare !== null) {
          const isTarget = gameState.legalMoves.some(
            m => m.start === gameState.selectedSquare && m.end === sqIndex
          );
          if (isTarget) {
            sqEl.classList.add('legal-target');
          }
        }

        // Render Piece if present
        const pieceVal = gameState.board[sqIndex];
        if (pieceVal !== EMPTY) {
          const pieceEl = document.createElement('div');
          pieceEl.classList.add('piece');

          if (pieceVal === BLACK_MAN || pieceVal === BLACK_KING) {
            pieceEl.classList.add('black-piece');
          } else {
            pieceEl.classList.add('red-piece');
          }

          if (pieceVal === BLACK_KING || pieceVal === RED_KING) {
            pieceEl.classList.add('king');
          }

          // Make piece draggable
          const isPieceTurn = (gameState.turn === 'black' && (pieceVal === BLACK_MAN || pieceVal === BLACK_KING)) ||
                              (gameState.turn === 'red' && (pieceVal === RED_MAN || pieceVal === RED_KING));

          const canHumanMove = (gameState.gameMode === 'edit' && isPieceTurn) ||
                               (gameState.gameMode === 'human' && gameState.turn === gameState.humanSide && isPieceTurn);

          if (canHumanMove && !gameState.isBotThinking && !gameState.isGameOver) {
            pieceEl.setAttribute('draggable', 'true');
            pieceEl.addEventListener('dragstart', (e) => onDragStart(e, sqIndex));
          }

          sqEl.appendChild(pieceEl);
        }

        // Square click listener
        sqEl.addEventListener('click', () => onSquareClick(sqIndex));
        sqEl.addEventListener('dragover', onDragOver);
        sqEl.addEventListener('drop', (e) => onDrop(e, sqIndex));
      }

      boardEl.appendChild(sqEl);
    }
  }
}

// Click and Drag & Drop handlers
function onSquareClick(sqIndex) {
  if (gameState.isGameOver || gameState.isBotThinking) return;

  const canClick = (gameState.gameMode === 'edit') ||
                   (gameState.gameMode === 'human' && gameState.turn === gameState.humanSide);

  if (!canClick) return;

  const piece = gameState.board[sqIndex];
  const isPieceTurn = (gameState.turn === 'black' && (piece === BLACK_MAN || piece === BLACK_KING)) ||
                      (gameState.turn === 'red' && (piece === RED_MAN || piece === RED_KING));

  if (gameState.selectedSquare === null) {
    if (isPieceTurn) {
      gameState.selectedSquare = sqIndex;
      renderBoard();
    }
  } else {
    if (gameState.selectedSquare === sqIndex) {
      gameState.selectedSquare = null;
      renderBoard();
    } else if (isPieceTurn) {
      gameState.selectedSquare = sqIndex;
      renderBoard();
    } else {
      // Try to make move from selectedSquare to sqIndex
      attemptUserMove(gameState.selectedSquare, sqIndex);
    }
  }
}

function onDragStart(e, sqIndex) {
  gameState.selectedSquare = sqIndex;
  e.dataTransfer.setData('text/plain', sqIndex);
  renderBoard();
}

function onDragOver(e) {
  e.preventDefault();
}

function onDrop(e, targetSq) {
  e.preventDefault();
  const startSq = parseInt(e.dataTransfer.getData('text/plain'), 10);
  if (!isNaN(startSq)) {
    attemptUserMove(startSq, targetSq);
  }
}

async function attemptUserMove(startSq, endSq) {
  const moveObj = gameState.legalMoves.find(m => m.start === startSq && m.end === endSq);

  if (!moveObj) {
    gameState.selectedSquare = null;
    renderBoard();
    return;
  }

  // Execute Move
  gameState.selectedSquare = null;
  gameState.lastMove = { start: startSq, end: endSq };
  try {
    const res = await fetch('/api/apply-move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        position: generatePositionString(),
        move: moveObj.notation,
        clock: gameState.reversiblePlies,
        history: gameState.positionHistory,
        rules_profile: gameState.rulesProfile,
      })
    });

    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || `apply-move failed (${res.status})`);
    }
    gameState.moveHistory.push({
      player: gameState.turn,
      notation: moveObj.notation,
      actor: 'human',
    });
    updateGameState(data);
    gameState.positionHistory.push(generatePositionString());
    renderBoard();
    updateMoveHistoryUI();

    checkBotTurn();
  } catch (err) {
    console.error('Failed to apply move:', err);
    setStatusMessage('เกิดข้อผิดพลาดในการเดินหมาก');
  }
}

function checkBotTurn() {
  if (gameState.isGameOver || gameState.gameMode === 'edit') return;

  const isBotMove = (gameState.gameMode === 'bot') ||
                    (gameState.gameMode === 'human' && gameState.turn !== gameState.humanSide);

  if (isBotMove) {
    triggerBotSearch();
  }
}

async function triggerBotSearch() {
  if (gameState.isBotThinking || gameState.isGameOver) return;

  // Freeze the request values. The user may change a select box while the
  // search is running; exported evidence must describe what the server
  // actually searched, not whatever happens to be selected afterwards.
  const searchSettings = Object.freeze({
    time_sec: gameState.thinkTimeSec,
    threads: gameState.engineThreads,
    hash_mb: gameState.engineHashMb,
    mode: gameState.engineMode,
    rules_profile: gameState.rulesProfile,
  });

  gameState.isBotThinking = true;
  const generation = gameGeneration;
  const controller = new AbortController();
  activeSearchController = controller;
  setStatusMessage(
    `เอนจิ้นกำลังคิด... ${searchSettings.time_sec}s · ` +
    `${searchSettings.threads} Thread${searchSettings.threads > 1 ? 's' : ''} · ` +
    `Hash ${searchSettings.hash_mb} MB`
  );

  const posStr = generatePositionString();

  try {
    const res = await fetch('/api/bestmove', {
      signal: controller.signal,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        position: posStr,
        clock: gameState.reversiblePlies,
        time_sec: searchSettings.time_sec,
        depth: 64,
        use_full_time: true,
        threads: searchSettings.threads,
        hash_mb: searchSettings.hash_mb,
        mode: searchSettings.mode,
        history: gameState.positionHistory,
        rules_profile: searchSettings.rules_profile,
      })
    });

    const data = await res.json();
    if (generation !== gameGeneration) return;

    if (data.error || !data.bestmove) {
      throw new Error(data.error || 'Engine did not return a move');
    }

    // Update Eval metrics in UI
    updateEvalUI(data);

    // Apply Bot Move
    const botMoveNotation = data.bestmove;
    const moves = gameState.legalMoves;
    const matchedMove = moves.find(m => m.notation.toLowerCase() === botMoveNotation.toLowerCase()) || moves[0];

    if (matchedMove) {
      gameState.lastMove = { start: matchedMove.start, end: matchedMove.end };
    }

    const applyRes = await fetch('/api/apply-move', {
      signal: controller.signal,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        position: posStr,
        move: botMoveNotation,
        clock: gameState.reversiblePlies,
        history: gameState.positionHistory,
        rules_profile: searchSettings.rules_profile,
      })
    });

    const applyData = await applyRes.json();
    if (generation !== gameGeneration) return;
    if (!applyRes.ok || applyData.error) {
      throw new Error(applyData.error || `apply-move failed (${applyRes.status})`);
    }
    gameState.moveHistory.push({
      player: gameState.turn,
      notation: botMoveNotation,
      actor: 'engine',
      engine: {
        ...(data.provenance_version === 'search-v1'
          ? { provenance_version: 'search-v1' }
          : {}),
        think_time_seconds: searchSettings.time_sec,
        requested_time_ms: data.requested_time_ms,
        elapsed_ms: data.elapsed_ms,
        request_elapsed_ms: data.request_elapsed_ms,
        pre_search_setup_ms: data.pre_search_setup_ms,
        depth_limit: data.depth_limit,
        depth: data.depth,
        common_depth: data.common_depth,
        selective_root: data.selective_root,
        nodes: data.nodes,
        score: data.score,
        pv: Array.isArray(data.pv) ? data.pv : [],
        wdl: data.wdl,
        tablebase_hits: data.tablebase_hits,
        threads: data.threads,
        hash_mb: data.hash_mb,
        hash_allocated_mb: data.hash_allocated_mb,
        mode: data.mode,
        rules_profile: data.rules_profile,
        search_backend: data.search_backend,
        native_library: data.native_library,
        native_library_sha256: data.native_library_sha256,
        native_search_abi: data.native_search_abi,
        nnue_enabled: data.nnue_enabled,
        nnue_feature_abi: data.nnue_feature_abi,
        nnue_model: data.nnue_model,
        nnue_model_sha256: data.nnue_model_sha256,
        nnue_source_model_sha256: data.nnue_source_model_sha256,
        native_tablebase_ready: data.native_tablebase_ready,
        native_tablebase_error: data.native_tablebase_error,
        runtime_isolation: data.runtime_isolation,
        native_error: data.native_error,
        evaluator_used: data.evaluator_used,
        release_id: data.release_id,
        release_manifest_sha256: data.release_manifest_sha256,
      },
    });
    updateGameState(applyData);
    gameState.positionHistory.push(generatePositionString());
    renderBoard();
    updateMoveHistoryUI();

    if (!gameState.isGameOver) {
      setStatusMessage(`เอนจิ้นเดิน: ${botMoveNotation}`);

      // If Bot vs Bot mode, trigger next step after short delay
      if (gameState.gameMode === 'bot') {
        gameState.botVsBotTimer = setTimeout(() => checkBotTurn(), 600);
      }
    }
  } catch (err) {
    if (generation !== gameGeneration || err.name === 'AbortError') return;
    console.error('Failed bot search:', err);
    document.getElementById('val-evaluator').textContent = 'ไม่พร้อมใช้งาน';
    setStatusMessage(`เอนจิ้นไม่พร้อม: ${err.message}`);
  } finally {
    if (generation === gameGeneration) {
      gameState.isBotThinking = false;
      activeSearchController = null;
    }
  }
}

function showEngineIdentity(data) {
  const backend = data.configured_backend || data.search_backend || 'unavailable';
  document.getElementById('val-evaluator').textContent = data.nnue_enabled ? 'NNUE v1' : 'HCE';
  document.getElementById('engine-identity').textContent =
    `${data.nnue_enabled ? 'NNUE v1' : 'HCE'} · ${backend} · ` +
    `${data.threads}T · TT ${data.hash_allocated_mb}/${data.hash_mb} MiB`;
  document.getElementById('engine-identity').title =
    `DLL: ${data.native_library_sha256 || '-'}\nModel: ${data.nnue_model_sha256 || '-'}\nRelease: ${data.release_id || 'explicit'}`;
}

async function loadEngineIdentity() {
  try {
    const response = await fetch('/api/engine', {method:'POST'});
    const data = await response.json();
    if (!response.ok || data.error || data.native_error) throw new Error(data.error || data.native_error);
    showEngineIdentity(data);
  } catch (error) {
    document.getElementById('engine-identity').textContent = `เอนจิ้นไม่พร้อม: ${error.message}`;
    document.getElementById('val-evaluator').textContent = 'ไม่พร้อมใช้งาน';
    setStatusMessage(`เอนจิ้นไม่พร้อม: ${error.message}`);
  }
}

function updateEvalUI(data) {
  showEngineIdentity(data);
  document.getElementById('val-depth').textContent = data.depth || '-';
  document.getElementById('val-nodes').textContent = (data.nodes || 0).toLocaleString();
  document.getElementById('val-time').textContent = `${data.elapsed_ms || 0} ms`;
  document.getElementById('val-wdl').textContent = data.wdl || 'UNKNOWN';
  document.getElementById('val-evaluator').textContent = data.nnue_enabled
    ? 'NNUE v1'
    : 'HCE';

  const pvText = data.pv ? data.pv.slice(0, 6).join(' ') : '-';
  document.getElementById('val-pv').textContent = pvText;

  // Convert centipawn score to percentage for eval bar
  const cpScore = data.score || 0;
  document.getElementById('eval-score-text').textContent = (cpScore / 100).toFixed(2);

  // Map cp score (-1000..+1000) to 0%..100%
  let evalPct = 50 + (cpScore / 10);
  evalPct = Math.max(5, Math.min(95, evalPct));
  document.getElementById('eval-bar-fill').style.width = `${evalPct}%`;
}

function updateMoveHistoryUI() {
  const listEl = document.getElementById('move-list');
  listEl.innerHTML = '';

  for (let i = 0; i < gameState.moveHistory.length; i += 2) {
    const moveNum = Math.floor(i / 2) + 1;
    const blackMove = gameState.moveHistory[i] ? gameState.moveHistory[i].notation : '';
    const redMove = gameState.moveHistory[i + 1] ? gameState.moveHistory[i + 1].notation : '';

    const entryEl = document.createElement('div');
    entryEl.classList.add('move-entry');
    entryEl.innerHTML = `
      <span class="move-num">${moveNum}.</span>
      <span class="move-black">${blackMove}</span>
      <span class="move-red">${redMove}</span>
    `;
    listEl.appendChild(entryEl);
  }

  // Scroll to bottom
  listEl.scrollTop = listEl.scrollHeight;
}

function buildGameRecord() {
  const engineMoves = gameState.moveHistory.filter(move => move.actor === 'engine');
  const provenanceVersion = (
    engineMoves.length > 0 &&
    engineMoves.every(move => move.engine?.provenance_version === 'search-v1')
  ) ? 'search-v1' : null;

  return JSON.stringify({
    format: 'thai-makhos-game-v1',
    start_position: gameState.startPosition || generatePositionString(),
    start_reversible_plies: gameState.startReversiblePlies,
    final_position: generatePositionString(),
    reversible_plies: gameState.reversiblePlies,
    position_history: gameState.positionHistory,
    moves: gameState.moveHistory.map((move, index) => ({
      ply: index + 1,
      player: move.player,
      notation: move.notation,
      actor: move.actor,
      ...(move.engine ? { engine: move.engine } : {}),
    })),
    engine: {
      provenance_version: provenanceVersion,
      think_time_seconds: gameState.thinkTimeSec,
      threads: gameState.engineThreads,
      hash_mb: gameState.engineHashMb,
      mode: gameState.engineMode,
      game_mode: gameState.gameMode,
      human_side: gameState.humanSide,
      rules_profile: gameState.rulesProfile,
    },
  }, null, 2);
}

async function copyGameRecord() {
  const record = buildGameRecord();
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(record);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = record;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    setStatusMessage(`📋 คัดลอกบันทึกเกมแล้ว (${gameState.moveHistory.length} ตา)`);
  } catch (err) {
    console.error('Failed to copy game record:', err);
    setStatusMessage('คัดลอกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง');
  }
}

function setStatusMessage(msg) {
  document.getElementById('status-message').textContent = msg;
}
