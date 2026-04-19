'use strict';

// ─── Config ─────────────────────────────────────────────────────────────────
// Use the same origin as the page so it works from any host/port served by Flask
const API = window.location.origin;

// ─── State ──────────────────────────────────────────────────────────────────
let lastResults = null;

// ─── Viz.js (client-side Graphviz) ───────────────────────────────────────────
let _vizInstance = null;
if (window.Viz) {
  Viz.instance().then(v => { _vizInstance = v; }).catch(() => {});
}

// ─── CFG pan/zoom state (viewBox-based — never blurry) ───────────────────────
// Instead of CSS transform (which rasterizes then upscales = blurry),
// we manipulate the SVG viewBox directly so the browser re-renders vectors.
let _cfgVB        = null;   // current viewBox {x, y, w, h}
let _cfgNaturalVB = null;   // original full-graph viewBox
let _cfgDragging  = false;
let _cfgDragStart = null;   // {screenX, screenY, vb: snapshot}
let _cfgDot  = null;
let _cfgView = 'graph';

// ─── DOM refs ────────────────────────────────────────────────────────────────
const editor      = document.getElementById('code-editor');
const gutter      = document.getElementById('editor-gutter');
const btnAnalyze  = document.getElementById('btn-analyze');
const btnClear    = document.getElementById('btn-clear');
const loading     = document.getElementById('loading-overlay');
const errorToast  = document.getElementById('error-toast');
const errorMsg    = document.getElementById('error-msg');
const samplesGrid = document.getElementById('samples-grid');
const btnShowDot  = document.getElementById('btn-show-dot');

// ─── Gutter (line numbers) ────────────────────────────────────────────────────
function updateGutter() {
  const lines = editor.value.split('\n').length;
  const nums = Array.from({length: lines}, (_, i) => i + 1).join('\n');
  gutter.textContent = nums;
  gutter.scrollTop = editor.scrollTop;
}
editor.addEventListener('input', updateGutter);
editor.addEventListener('scroll', () => { gutter.scrollTop = editor.scrollTop; });
editor.addEventListener('keydown', e => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = editor.selectionStart, end = editor.selectionEnd;
    editor.value = editor.value.slice(0, s) + '    ' + editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = s + 4;
    updateGutter();
  }
});
updateGutter();

// ─── Buttons ─────────────────────────────────────────────────────────────────
btnClear.addEventListener('click', () => {
  editor.value = '';
  updateGutter();
});
btnAnalyze.addEventListener('click', runAnalysis);

// Ctrl+Enter shortcut
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') runAnalysis();
});

// ─── Tabs ─────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// ─── DOT source toggle ────────────────────────────────────────────────────────
btnShowDot.addEventListener('click', () => {
  const ds = document.getElementById('cfg-dot-source');
  ds.classList.toggle('hidden');
  btnShowDot.textContent = ds.classList.contains('hidden') ? 'Show DOT Source' : 'Hide DOT Source';
});

// ─── Toast ────────────────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.textContent = msg;
  errorToast.classList.remove('hidden');
  setTimeout(() => errorToast.classList.add('hidden'), 6000);
}

// ─── Load samples ─────────────────────────────────────────────────────────────
async function loadSamples() {
  try {
    const res = await fetch(`${API}/samples`);
    const samples = await res.json();
    samplesGrid.innerHTML = '';
    for (const [key, s] of Object.entries(samples)) {
      const card = document.createElement('div');
      card.className = 'sample-card';
      card.innerHTML = `
        <div class="sample-card-title">${s.title}</div>
        <div class="sample-card-desc">${s.description}</div>
      `;
      card.addEventListener('click', () => {
        editor.value = s.code.trim();
        updateGutter();
      });
      samplesGrid.appendChild(card);
    }
  } catch {
    samplesGrid.innerHTML = '<p style="color:var(--text-muted);font-size:0.72rem">Could not load samples</p>';
  }
}
loadSamples();

