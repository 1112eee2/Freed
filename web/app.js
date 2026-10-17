/**
 * Freed Web GUI Frontend Application.
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
  engineThreads: 12,
  engineHashMb: 512,
  engineMode: 'win',
  rulesProfile: 'project',
  isBotThinking: false,
  isGameOver: false,
  isLoading: false,
  isMovePending: false,
  isPaused: false,
  undoStack: [],
  result: null,
  rulesResult: null,
  savedPath: null,
  botVsBotTimer: null,
};

const SETTINGS_STORAGE_KEY = 'thai-makhos-engine-settings-v1';
let gameGeneration = 0;
let activeSearchController = null;
let activeMoveController = null;
let recordRevision = 0;
let savePending = false;

function invalidateSearch() {
  gameGeneration += 1;
  if (activeSearchController) activeSearchController.abort();
  if (activeMoveController) activeMoveController.abort();
  activeSearchController = null;
  activeMoveController = null;
  clearTimeout(gameState.botVsBotTimer);
  gameState.botVsBotTimer = null;
  gameState.isBotThinking = false;
  gameState.isMovePending = false;
}

function markRecordChanged() {
  recordRevision += 1;
  gameState.savedPath = null;
  document.getElementById('save-game-status').textContent = '';
}

function resetGameRecord() {
  gameState.undoStack = [];
  gameState.result = null;
  gameState.rulesResult = null;
  gameState.isPaused = false;
  document.getElementById('select-game-result').value = '';
  markRecordChanged();
}

// Display names only. The engine's 'black' side starts on squares 25-32 and
// moves first; the GUI shows it as red (Thai convention). Side ids, position
// strings (B/R), API payloads and saved records keep the engine's names.
const SIDE_NAME = { black: 'แดง', red: 'ดำ' };
const SIDE_NAME_EN = { black: 'RED', red: 'BLACK' };
const SIDE_DOT = { black: '🔴', red: '⚫' };

function resultLabel(result) {
  if (!result) return 'ยังไม่จบเกม';
  if (result.winner === null) return 'เสมอ';
  const loser = result.winner === 'black' ? 'red' : 'black';
  return `${SIDE_NAME[result.winner]}ชนะ · ${SIDE_NAME[loser]}แพ้`;
}

function updateGameControls() {
  const ready = Boolean(gameState.startPosition) && !gameState.isLoading;
  for (const id of ['btn-mode-human', 'btn-mode-bot', 'btn-mode-edit', 'select-human-side']) {
    document.getElementById(id).disabled = gameState.isLoading;
  }
  document.getElementById('btn-undo-move').disabled = !ready || gameState.undoStack.length === 0;
  document.getElementById('btn-resume-game').disabled = !ready || !gameState.isPaused || gameState.isGameOver;
  document.getElementById('select-game-result').disabled = !ready;
  document.getElementById('btn-adjudicate-game').disabled = !ready || !document.getElementById('select-game-result').value;
  const saveButton = document.getElementById('btn-save-game');
  saveButton.disabled = !ready || !gameState.isGameOver || savePending || Boolean(gameState.savedPath);
  saveButton.textContent = savePending ? 'กำลังบันทึก…' : gameState.savedPath ? '✓ บันทึกแล้ว' : '💾 บันทึกเกม';
  document.getElementById('game-result-summary').textContent = resultLabel(gameState.result) +
    (gameState.result ? (gameState.result.source === 'user' ? ' (ผู้ใช้ตัดสิน)' : ' (ตามกติกา)') : '');
}

function commitMove(data, record, move) {
  // One snapshot per completed turn: a multi-capture is still exactly one ply.
  gameState.undoStack.push(JSON.parse(JSON.stringify({
    board: gameState.board, turn: gameState.turn,
    reversiblePlies: gameState.reversiblePlies, legalMoves: gameState.legalMoves,
    lastMove: gameState.lastMove, rulesResult: gameState.rulesResult,
  })));
  gameState.moveHistory.push(record);
  gameState.lastMove = move ? {start: move.start, end: move.end} : null;
  markRecordChanged();
  updateGameState(data);
  gameState.positionHistory.push(generatePositionString());
  renderBoard();
  updateMoveHistoryUI();
  updateGameControls();
}

function undoLastPly() {
  if (gameState.isLoading || gameState.undoStack.length === 0) return;
  invalidateSearch();
  Object.assign(gameState, gameState.undoStack.pop());
  gameState.moveHistory.pop();
  gameState.positionHistory.pop();
  gameState.selectedSquare = null;
  gameState.isGameOver = false;
  gameState.result = null;
  // Do not let the bot immediately replay the move the user just took back.
  gameState.isPaused = true;
  document.getElementById('select-game-result').value = '';
  markRecordChanged();
  resetEvalUI();
  renderBoard();
  updateMoveHistoryUI();
  updateTurnBadges();
  updateGameControls();
  setStatusMessage('↶ ย้อนแล้ว 1 ตา (1 ply) · พักเกมอยู่ กด “เล่นต่อ” เมื่อพร้อม');
}

function resumeGame() {
  if (gameState.isLoading || gameState.isGameOver || !gameState.isPaused) return;
  gameState.isPaused = false;
  updateTurnBadges();
  updateGameControls();
  renderBoard();
  setStatusMessage(`เล่นต่อ · ${SIDE_NAME[gameState.turn]} เดิน`);
  checkBotTurn();
}

function adjudicateGame() {
  const choice = document.getElementById('select-game-result').value;
  if (gameState.isLoading || !gameState.startPosition || !['black', 'red', 'draw'].includes(choice)) return;
  invalidateSearch();
  gameState.result = {source: 'user', winner: choice === 'draw' ? null : choice, reason: 'user_adjudication'};
  gameState.isGameOver = true;
  gameState.isPaused = false;
  gameState.selectedSquare = null;
  markRecordChanged();
  renderBoard();
  updateTurnBadges();
  updateGameControls();
  setStatusMessage(`ผู้ใช้ตัดสิน: ${resultLabel(gameState.result)} · กด “บันทึกเกม” เพื่อเก็บไฟล์`);
}

async function saveGameRecord() {
  if (!gameState.isGameOver || !gameState.startPosition || gameState.isLoading || savePending || gameState.savedPath) return;
  const revision = recordRevision;
  const record = buildGameRecord();
  savePending = true;
  updateGameControls();
  const status = document.getElementById('save-game-status');
  status.textContent = 'กำลังบันทึก…';
  try {
    const response = await fetch('/api/save-game', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: record,
    });
    const data = await response.json();
    if (!response.ok || !data.saved || typeof data.path !== 'string') throw new Error(data.error || 'บันทึกไม่สำเร็จ');
    if (revision !== recordRevision) return;
    gameState.savedPath = data.path;
    status.textContent = `บันทึกแล้ว: ${data.path}`;
  } catch (error) {
    if (revision === recordRevision) status.textContent = `บันทึกไม่สำเร็จ: ${error.message} · กดบันทึกเพื่อลองใหม่`;
  } finally {
    savePending = false;
    updateGameControls();
  }
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
    ['input-engine-threads', 'engineThreads', 'int'],
    ['input-engine-hash', 'engineHashMb', 'int'],
    ['select-engine-mode', 'engineMode', 'string'],
    ['select-rules-profile', 'rulesProfile', 'string'],
  ];
  for (const [elementId, stateKey, type] of bindings) {
    const element = document.getElementById(elementId);
    const raw = saved[stateKey];
    if (raw === undefined) continue;
    const value = String(raw);
    if (!settingAccepts(element, value)) continue;
    element.value = value;
    gameState[stateKey] = type === 'int'
      ? parseInt(value, 10)
      : (type === 'float' ? parseFloat(value) : value);
  }
}

// A select accepts one of its options; a number input accepts an integer
// inside its own min/max, the same range the server validates.
function settingAccepts(element, value) {
  if (element.options) return [...element.options].some(option => option.value === value);
  if (!/^\d+$/.test(value)) return false;
  const number = parseInt(value, 10);
  return number >= parseInt(element.min, 10) && number <= parseInt(element.max, 10);
}

// Typed values are rounded and clamped to the input's range; an empty or
// non-numeric entry keeps the previous value.
function readIntInput(element, previous) {
  const typed = Math.round(Number(element.value));
  const number = element.value.trim() === '' || !Number.isFinite(typed)
    ? previous
    : Math.min(parseInt(element.max, 10), Math.max(parseInt(element.min, 10), typed));
  element.value = String(number);
  return number;
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

  document.getElementById('input-engine-threads').addEventListener('change', (e) => {
    gameState.engineThreads = readIntInput(e.target, gameState.engineThreads);
    persistSettings();
  });

  document.getElementById('input-engine-hash').addEventListener('change', (e) => {
    gameState.engineHashMb = readIntInput(e.target, gameState.engineHashMb);
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
  document.getElementById('btn-undo-move').addEventListener('click', undoLastPly);
  document.getElementById('btn-resume-game').addEventListener('click', resumeGame);
  document.getElementById('select-game-result').addEventListener('change', updateGameControls);
  document.getElementById('btn-adjudicate-game').addEventListener('click', adjudicateGame);
  document.getElementById('btn-save-game').addEventListener('click', saveGameRecord);
}

function setMode(mode) {
  if (gameState.isLoading) return;
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
    // Edit mode plays both sides using legal moves. Keep its complete history
    // so switching controllers cannot erase repetition evidence or undo plies.
    updateMoveHistoryUI();
    setStatusMessage(`สลับโหมดเป็น ${mode === 'human' ? 'คน vs บอท' : 'บอท vs บอท'} พร้อมลุยต่อจากตำแหน่งนี้!`);
    renderBoard();
    checkBotTurn();
  } else {
    startNewGame();
  }
  updateGameControls();
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

  const topSide = gameState.isFlipped ? 'black' : 'red';
  const bottomSide = gameState.isFlipped ? 'red' : 'black';
  topDot.textContent = SIDE_DOT[topSide];
  topName.textContent = `${SIDE_NAME_EN[topSide]} (${SIDE_NAME[topSide]})`;
  bottomDot.textContent = SIDE_DOT[bottomSide];
  bottomName.textContent = `${SIDE_NAME_EN[bottomSide]} (${SIDE_NAME[bottomSide]})`;
  updateTurnBadges();
}

function updateTurnBadges() {
  const badgeTop = document.getElementById('badge-top');
  const badgeBottom = document.getElementById('badge-bottom');

  const topColor = gameState.isFlipped ? 'black' : 'red';
  const bottomColor = gameState.isFlipped ? 'red' : 'black';

  const label = gameState.isGameOver ? '' : gameState.isPaused ? 'พักเกม' : 'กำลังเดิน...';
  badgeTop.textContent = gameState.turn === topColor ? label : '';
  badgeBottom.textContent = gameState.turn === bottomColor ? label : '';
}

async function startNewGame() {
  invalidateSearch();
  const generation = gameGeneration;
  const controller = new AbortController();
  activeSearchController = controller;
  if (gameState.botVsBotTimer) {
    clearTimeout(gameState.botVsBotTimer);
    gameState.botVsBotTimer = null;
  }

  gameState.selectedSquare = null;
  gameState.lastMove = null;
  gameState.moveHistory = [];
  gameState.isGameOver = false;
  gameState.isBotThinking = false;
  gameState.isLoading = true;
  gameState.startPosition = null;
  gameState.positionHistory = [];
  resetGameRecord();
  resetEvalUI();
  updateMoveHistoryUI();
  updateGameControls();
  setStatusMessage('กำลังเริ่มเกมใหม่…');

  // Request initial state from backend
  try {
    const res = await fetch('/api/state', {
      signal: controller.signal,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        first: 2,
        rules_profile: gameState.rulesProfile,
      }) // The engine's black side (shown red) moves first
    });
    const data = await res.json();
    if (generation !== gameGeneration) return;
    if (!res.ok || data.error) throw new Error(data.error || 'Cannot start game');
    updateGameState(data);
    gameState.startPosition = generatePositionString();
    gameState.startReversiblePlies = gameState.reversiblePlies;
    gameState.positionHistory = [gameState.startPosition];
    gameState.isLoading = false;
    activeSearchController = null;
    renderBoard();
    updateMoveHistoryUI();
    updateGameControls();
    setStatusMessage(`เกมใหม่เริ่มแล้ว! ${SIDE_NAME.black}เดินก่อน`);

    checkBotTurn();
  } catch (err) {
    if (generation !== gameGeneration || err.name === 'AbortError') return;
    gameState.isLoading = false;
    gameState.isPaused = true;
    activeSearchController = null;
    updateGameControls();
    console.error('Failed to start new game:', err);
    setStatusMessage('เกิดข้อผิดพลาดในการเชื่อมต่อเอนจิ้น');
  }
}

function updateGameState(data) {
  gameState.board = data.board;
  gameState.turn = data.turn;
  gameState.reversiblePlies = data.reversible_plies || 0;
  gameState.legalMoves = data.legal_moves || [];
  gameState.rulesResult = {terminal: Boolean(data.terminal), winner: data.winner || null, reason: data.reason || null};
  gameState.isGameOver = Boolean(data.terminal);
  gameState.result = data.terminal ? {source: 'rules', winner: data.winner || null, reason: data.reason} : null;

  if (data.terminal) {
    gameState.isGameOver = true;
    if (data.winner) {
      const winnerName = `${SIDE_NAME[data.winner]} (${SIDE_NAME_EN[data.winner]})`;
      setStatusMessage(`🏆 จบเกม! ${winnerName} ชนะ (${data.reason})`);
    } else {
      setStatusMessage(`🤝 จบเกม! เสมอกัน (${data.reason})`);
    }
  }
  updateTurnBadges();
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

          // Engine black is drawn red, engine red is drawn dark (see SIDE_NAME).
          if (pieceVal === BLACK_MAN || pieceVal === BLACK_KING) {
            pieceEl.classList.add('red-piece');
          } else {
            pieceEl.classList.add('black-piece');
          }

          if (pieceVal === BLACK_KING || pieceVal === RED_KING) {
            pieceEl.classList.add('king');
          }

          // Make piece draggable
          const isPieceTurn = (gameState.turn === 'black' && (pieceVal === BLACK_MAN || pieceVal === BLACK_KING)) ||
                              (gameState.turn === 'red' && (pieceVal === RED_MAN || pieceVal === RED_KING));

          const canHumanMove = (gameState.gameMode === 'edit' && isPieceTurn) ||
                               (gameState.gameMode === 'human' && gameState.turn === gameState.humanSide && isPieceTurn);

          if (canHumanMove && !gameState.isBotThinking && !gameState.isGameOver &&
              !gameState.isMovePending && !gameState.isPaused && !gameState.isLoading) {
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
  if (gameState.isGameOver || gameState.isBotThinking || gameState.isMovePending || gameState.isPaused || gameState.isLoading) return;

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
  if (gameState.isGameOver || gameState.isBotThinking || gameState.isMovePending || gameState.isPaused || gameState.isLoading) return;
  if (gameState.gameMode !== 'edit' && (gameState.gameMode !== 'human' || gameState.turn !== gameState.humanSide)) return;
  const moveObj = gameState.legalMoves.find(m => m.start === startSq && m.end === endSq);

  if (!moveObj) {
    gameState.selectedSquare = null;
    renderBoard();
    return;
  }

  // Execute Move
  gameState.selectedSquare = null;
  const generation = gameGeneration;
  const controller = new AbortController();
  activeMoveController = controller;
  gameState.isMovePending = true;
  try {
    const res = await fetch('/api/apply-move', {
      signal: controller.signal,
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
    if (generation !== gameGeneration) return;
    if (!res.ok || data.error) {
      throw new Error(data.error || `apply-move failed (${res.status})`);
    }
    commitMove(data, {
      player: gameState.turn,
      notation: moveObj.notation,
      actor: 'human',
    }, moveObj);
    gameState.isMovePending = false;
    activeMoveController = null;
    checkBotTurn();
  } catch (err) {
    if (generation !== gameGeneration || err.name === 'AbortError') return;
    console.error('Failed to apply move:', err);
    setStatusMessage('เกิดข้อผิดพลาดในการเดินหมาก');
  } finally {
    if (generation === gameGeneration) {
      gameState.isMovePending = false;
      activeMoveController = null;
      renderBoard();
      updateGameControls();
    }
  }
}

function checkBotTurn() {
  if (gameState.isGameOver || gameState.gameMode === 'edit' || gameState.isPaused || gameState.isLoading || gameState.isMovePending) return;

  const isBotMove = (gameState.gameMode === 'bot') ||
                    (gameState.gameMode === 'human' && gameState.turn !== gameState.humanSide);

  if (isBotMove) {
    triggerBotSearch();
  }
}

async function triggerBotSearch() {
  if (gameState.isBotThinking || gameState.isGameOver || gameState.isPaused || gameState.isLoading || gameState.isMovePending) return;

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
      // Readiness errors leave a resumable game; never apply a fallback move.
      if (data.tb3 && !data.tb3.ready) gameState.isPaused = true;
      throw new Error(data.error || 'Engine did not return a move');
    }

    // Update Eval metrics in UI
    updateEvalUI(data);

    // Apply Bot Move
    const botMoveNotation = data.bestmove;
    const moves = gameState.legalMoves;
    const matchedMove = moves.find(m => m.notation.toLowerCase() === botMoveNotation.toLowerCase()) || moves[0];

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
    commitMove(applyData, {
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
        tb3: data.tb3,
        runtime_isolation: data.runtime_isolation,
        native_error: data.native_error,
        evaluator_used: data.evaluator_used,
        release_id: data.release_id,
        release_manifest_sha256: data.release_manifest_sha256,
      },
    }, matchedMove);

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
      renderBoard();
      updateGameControls();
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
    applyServerReleaseDefaults(data);
  } catch (error) {
    document.getElementById('engine-identity').textContent = `เอนจิ้นไม่พร้อม: ${error.message}`;
    document.getElementById('val-evaluator').textContent = 'ไม่พร้อมใช้งาน';
    setStatusMessage(`เอนจิ้นไม่พร้อม: ${error.message}`);
  }
}

function applyServerReleaseDefaults(data) {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY) || '{}');
  } catch (_error) {
    saved = {};
  }
  const defaults = data.defaults || {};
  const defaultThreads = defaults.threads !== undefined ? defaults.threads : data.threads;
  const defaultHash = defaults.hash_mb_total !== undefined ? defaults.hash_mb_total : data.hash_mb;

  if (saved.engineThreads === undefined && defaultThreads !== undefined) {
    const input = document.getElementById('input-engine-threads');
    const valStr = String(defaultThreads);
    if (settingAccepts(input, valStr)) {
      input.value = valStr;
      gameState.engineThreads = defaultThreads;
    }
  }
  if (saved.engineHashMb === undefined && defaultHash !== undefined) {
    const input = document.getElementById('input-engine-hash');
    const valStr = String(defaultHash);
    if (settingAccepts(input, valStr)) {
      input.value = valStr;
      gameState.engineHashMb = defaultHash;
    }
  }
}

function resetEvalUI() {
  const elDepth = document.getElementById('val-depth');
  if (elDepth) elDepth.textContent = '-';
  const elNodes = document.getElementById('val-nodes');
  if (elNodes) elNodes.textContent = '-';
  const elTime = document.getElementById('val-time');
  if (elTime) elTime.textContent = '-';
  const elWdl = document.getElementById('val-wdl');
  if (elWdl) elWdl.textContent = '-';
  const elPv = document.getElementById('val-pv');
  if (elPv) elPv.textContent = '-';
  const elScore = document.getElementById('eval-score-text');
  if (elScore) elScore.textContent = '0.00';
  const elBar = document.getElementById('eval-bar-fill');
  if (elBar) elBar.style.width = '50%';
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
    result: gameState.result,
    rules_result: gameState.rulesResult,
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
