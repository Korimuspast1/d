// Formicarium 2D - pixel style
const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');

// Resize canvas to window
function resizeCanvas() {
  canvas.width = window.innerWidth - 20;
  canvas.height = window.innerHeight - 200 - 20; // leave space for UI
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

// World dimensions in cells
const CELL = 10; // pixel size for each tile
const COLS = Math.floor(canvas.width / CELL);
const ROWS = Math.floor(canvas.height / CELL);

// Tile types: 'empty', 'sand', 'water', 'food'
let world = new Array(ROWS).fill().map(() => new Array(COLS).fill('empty'));

// Ants array
let ants = [];

// UI references
const btnSpawnAnt = document.getElementById('btn-spawn-ant');
const btnAddSand = document.getElementById('btn-add-sand');
const btnAddWater = document.getElementById('btn-add-water');
const btnAddFood = document.getElementById('btn-add-food');
const btnClearAll = document.getElementById('btn-clear-all');

// ---- UI actions ----
btnSpawnAnt.addEventListener('click', () => {
  // spawn a ant at a random empty cell
  let empty = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (world[r][c] === 'empty') empty.push({r,c});
    }
  }
  if (empty.length === 0) return;
  const pos = empty[Math.floor(Math.random() * empty.length)];
  ants.push({ r: pos.r, c: pos.c, dir: Math.floor(Math.random()*4) });
});

btnAddSand.addEventListener('click', () => {
  // add sand at center
  const r = Math.floor(ROWS/2);
  const c = Math.floor(COLS/2);
  world[r][c] = 'sand';
});

btnAddWater.addEventListener('click', () => {
  const r = Math.floor(ROWS/2) - 1;
  const c = Math.floor(COLS/2);
  world[r][c] = 'water';
});

btnAddFood.addEventListener('click', () => {
  const r = Math.floor(ROWS/2) + 1;
  const c = Math.floor(COLS/2);
  world[r][c] = 'food';
});

btnClearAll.addEventListener('click', () => {
  world = new Array(ROWS).fill().map(() => new Array(COLS).fill('empty'));
  ants = [];
};

// ---- Game logic ----
function updateAnts() {
  // move each ant randomly
  for (const ant of ants) {
    // random direction change
    ant.dir = Math.floor(Math.random()*4);
    const moves = [
      {dr: -1, dc: 0}, // up
      {dr: 1, dc: 0},  // down
      {dr: 0, dc: -1}, // left
      {dr: 0, dc: 1},  // right
    ];
    const m = moves[ant.dir];
    let nr = ant.r + m.dr;
    let nc = ant.c + m.dc;
    // wrap around
    if (nr < 0) nr = ROWS - 1;
    if (nr >= ROWS) nr = 0;
    if (nc < 0) nc = COLS - 1;
    if (nc >= COLS) nc = 0;
    // if target cell is empty or food, move there; otherwise stay
    if (world[nr][nc] === 'empty' || world[nr][nc] === 'food') {
      ant.r = nr; ant.c = nc;
      // if food, remove food and maybe give score? just clear
      if (world[nr][nc] === 'food') world[nr][nc] = 'empty';
    }
    // if sand or water, stay put? could allow moving through sand? keep simple.
  }
}

function render() {
  // clear with sand color background
  ctx.fillStyle = '#f0e68c';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // draw tiles
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const tile = world[r][c];
      ctx.fillStyle = {
        sand: '#e6c26e',
        water: '#4a90e2',
        food: '#ffd700',
        empty: '#222222' // dark empty
      }[tile] || '#222';
      ctx.fillRect(c * CELL, r * CELL, CELL, CELL);
      // draw cell border
      ctx.strokeStyle = '#555';
      ctx.lineWidth = 1;
      ctx.strokeRect(c * CELL, r * CELL, CELL, CELL);
    }
  }

  // draw ants
  for (const ant of ants) {
    ctx.fillStyle = '#b22222'; // firebrick red
    ctx.beginPath();
    const x = ant.c * CELL + CELL/2;
    const y = ant.r * CELL + CELL/2;
    const radius = CELL/3;
    ctx.arc(x, y, radius, 0, Math.PI*2);
    ctx.fill();
  }
}

function gameLoop() {
  updateAnts();
  render();
  requestAnimationFrame(gameLoop);
}

// start loop
gameLoop();

// optional: mouse interaction to add tiles
canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const c = Math.floor(x / CELL);
  const r = Math.floor(y / CELL);
  if (c >= 0 && c < COLS && r >= 0 && r < ROWS) {
    // toggle sand on click
    world[r][c] = 'sand';
  }
});