// ─── Main analysis ────────────────────────────────────────────────────────────
async function runAnalysis() {
  const code = editor.value.trim();
  if (!code) { showError('Please enter some source code first.'); return; }

  loading.classList.remove('hidden');
  btnAnalyze.disabled = true;

  try {
    // Analyze
    const res = await fetch(`${API}/analyze`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code})
    });
    const data = await res.json();

    if (!data.success) {
      showError(data.error || 'Analysis failed');
      return;
    }

    lastResults = data.results;

    // Fetch DOT source for client-side Viz.js rendering
    const vizRes = await fetch(`${API}/visualize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code, format: 'dot'})
    });
    const vizData = await vizRes.json();

    renderAll(data.results, vizData);

    // Switch to overview tab
    document.querySelector('[data-tab="overview"]').click();

  } catch (e) {
    showError('Could not connect to analysis server. Make sure it is running on port 5050.');
  } finally {
    loading.classList.add('hidden');
    btnAnalyze.disabled = false;
  }
}

// ─── Render all tabs ──────────────────────────────────────────────────────────
function renderAll(results, vizData) {
  renderOverview(results);
  renderTAC(results);
  renderCFG(results, vizData);
  renderDeadCode(results);
  renderLiveness(results);
}

// ── Overview ──────────────────────────────────────────────────────────────────
function renderOverview(results) {
  document.getElementById('welcome-state').classList.add('hidden');
  const ov = document.getElementById('overview-results');
  ov.classList.remove('hidden');

  let totalBlocks=0, reachable=0, unreachStruct=0, unreachConst=0, deadItems=0, deadFuncs=0;
  results.forEach(r => {
    totalBlocks  += r.total_blocks;
    reachable    += r.reachable_blocks;
    unreachStruct+= r.unreachable_structural.length;
    unreachConst += r.unreachable_constant_folding.length;
    deadItems    += r.dead_code.reduce((acc,b)=>acc+b.dead_instructions.length, 0);
    if (r.is_dead_function) deadFuncs++;
  });

  // Count total removed instructions across all functions
  let totalRemoved = 0;
  results.forEach(r => { totalRemoved += (r.elimination_stats?.total_removed_instructions || 0); });

  ov.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card blue">
        <div class="stat-value">${totalBlocks}</div>
        <div class="stat-label">Total Blocks</div>
      </div>
      <div class="stat-card green">
        <div class="stat-value">${reachable}</div>
        <div class="stat-label">Reachable Blocks</div>
      </div>
      <div class="stat-card red">
        <div class="stat-value">${unreachStruct + unreachConst}</div>
        <div class="stat-label">Unreachable Blocks</div>
      </div>
      <div class="stat-card orange">
        <div class="stat-value">${deadItems}</div>
        <div class="stat-label">Dead Assignments</div>
      </div>
      <div class="stat-card purple">
        <div class="stat-value">${results.length}</div>
        <div class="stat-label">Functions</div>
      </div>
      <div class="stat-card red">
        <div class="stat-value">${deadFuncs}</div>
        <div class="stat-label">Dead Functions</div>
      </div>
    </div>
    <div style="margin-top:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <button class="btn btn-optimize" id="btn-show-optimized">
        <svg width="15" height="15" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
        View Optimized Code
      </button>
      ${totalRemoved > 0 ? `<span style="font-size:0.75rem;color:var(--green)">${totalRemoved} instruction(s) eliminated</span>` : '<span style="font-size:0.75rem;color:var(--text-muted)">No instructions to eliminate</span>'}
    </div>
  `;

  results.forEach(r => {
    const deadFuncBadge = r.is_dead_function
      ? ' <span style="background:#7f1d1d;color:#fca5a5;font-size:0.65rem;padding:2px 7px;border-radius:999px;font-weight:700;vertical-align:middle">DEAD FUNCTION</span>'
      : '';
    ov.innerHTML += `<div class="section-title">Function: ${escHtml(r.function)}()${deadFuncBadge}</div>`;

    // Dead function banner — shown first, prominently
    if (r.is_dead_function) {
      ov.innerHTML += `
        <div class="alert-card unreachable-struct" style="border-color:#dc2626">
          <div class="alert-title" style="color:#fca5a5">☠ Dead Function — Never Called</div>
          <div class="alert-sub">
            <strong>${escHtml(r.function)}()</strong> is declared but never called from any other function.
            The entire function body is unreachable at runtime and can be safely removed.
          </div>
        </div>`;
    }

    const totalUnreach = r.unreachable_structural.length + r.unreachable_constant_folding.length;
    const totalDead    = r.dead_code.reduce((a,b)=>a+b.dead_instructions.length,0);

    if (!r.is_dead_function && totalUnreach === 0 && totalDead === 0) {
      ov.innerHTML += `
        <div class="success-banner">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
          No dead code or unreachable paths detected in this function.
        </div>`;
      return;
    }

    r.unreachable_structural.forEach(b => {
      ov.innerHTML += `
        <div class="alert-card unreachable-struct">
          <div class="alert-title">⚠ Structurally Unreachable Block</div>
          <div class="alert-sub">Block: ${escHtml(b.label)} — not reachable from entry via any execution path</div>
          ${b.instructions.length ? `<ul class="instr-list">${b.instructions.map(i=>`<li>${escHtml(i)}</li>`).join('')}</ul>` : ''}
        </div>`;
    });

    r.unreachable_constant_folding.forEach(b => {
      ov.innerHTML += `
        <div class="alert-card unreachable-const">
          <div class="alert-title">🔍 Constant-Folding Unreachable Block</div>
          <div class="alert-sub">Block: ${escHtml(b.label)} — condition evaluates to a compile-time constant, making this branch infeasible</div>
          ${b.instructions.length ? `<ul class="instr-list">${b.instructions.map(i=>`<li>${escHtml(i)}</li>`).join('')}</ul>` : ''}
        </div>`;
    });

    r.dead_code.forEach(b => {
      const deadList = b.dead_instructions.map(d =>
        `<li class="dead-instr">${escHtml(d.instruction)}</li>`
      ).join('');
      ov.innerHTML += `
        <div class="alert-card dead">
          <div class="alert-title">✗ Dead Code in Block: ${escHtml(b.label)}</div>
          <div class="alert-sub">${b.dead_instructions.length} dead assignment(s) — values computed but never used</div>
          <ul class="instr-list">${deadList}</ul>
        </div>`;
    });
  });

  // Wire up AFTER forEach so innerHTML+= doesn't destroy the listener
  document.getElementById('btn-show-optimized').addEventListener('click', () => showOptimizedModal(results));
}

