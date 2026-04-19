'use strict';

// ─── Config ─────────────────────────────────────────────────────────────────
// Use the same origin as the page so it works from any host/port served by Flask
const API = window.location.origin;

// ─── State ──────────────────────────────────────────────────────────────────
let lastResults = null;

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

    // Visualize (CFG DOT)
    const vizRes = await fetch(`${API}/visualize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code, format: 'svg'})
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
        `<li class="${b.is_unreachable ? '' : 'dead-instr'}">${escHtml(d.instruction)}</li>`
      ).join('');
      ov.innerHTML += `
        <div class="alert-card dead">
          <div class="alert-title">✗ Dead Code in Block: ${escHtml(b.label)}</div>
          <div class="alert-sub">${b.dead_instructions.length} dead assignment(s) — values computed but never used</div>
          <ul class="instr-list">${deadList}</ul>
        </div>`;
    });
  });
}

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
  const cc = document.getElementById('cfg-content');
  cc.classList.remove('hidden');

  const display = document.getElementById('cfg-display');
  display.innerHTML = '';

  // If we got SVG from Graphviz, show it
  if (vizData && vizData.svg) {
    display.innerHTML = vizData.svg;
  } else {
    // Render block cards manually
    results.forEach(r => {
      const funcTitle = document.createElement('div');
      funcTitle.className = 'section-title';
      funcTitle.textContent = `Function: ${r.function}()`;
      display.appendChild(funcTitle);

      const grid = document.createElement('div');
      grid.className = 'cfg-blocks-grid';

      r.blocks.forEach(b => {
        let cls = 'cfg-block-card';
        if (b.is_unreachable) cls += ' unreachable';
        else if (b.is_entry) cls += ' entry';
        else if (b.is_exit) cls += ' exit';
        if (b.has_dead_code) cls += ' dead-code';

        const badges = [];
        if (b.is_entry)      badges.push('<span class="block-badge entry">Entry</span>');
        if (b.is_exit)       badges.push('<span class="block-badge exit">Exit</span>');
        if (b.is_unreachable) badges.push('<span class="block-badge unreachable">Unreachable</span>');
        if (b.has_dead_code)  badges.push('<span class="block-badge dead-code">Dead Code</span>');

        const instrHTML = b.instructions.map((ins, idx) => {
          const isDead = b.is_unreachable;
          return `<div class="cfg-instr${isDead?' dead':''}">${escHtml(ins)}</div>`;
        }).join('');

        const card = document.createElement('div');
        card.className = cls;
        card.innerHTML = `
          <div class="cfg-block-header">
            <span>${escHtml(b.label)}</span>
            <span style="display:flex;gap:4px">${badges.join('')}</span>
          </div>
          <div class="cfg-block-body">${instrHTML || '<i style="color:var(--text-muted);font-size:0.7rem">empty</i>'}</div>
          <div class="cfg-connections">
            <span>→ [${b.successors.map(s=>'B'+s).join(', ')||'—'}]</span>
            <span>← [${b.predecessors.map(p=>'B'+p).join(', ')||'—'}]</span>
          </div>`;
        grid.appendChild(card);
      });
      display.appendChild(grid);
    });
  }

  // Set DOT source
  if (vizData && vizData.dot) {
    document.getElementById('dot-pre').textContent = vizData.dot;
    document.getElementById('cfg-dot-source').classList.remove('hidden');
    btnShowDot.classList.remove('hidden');
    btnShowDot.textContent = 'Hide DOT Source';
  } else {
    // Request DOT separately
    const code = editor.value.trim();
    fetch(`${API}/visualize`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code, format: 'dot'})
    }).then(r=>r.json()).then(d => {
      if (d.dot) document.getElementById('dot-pre').textContent = d.dot;
    }).catch(()=>{});
  }
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
