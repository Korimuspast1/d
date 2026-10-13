// Formicarium 2D - pixel style with physics (sand falling) and ant simulation
// ---------------------------------------------------------------
// Canvas setup
const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
  canvas.width = window.innerWidth - 20;
  canvas.height = window.innerHeight - 200 - 20; // space for UI
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

// Grid configuration
const CELL = 10; // pixel size per cell
const COLS = Math.floor(canvas.width / CELL);
const ROWS = Math.floor(canvas.height / CELL);

// Tile types: 'empty', 'sand', 'water', 'food'
let world = new Array(ROWS).fill().map(() => new Array(COLS).fill('empty'));

// Ants: each ant has r,c and maybe direction
let ants = [];

// Physics flag
let physicsEnabled = true;

// UI references
const btnSpawnAnt = document.getElementById('btn-spawn-ant');
const btnAddSand = document.getElementById('btn-add-sand');
const btnAddWater = document.getElementById('btn-add-water');
const btnAddFood = document.getElementById('btn-add-food');
const btnClearAll = document.getElementById('btn-clear-all');
const physicsToggle = document.getElementById('physics-toggle'); // will add later

// ---- UI actions ----
btnSpawnAnt.addEventListener('click', () => {
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
  physicsEnabled = true;
});

// Physics: sand gravity
function applySandGravity() {
  if (!physicsEnabled) return;
  // iterate from bottom-1 up to 0 so that sand above can fall
  for (let r = ROWS-2; r >= 0; r--) {
    for (let c = 0; c < COLS; c++) {
      if (world[r][c] !== 'sand') continue;
      // check cell below
      if (world[r+1][c] === 'empty') {
        // swap
        world[r+1][c] = 'sand';
        world[r][c] = 'empty';
        // after falling, we might need to check again; loop will handle
      } else if (world[r+1][c] === 'sand' && c > 0 && c < COLS-1) {
        // try to fall to side randomly
        const side = Math.random() < 0.5 ? -1 : 1;
        const nc = c + side;
        if (world[r+1][nc] === 'empty') {
          world[r+1][nc] = 'sand';
          world[r][c] = 'empty';
        }
      }
    }
  }
}

// Ant movement
function updateAnts() {
  const moves = [
    {dr: -1, dc: 0}, // up
    {dr: 1, dc: 0},  // down
    {dr: 0, dc: -1}, // left
    {dr: 0, dc: 1},  // right
  ];
  for (const ant of ants) {
    // random direction change
    ant.dir = Math.floor(Math.random()*4);
    const m = moves[ant.dir];
    let nr = ant.r + m.dr;
    let nc = ant.c + m.dc;
    // wrap around horizontally, but keep within rows vertically (bounce at walls)
    if (nc < 0) nc = COLS - 1;
    if (nc >= COLS) nc = 0;
    // vertical wrapping optional; we'll just keep within bounds
    if (nr < 0) nr = 0;
    if (nr >= ROWS) nr = ROWS - 1;
    // move if target cell is empty or food
    if (world[nr][nc] === 'empty' || world[nr][nc] === 'food') {
      ant.r = nr;
      ant.c = nc;
      if (world[nr][nc] === 'food') world[nr][nc] = 'empty';
    }
    // if target is sand or water, ant stays put (could be modified)
  }
}

// Render everything
function render() {
  // clear canvas with sand color background
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
        empty: '#222222',
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

// Game loop
function gameLoop() {
  applySandGravity();
  updateAnts();
  render();
  requestAnimationFrame(gameLoop);
}

// Start loop
gameLoop();

// Optional: mouse interaction to add sand
canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const c = Math.floor(x / CELL);
  const r = Math.floor(y / CELL);
  if (c >= 0 && c < COLS && r >= 0 && r < ROWS) {
    world[r][c] = 'sand';
  }
});

// physics toggle button handling (if exists)
if (typeof physicsToggle !== 'undefined') {
  physicsToggle.addEventListener('click', () => {
    physicsEnabled = !physicsEnabled;
  });
}

const physicsToggle = document.getElementById('physics-toggle');
physicsToggle.addEventListener('click', () => {
  physicsEnabled = !physicsEnabled;
  physicsToggle.textContent = physicsEnabled ? 'Physics On' : 'Physics Off';
});

// End of script