// ── Optimized Code Modal ──────────────────────────────────────────────────────
const optModal      = document.getElementById('opt-modal');
const optModalBody  = document.getElementById('opt-modal-body');
const optCopyBtn    = document.getElementById('opt-copy-btn');

function closeOptModal() { optModal.classList.add('hidden'); }
document.getElementById('opt-modal-close').addEventListener('click', closeOptModal);
document.getElementById('opt-modal-close2').addEventListener('click', closeOptModal);
optModal.addEventListener('click', e => { if (e.target === optModal) closeOptModal(); });

let _optAllLines = [];   // flat list for copy

function showOptimizedModal(results) {
  optModalBody.innerHTML = '';
  _optAllLines = [];

  results.forEach(r => {
    const stats = r.elimination_stats || {};
    const orig  = stats.original_instruction_count  || 0;
    const opt   = stats.optimized_instruction_count || 0;
    const removed = stats.total_removed_instructions || 0;
    const pct   = orig > 0 ? Math.round((removed / orig) * 100) : 0;

    // Stats bar for this function
    const funcLabel = r.is_dead_function
      ? `${r.function}() <span style="color:#fca5a5;font-size:0.7rem">[DEAD FUNCTION — entire body eliminated]</span>`
      : r.function + '()';

    optModalBody.innerHTML += `
      <div class="opt-func-section">
        <div class="opt-func-title">${funcLabel}</div>
        <div class="opt-stats-row">
          <span class="opt-stat"><span class="opt-stat-num">${orig}</span> original</span>
          <span class="opt-arrow">→</span>
          <span class="opt-stat"><span class="opt-stat-num" style="color:var(--green)">${opt}</span> optimized</span>
          ${removed > 0
            ? `<span class="opt-removed">−${removed} removed (${pct}%)</span>`
            : `<span style="color:var(--text-muted);font-size:0.72rem">nothing to remove</span>`}
        </div>
      </div>`;

    // Breakdown chips
    if (removed > 0) {
      const chips = [];
      if (stats.removed_unreachable_instructions > 0)
        chips.push(`<span class="opt-chip red">${stats.removed_unreachable_instructions} unreachable block instr.</span>`);
      if (stats.removed_dead_instructions > 0)
        chips.push(`<span class="opt-chip orange">${stats.removed_dead_instructions} dead assignments</span>`);
      if (chips.length)
        optModalBody.innerHTML += `<div class="opt-chips">${chips.join('')}</div>`;
    }

    // Optimized TAC listing
    const lines = r.optimized_tac || [];
    if (r.is_dead_function) {
      optModalBody.innerHTML += `<div class="opt-dead-fn-msg">Function body fully eliminated — not emitted in optimized output.</div>`;
    } else if (lines.length === 0) {
      optModalBody.innerHTML += `<div class="opt-dead-fn-msg" style="color:var(--text-muted)">No instructions remain.</div>`;
    } else {
      const listEl = document.createElement('div');
      listEl.className = 'opt-tac-list';
      lines.forEach((line, idx) => {
        _optAllLines.push(line);
        const lo = line.toLowerCase();
        let cls = 'opt-tac-line';
        if (lo.startsWith('label'))    cls += ' is-label';
        if (lo.startsWith('goto'))     cls += ' is-goto';
        if (lo.startsWith('if_false')) cls += ' is-branch';
        if (lo.startsWith('return'))   cls += ' is-return';
        listEl.innerHTML += `<div class="${cls}"><span class="opt-line-num">${idx + 1}</span><span>${escHtml(line)}</span></div>`;
      });
      optModalBody.appendChild(listEl);
    }

    optModalBody.innerHTML += '<div class="opt-func-divider"></div>';
  });

  optModal.classList.remove('hidden');
}

optCopyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(_optAllLines.join('\n')).then(() => {
    optCopyBtn.textContent = 'Copied!';
    setTimeout(() => { optCopyBtn.textContent = 'Copy Optimized TAC'; }, 2000);
  }).catch(() => {
    optCopyBtn.textContent = 'Copy failed';
    setTimeout(() => { optCopyBtn.textContent = 'Copy Optimized TAC'; }, 2000);
  });
});

// ── Three-Address Code ─────────────────────────────────────────────────────────
function renderTAC(results) {
  document.getElementById('tac-empty').classList.add('hidden');
  const tc = document.getElementById('tac-content');
  tc.classList.remove('hidden');
  tc.innerHTML = '';

  const renderTacList = (parent, lines, title) => {
    const header = document.createElement('div');
    header.className = 'tac-func-header';
    header.textContent = title;
    parent.appendChild(header);

    const list = document.createElement('div');
    list.className = 'tac-instr-list';
    lines.forEach((line, i) => {
      const row = document.createElement('div');
      const lo = line.toLowerCase();
      if (lo.startsWith('label')) row.className = 'tac-instr is-label';
      else if (lo.startsWith('goto')) row.className = 'tac-instr is-goto';
      else if (lo.startsWith('if_false')) row.className = 'tac-instr is-branch';
      else if (lo.startsWith('return')) row.className = 'tac-instr is-return';
      else row.className = 'tac-instr';
      row.innerHTML = `<span class="tac-line-num">${i + 1}</span><span class="tac-code">${escHtml(line)}</span>`;
      list.appendChild(row);
    });
    parent.appendChild(list);
  };

  results.forEach(r => {
    const div = document.createElement('div');
    div.className = 'tac-func';

    renderTacList(div, r.tac || [], `// Function: ${r.function}() - Original TAC`);

    if (Array.isArray(r.optimized_tac) && r.optimized_tac.length) {
      renderTacList(div, r.optimized_tac, `// Function: ${r.function}() - Optimized TAC`);
    }

    tc.appendChild(div);
  });
}

// ── CFG ───────────────────────────────────────────────────────────────────────
function renderCFG(results, vizData) {
  document.getElementById('cfg-empty').classList.add('hidden');
  document.getElementById('cfg-content').classList.remove('hidden');

  _cfgDot = (vizData && vizData.dot) || null;
  if (_cfgDot) document.getElementById('dot-pre').textContent = _cfgDot;

  // Toggle buttons
  document.getElementById('cfg-graph-btn').onclick = () => { _cfgView = 'graph';  _cfgApplyView(results); };
  document.getElementById('cfg-block-btn').onclick = () => { _cfgView = 'blocks'; _cfgApplyView(results); };

  // Zoom buttons — operate on the viewBox
  document.getElementById('cfg-zoom-in').onclick    = () => _cfgZoom(1.3);
  document.getElementById('cfg-zoom-out').onclick   = () => _cfgZoom(1 / 1.3);
  document.getElementById('cfg-zoom-reset').onclick = _cfgFit;

  // Mouse pan/wheel zoom — attach once
  const container = document.getElementById('cfg-graph-container');
  if (!container.dataset.eventsAttached) {
    container.dataset.eventsAttached = '1';

    container.addEventListener('wheel', e => {
      e.preventDefault();
      _cfgZoom(e.deltaY < 0 ? 1.12 : 0.89, e.clientX, e.clientY);
    }, { passive: false });

    container.addEventListener('mousedown', e => {
      if (!_cfgVB) return;
      _cfgDragging  = true;
      _cfgDragStart = { sx: e.clientX, sy: e.clientY, vb: { ..._cfgVB } };
      container.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', e => {
      if (!_cfgDragging || !_cfgVB || !_cfgDragStart) return;
      const rect = container.getBoundingClientRect();
      const dx = (e.clientX - _cfgDragStart.sx) / rect.width  * _cfgVB.w;
      const dy = (e.clientY - _cfgDragStart.sy) / rect.height * _cfgVB.h;
      _cfgVB.x = _cfgDragStart.vb.x - dx;
      _cfgVB.y = _cfgDragStart.vb.y - dy;
      _cfgApplyVB();
    });
    window.addEventListener('mouseup', () => {
      _cfgDragging = false;
      container.style.cursor = 'grab';
    });
  }

  _cfgView = 'graph';
  _cfgApplyView(results);
}

function _cfgApplyView(results) {
  const graphCont    = document.getElementById('cfg-graph-container');
  const blockDisplay = document.getElementById('cfg-display');
  const zoomControls = document.getElementById('cfg-zoom-controls');

  document.getElementById('cfg-graph-btn').classList.toggle('active', _cfgView === 'graph');
  document.getElementById('cfg-block-btn').classList.toggle('active', _cfgView === 'blocks');

  if (_cfgView === 'graph') {
    graphCont.classList.remove('hidden');
    blockDisplay.classList.add('hidden');
    zoomControls.style.visibility = 'visible';
    _cfgRenderGraph();
  } else {
    graphCont.classList.add('hidden');
    blockDisplay.classList.remove('hidden');
    zoomControls.style.visibility = 'hidden';
    _cfgRenderBlocks(results);
  }
}

function _cfgRenderGraph() {
  const inner = document.getElementById('cfg-graph-inner');
  inner.innerHTML = '';
  _cfgVB = null; _cfgNaturalVB = null;

  if (!_cfgDot) {
    inner.innerHTML = '<p style="color:var(--text-muted);padding:32px;text-align:center">No DOT source available</p>';
    return;
  }
  if (!_vizInstance) {
    inner.innerHTML = '<p style="color:var(--text-muted);padding:32px;text-align:center">Viz.js loading… retry in a moment</p>';
    Viz.instance().then(v => { _vizInstance = v; _cfgRenderGraph(); })
                  .catch(() => { inner.innerHTML = '<p style="color:var(--red);padding:32px;text-align:center">Could not load Viz.js (check network)</p>'; });
    return;
  }

  try {
    const svg = _vizInstance.renderSVGElement(_cfgDot);

    // Parse the natural viewBox Graphviz embedded in the SVG
    const vbStr = svg.getAttribute('viewBox');
    if (vbStr) {
      const [x, y, w, h] = vbStr.trim().split(/[\s,]+/).map(Number);
      _cfgNaturalVB = { x, y, w, h };
    } else {
      const w = parseFloat(svg.getAttribute('width'))  || 800;
      const h = parseFloat(svg.getAttribute('height')) || 600;
      _cfgNaturalVB = { x: 0, y: 0, w, h };
      svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    }
    _cfgVB = { ..._cfgNaturalVB };

    // SVG fills the container — viewBox controls what we see (crisp at all zoom)
    svg.setAttribute('width',  '100%');
    svg.setAttribute('height', '100%');
    svg.style.width  = '100%';
    svg.style.height = '100%';
    svg.style.display = 'block';

    inner.appendChild(svg);
  } catch (e) {
    inner.innerHTML = `<p style="color:var(--red);padding:32px;text-align:center">Render error: ${escHtml(String(e))}</p>`;
  }
}

// Zoom: shrink/grow viewBox around a screen point (defaults to center)
function _cfgZoom(factor, screenX, screenY) {
  if (!_cfgVB || !_cfgNaturalVB) return;
  const container = document.getElementById('cfg-graph-container');
  const rect = container.getBoundingClientRect();

  // Anchor point in SVG coordinates
  const cx = screenX !== undefined ? screenX - rect.left : rect.width  / 2;
  const cy = screenY !== undefined ? screenY - rect.top  : rect.height / 2;
  const svgCX = _cfgVB.x + (cx / rect.width)  * _cfgVB.w;
  const svgCY = _cfgVB.y + (cy / rect.height) * _cfgVB.h;

  const newW = _cfgVB.w / factor;
  const newH = _cfgVB.h / factor;

  // Clamp: don't zoom beyond 20× in or 5× out from natural
  const minW = _cfgNaturalVB.w / 20;
  const maxW = _cfgNaturalVB.w * 5;
  if (newW < minW || newW > maxW) return;

  _cfgVB.x = svgCX - (cx / rect.width)  * newW;
  _cfgVB.y = svgCY - (cy / rect.height) * newH;
  _cfgVB.w = newW;
  _cfgVB.h = newH;
  _cfgApplyVB();
}

// Fit: reset viewBox to show the whole graph
function _cfgFit() {
  if (!_cfgNaturalVB) return;
  _cfgVB = { ..._cfgNaturalVB };
  _cfgApplyVB();
}

// Write _cfgVB back into the SVG's viewBox attribute
function _cfgApplyVB() {
  const svg = document.querySelector('#cfg-graph-inner svg');
  if (svg && _cfgVB) {
    svg.setAttribute('viewBox', `${_cfgVB.x} ${_cfgVB.y} ${_cfgVB.w} ${_cfgVB.h}`);
  }
}

function _cfgRenderBlocks(results) {
  const display = document.getElementById('cfg-display');
  display.innerHTML = '';

  results.forEach(r => {
    const funcTitle = document.createElement('div');
    funcTitle.className = 'section-title';
    funcTitle.textContent = `Function: ${r.function}()`;
    display.appendChild(funcTitle);

    const grid = document.createElement('div');
    grid.className = 'cfg-blocks-grid';

    r.blocks.forEach(b => {
      let cls = 'cfg-block-card';
      if (b.is_unreachable)  cls += ' unreachable';
      else if (b.is_entry)   cls += ' entry';
      else if (b.is_exit)    cls += ' exit';
      if (b.has_dead_code)   cls += ' dead-code';

      const badges = [];
      if (b.is_entry)       badges.push('<span class="block-badge entry">Entry</span>');
      if (b.is_exit)        badges.push('<span class="block-badge exit">Exit</span>');
      if (b.is_unreachable) badges.push('<span class="block-badge unreachable">Unreachable</span>');
      if (b.has_dead_code)  badges.push('<span class="block-badge dead-code">Dead Code</span>');

      const instrHTML = b.instructions.map(ins =>
        `<div class="cfg-instr${b.is_unreachable ? ' dead' : ''}">${escHtml(ins)}</div>`
      ).join('');

      const card = document.createElement('div');
      card.className = cls;
      card.innerHTML = `
        <div class="cfg-block-header">
          <span>${escHtml(b.label)}</span>
          <span style="display:flex;gap:4px">${badges.join('')}</span>
        </div>
        <div class="cfg-block-body">${instrHTML || '<i style="color:var(--text-muted);font-size:0.7rem">empty</i>'}</div>
        <div class="cfg-connections">
          <span>→ [${b.successors.map(s => 'B'+s).join(', ') || '—'}]</span>
          <span>← [${b.predecessors.map(p => 'B'+p).join(', ') || '—'}]</span>
        </div>`;
      grid.appendChild(card);
    });
    display.appendChild(grid);
  });
}

// ── Dead Code ─────────────────────────────────────────────────────────────────
function renderDeadCode(results) {
  document.getElementById('dead-empty').classList.add('hidden');
  const dc = document.getElementById('dead-content');
  dc.classList.remove('hidden');
  dc.innerHTML = '';

  results.forEach(r => {
    dc.innerHTML += `<div class="section-title">Function: ${escHtml(r.function)}()</div>`;

    const totalUnreach = r.unreachable_structural.length + r.unreachable_constant_folding.length;
    const totalDead    = r.dead_code.reduce((a,b)=>a+b.dead_instructions.length,0);

    if (r.is_dead_function) {
      dc.innerHTML += `
        <div class="alert-card unreachable-struct" style="border-color:#dc2626">
          <div class="alert-title" style="color:#fca5a5">☠ Dead Function — Never Called</div>
          <div class="alert-sub">
            <strong>${escHtml(r.function)}()</strong> is never called from any other function.
            The entire function body is dead — it can be safely removed.
          </div>
        </div>`;
    }

    if (totalUnreach === 0 && totalDead === 0 && !r.is_dead_function) {
      dc.innerHTML += `<div class="success-banner">
        <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
        No issues found in ${escHtml(r.function)}()
      </div>`;
      return;
    }
    if (totalUnreach === 0 && totalDead === 0) return;  // dead func banner already shown

    // Unreachable blocks section
    const allUnreach = [
      ...r.unreachable_structural.map(b=>({...b, type:'structural'})),
      ...r.unreachable_constant_folding.map(b=>({...b, type:'constant'}))
    ];

    if (allUnreach.length) {
      dc.innerHTML += `
        <h3 style="font-size:0.82rem;color:var(--red);margin-bottom:10px;font-weight:700">
          Unreachable Code Blocks (${allUnreach.length})
        </h3>`;
      allUnreach.forEach(b => {
        const typeLabel = b.type === 'structural'
          ? 'Structural — not reachable from entry'
          : 'Constant Folding — branch condition is always constant';
        dc.innerHTML += `
          <div class="alert-card ${b.type==='structural'?'unreachable-struct':'unreachable-const'}">
            <div class="alert-title">${b.label}</div>
            <div class="alert-sub">${typeLabel}</div>
            ${b.instructions.length
              ? `<ul class="instr-list">${b.instructions.map(i=>`<li>${escHtml(i)}</li>`).join('')}</ul>`
              : '<i style="color:var(--text-muted);font-size:0.7rem">No instructions</i>'}
          </div>`;
      });
    }

    // Dead code section
    if (totalDead) {
      dc.innerHTML += `
        <h3 style="font-size:0.82rem;color:var(--purple);margin:16px 0 10px;font-weight:700">
          Dead Assignments (${totalDead})
        </h3>`;
      r.dead_code.forEach(b => {
        dc.innerHTML += `
          <div class="alert-card dead">
            <div class="alert-title">Block: ${b.label} — ${b.dead_instructions.length} dead instruction(s)</div>
            <div class="alert-sub">Values computed but never consumed by any subsequent instruction</div>
            <table style="width:100%;font-size:0.72rem;border-collapse:collapse;margin-top:8px">
              <tr>
                <th style="text-align:left;color:var(--text-muted);padding:4px 8px;border-bottom:1px solid var(--border)">Instruction</th>
                <th style="text-align:left;color:var(--text-muted);padding:4px 8px;border-bottom:1px solid var(--border)">Defined Variable</th>
                <th style="text-align:left;color:var(--text-muted);padding:4px 8px;border-bottom:1px solid var(--border)">Status</th>
              </tr>
              ${b.dead_instructions.map(d=>`
                <tr>
                  <td style="padding:4px 8px;font-family:var(--font-mono);color:var(--text-code)">${escHtml(d.instruction)}</td>
                  <td style="padding:4px 8px;font-family:var(--font-mono);color:var(--orange)">${escHtml(d.defined_var||'—')}</td>
                  <td style="padding:4px 8px;color:var(--red)">✗ Dead</td>
                </tr>`).join('')}
            </table>
          </div>`;
      });
    }
  });
}

// ── Liveness ──────────────────────────────────────────────────────────────────
function renderLiveness(results) {
  document.getElementById('liveness-empty').classList.add('hidden');
  const lc = document.getElementById('liveness-content');
  lc.classList.remove('hidden');
  lc.innerHTML = '';

  // Legend
  lc.innerHTML = `
    <div class="cfg-legend" style="margin-bottom:20px">
      <span class="legend-item"><span class="var-chip live-in">x</span> Live-In</span>
      <span class="legend-item"><span class="var-chip live-out">x</span> Live-Out</span>
      <span class="legend-item"><span class="var-chip gen">x</span> GEN (used before def)</span>
      <span class="legend-item"><span class="var-chip kill">x</span> KILL (defined)</span>
    </div>`;

  results.forEach(r => {
    lc.innerHTML += `<div class="section-title">Function: ${r.function}()</div>`;
    const wrap = document.createElement('div');
    wrap.className = 'liveness-table-wrapper';

    const rows = r.blocks.map(b => {
      const fmtSet = (arr, cls) =>
        arr && arr.length
          ? arr.map(v=>`<span class="var-chip ${cls}">${escHtml(v)}</span>`).join('')
          : '<span class="var-chip empty">∅</span>';

      return `
        <tr>
          <td class="block-id">B${b.id}</td>
          <td>${escHtml(b.label)}</td>
          <td><div class="var-set">${fmtSet(b.live_in,'live-in')}</div></td>
          <td><div class="var-set">${fmtSet(b.live_out,'live-out')}</div></td>
        </tr>`;
    }).join('');

    wrap.innerHTML = `
      <table class="liveness-table">
        <thead>
          <tr>
            <th>Block</th>
            <th>Label</th>
            <th>Live-IN</th>
            <th>Live-OUT</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
    lc.appendChild(wrap);

    // Also show constant propagation results
    const hasConsts = r.blocks.some(b=>b.constants && Object.keys(b.constants).length>0);
    if (hasConsts) {
      const constTitle = document.createElement('div');
      constTitle.className = 'section-title';
      constTitle.textContent = 'Constant Propagation Results';
      constTitle.style.marginTop = '20px';
      lc.appendChild(constTitle);

      const constWrap = document.createElement('div');
      constWrap.className = 'liveness-table-wrapper';

      const constRows = r.blocks.filter(b => b.constants && Object.keys(b.constants).length > 0).map(b => {
        const pairs = Object.entries(b.constants).map(([k,v])=>
          `<span class="var-chip gen">${escHtml(k)} = ${escHtml(String(v))}</span>`
        ).join('');
        return `
          <tr>
            <td class="block-id">B${b.id}</td>
            <td>${escHtml(b.label)}</td>
            <td><div class="var-set">${pairs}</div></td>
          </tr>`;
      }).join('');

      constWrap.innerHTML = `
        <table class="liveness-table">
          <thead>
            <tr><th>Block</th><th>Label</th><th>Known Constants at Exit</th></tr>
          </thead>
          <tbody>${constRows}</tbody>
        </table>`;
      lc.appendChild(constWrap);
    }
  });
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
