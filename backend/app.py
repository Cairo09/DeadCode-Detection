"""
Flask REST API Server.

Endpoints:
  POST /analyze   — full pipeline analysis → JSON
  POST /visualize — returns DOT or SVG of annotated CFG
  GET  /health    — health check
  GET  /samples   — list sample programs
"""

import os
import sys
import subprocess
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.ir_generator import generate_ir
from backend.cfg_builder import build_cfg
from backend.constant_prop import ConstantPropagation
from backend.liveness import LivenessAnalysis
from backend.dead_code import detect, _fmt_instr
from backend.elimination import eliminate
from backend.visualizer import generate_dot_for_all

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend')
)
CORS(app)

# ─── Sample Programs ─────────────────────────────────────────────────────────

SAMPLES = {
    # ── Liveness & Dead Assignments ───────────────────────────────────────────
    "dead_assignment": {
        "title": "Dead Assignment (Classic)",
        "description": (
            "Three variables are assigned but only one reaches the return. "
            "Liveness analysis flags the assignments to 'x' and 'temp' as dead "
            "because their values are never consumed on any subsequent path."
        ),
        "code": """\
int main() {
    int x = 10;
    int y = 20;
    int temp = x * 3;
    int z = y + 5;
    return z;
}
"""
    },

    "multi_dead_chain": {
        "title": "Dead Assignment Chain",
        "description": (
            "A chain of assignments where only the last value is used. "
            "Each intermediate assignment to 'val' is dead because it is "
            "immediately overwritten before being read."
        ),
        "code": """\
int main() {
    int val = 1;
    val = 2;
    val = 3;
    val = 4;
    int result = val + 10;
    return result;
}
"""
    },

    "liveness_across_branches": {
        "title": "Liveness Across Branches",
        "description": (
            "Liveness analysis must track variable usage across both if/else branches. "
            "'dead_left' is only written in the true branch and never read afterwards, "
            "while 'score' is live because it is used after the if-else."
        ),
        "code": """\
int grade(int marks) {
    int score = marks * 2;
    int dead_left = 0;
    int bonus = 5;
    if (marks > 50) {
        dead_left = marks - 50;
        score += bonus;
    } else {
        score = score - 10;
    }
    return score;
}

int main() {
    int result = grade(60);
    return result;
}
"""
    },

    # ── Constant Propagation & Folding ────────────────────────────────────────
    "constant_branch_true": {
        "title": "Constant Branch — Always True",
        "description": (
            "Both 'a' and 'b' are compile-time constants (5 and 3). "
            "Constant propagation proves a > b is always True, so the else "
            "branch is never reachable. Its block is eliminated."
        ),
        "code": """\
int main() {
    int a = 5;
    int b = 3;
    int result = 0;
    if (a > b) {
        result = a + b;
    } else {
        result = a - b;
    }
    return result;
}
"""
    },

    "constant_branch_false": {
        "title": "Constant Branch — Always False",
        "description": (
            "The condition 'a == b' is always False because a=10, b=20 are "
            "known constants. Constant propagation prunes the true branch, "
            "leaving only the else block reachable."
        ),
        "code": """\
int main() {
    int a = 10;
    int b = 20;
    int result = 0;
    if (a == b) {
        result = 999;
    } else {
        result = a + b;
    }
    return result;
}
"""
    },

    "constant_folded_chain": {
        "title": "Constant Propagation Chain",
        "description": (
            "A sequence of assignments where every value is a compile-time constant. "
            "Constant propagation tracks all values through the chain and folds "
            "the final comparison to True, making the else branch unreachable."
        ),
        "code": """\
int main() {
    int base = 4;
    int step = 3;
    int total = base * step;
    int limit = 10;
    int result = 0;
    if (total > limit) {
        result = total - limit;
    } else {
        result = limit - total;
    }
    return result;
}
"""
    },

    "while_const_false": {
        "title": "While — Constant False Condition",
        "description": (
            "'flag' is set to 0 and never modified inside the loop body. "
            "Constant propagation determines while(flag) is always False, "
            "so the entire loop body is unreachable. 'unused' after the loop "
            "is also dead (never used in the return)."
        ),
        "code": """\
int main() {
    int flag = 0;
    int result = 0;
    while (flag) {
        result = result + 1;
        int dead = 42;
    }
    int unused = 99;
    return result;
}
"""
    },

    # ── Structurally Unreachable Code ─────────────────────────────────────────
    "after_return_simple": {
        "title": "Code After Return (Simple)",
        "description": (
            "Any statement after a 'return' in the same block is structurally "
            "unreachable — control flow cannot reach it. The CFG builder creates "
            "a new basic block for the dead statements, which has no predecessors."
        ),
        "code": """\
int compute(int x) {
    int a = x + 1;
    return a;
    int dead = 99;
    a = dead + 1;
    return a;
}

int main() {
    int result = compute(10);
    return result;
}
"""
    },

    "after_return_nested": {
        "title": "Code After Return (Nested Scopes)",
        "description": (
            "Dead code after return appears in both a helper function and inside "
            "a conditional branch in main. Each return creates a new unreachable "
            "block. The analyzer detects all of them independently."
        ),
        "code": """\
int clamp(int val) {
    if (val < 0) {
        return 0;
        int impossible = val * 2;
    }
    if (val > 100) {
        return 100;
        val = val - 100;
    }
    return val;
}

int main() {
    int x = clamp(150);
    int y = clamp(0) + x;
    return y;
}
"""
    },

    "break_unreachable": {
        "title": "Break Creates Unreachable Code",
        "description": (
            "'break' transfers control out of the loop immediately. Any statement "
            "written after 'break' in the same block is structurally unreachable. "
            "The CFG builder places these instructions in a new leader block with "
            "no incoming edges."
        ),
        "code": """\
int main() {
    int x = 0;
    int i = 0;
    while (i < 10) {
        if (i == 5) {
            x = i;
            break;
            x = 999;
            int phantom = x + 1;
        }
        i++;
    }
    return x;
}
"""
    },

    # ── Loops ─────────────────────────────────────────────────────────────────
    "for_loop_dead_var": {
        "title": "For Loop — Dead Variable Inside Body",
        "description": (
            "A for-loop with ++. Inside the loop body, 'scratch' is computed "
            "from 'i' but its value is never read again before the next iteration "
            "overwrites it. Liveness analysis correctly flags it as dead while "
            "keeping 'sum' (which is used after the loop) live."
        ),
        "code": """\
int main() {
    int sum = 0;
    int i = 0;
    for (i = 0; i < 10; i++) {
        int scratch = i * i;
        sum += i;
    }
    return sum;
}
"""
    },

    "for_loop_multi_dead": {
        "title": "For Loop — Multiple Dead Variables",
        "description": (
            "A for-loop accumulating a product. Three intermediate variables are "
            "computed inside the loop body — two of them ('debug' and 'offset') "
            "are never used, flagged dead. 'step' feeds into 'prod' and is live."
        ),
        "code": """\
int main() {
    int prod = 1;
    int i = 0;
    for (i = 1; i < 6; i++) {
        int step = i * 2;
        int debug = prod + 1000;
        int offset = i - 1;
        prod = prod * step;
    }
    return prod;
}
"""
    },

    "do_while_dead": {
        "title": "Do-While — Dead Variable in Body",
        "description": (
            "A do-while loop that accumulates into 'acc'. Inside the body, "
            "'waste' is computed each iteration but its value is never used. "
            "Liveness flags it dead in every iteration of the loop body block."
        ),
        "code": """\
int main() {
    int x = 1;
    int acc = 0;
    do {
        int waste = x * x * 3;
        acc += x;
        x++;
    } while (x < 6);
    return acc;
}
"""
    },

    "nested_loops": {
        "title": "Nested Loops — Dead Inner Variable",
        "description": (
            "A nested for-loop computing a matrix sum. The inner variable 'diag' "
            "is computed each inner iteration but never contributes to 'total'. "
            "Liveness analysis identifies it as dead across all inner-loop iterations."
        ),
        "code": """\
int main() {
    int total = 0;
    int i = 0;
    int j = 0;
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 4; j++) {
            int diag = i * j;
            total += i + j;
        }
    }
    return total;
}
"""
    },

    # ── Arrays ────────────────────────────────────────────────────────────────
    "arrays_dead_decl": {
        "title": "Arrays — Dead Declaration",
        "description": (
            "'dead_buf' is declared but no element is ever written or read. "
            "The liveness analysis sees 'array_decl dead_buf' define the name "
            "but no subsequent 'store' or 'load' uses it — so the declaration "
            "is flagged as dead. 'buf' is fully live."
        ),
        "code": """\
int main() {
    int buf[5];
    int dead_buf[10];
    buf[0] = 42;
    buf[1] = 99;
    int x = buf[0] + buf[1];
    return x;
}
"""
    },

    "arrays_dead_load": {
        "title": "Arrays — Dead Load Result",
        "description": (
            "An array element is read into 'tmp' but the value of 'tmp' is "
            "never used — the load result is dead. The array itself is live "
            "(it was written to), but the specific load instruction is flagged."
        ),
        "code": """\
int main() {
    int data[4];
    data[0] = 10;
    data[1] = 20;
    data[2] = 30;
    int tmp = data[1];
    int result = data[0] + data[2];
    return result;
}
"""
    },

    "arrays_loop_sum": {
        "title": "Arrays — Loop with Dead Intermediate",
        "description": (
            "A for-loop summing an array. 'normalized' is computed each "
            "iteration from 'data[i]' but never used. The array itself is "
            "fully live; only the intermediate calculation is dead."
        ),
        "code": """\
int main() {
    int data[5];
    data[0] = 3;
    data[1] = 7;
    data[2] = 2;
    data[3] = 9;
    data[4] = 1;
    int sum = 0;
    int i = 0;
    for (i = 0; i < 5; i++) {
        int normalized = data[i] * 10;
        sum += data[i];
    }
    return sum;
}
"""
    },

    # ── Functions & Dead Functions ─────────────────────────────────────────────
    "dead_function_simple": {
        "title": "Dead Function — Never Called",
        "description": (
            "'helper' is fully defined with logic but is never called by any "
            "other function. The dead function detector scans all 'call' "
            "instructions in the IR and finds no reference to 'helper', "
            "marking the entire function as dead."
        ),
        "code": """\
int helper(int x) {
    int result = x * 2;
    return result;
}

int main() {
    int val = 42;
    return val;
}
"""
    },

    "dead_function_multiple": {
        "title": "Dead Functions — Multiple Uncalled",
        "description": (
            "Three utility functions are defined: 'square', 'cube', and 'clamp'. "
            "Only 'square' is called from main. 'cube' and 'clamp' are never "
            "referenced in any call instruction, so both are flagged as dead functions."
        ),
        "code": """\
int square(int n) {
    return n * n;
}

int cube(int n) {
    int sq = n * n;
    return sq * n;
}

int clamp(int val) {
    if (val < 0) {
        return 0;
    }
    if (val > 100) {
        return 100;
    }
    return val;
}

int main() {
    int x = square(7);
    int y = x + 3;
    return y;
}
"""
    },

    "dead_function_chain": {
        "title": "Dead Function — Internal Dead Code Too",
        "description": (
            "'unused_fn' is never called (dead function). Inside it, 'temp' is "
            "also a dead variable. The called function 'process' has its own "
            "dead assignment 'overhead'. All three issues are detected independently."
        ),
        "code": """\
int unused_fn(int x) {
    int temp = x + 99;
    int result = x * 2;
    return result;
}

int process(int n) {
    int overhead = n * 0;
    int val = n + 10;
    return val;
}

int main() {
    int r = process(5);
    return r;
}
"""
    },

    # ── Char Type ─────────────────────────────────────────────────────────────
    "char_dead_var": {
        "title": "Char Type — Dead Char Variable",
        "description": (
            "Char variables are stored as their ASCII integer values. "
            "'dead_ch' is assigned the ASCII value of 'Z' (90) but is never "
            "read. Liveness analysis flags it dead just like any integer variable."
        ),
        "code": """\
int main() {
    char ch = 'A';
    char dead_ch = 'Z';
    int code = ch + 1;
    return code;
}
"""
    },

    "char_arithmetic": {
        "title": "Char Arithmetic & Dead Intermediates",
        "description": (
            "Char literals are folded to ASCII integers. 'upper' is computed "
            "from 'ch' but never used — dead. 'shift' is used in the final "
            "result. Constant propagation tracks the ASCII values through arithmetic."
        ),
        "code": """\
int main() {
    char ch = 'a';
    int upper = ch - 32;
    int shift = ch + 3;
    char sentinel = '\\0';
    int result = shift + sentinel;
    return result;
}
"""
    },

    # ── Complex / Mixed Scenarios ─────────────────────────────────────────────
    "complex_multi_function": {
        "title": "Complex — Multi-Function Mixed Analysis",
        "description": (
            "A realistic multi-function program combining: dead function detection "
            "('logger' is never called), constant-folded branch in 'compute' "
            "(a < b is always True since a=1, b=2), dead variable 'd' in 'compute', "
            "and a dead assignment 'unused' in 'main'."
        ),
        "code": """\
int logger(int code) {
    int stamp = code * 1000;
    return stamp;
}

int compute(int n) {
    int a = 1;
    int b = 2;
    int c = a + b;
    int d = 99;
    if (a < b) {
        c += n;
    } else {
        d = d + 1;
    }
    int e = c * 2;
    return e;
}

int main() {
    int val = compute(5);
    int unused = 777;
    return val;
}
"""
    },

    "complex_loop_branch_array": {
        "title": "Complex — Loop + Branch + Array",
        "description": (
            "Combines a for-loop, a conditional inside the loop, and array access. "
            "'dead_arr' is declared but never used (dead array). Inside the loop, "
            "'skip' is assigned in the else branch but never read. The constant "
            "branch 'i < 100' is always True for the loop range so else is dead."
        ),
        "code": """\
int main() {
    int scores[5];
    int dead_arr[3];
    scores[0] = 10;
    scores[1] = 85;
    scores[2] = 40;
    scores[3] = 90;
    scores[4] = 55;
    int total = 0;
    int i = 0;
    for (i = 0; i < 5; i++) {
        total += scores[i];
        int waste = i * i * i;
    }
    int average = total + 0;
    return total;
}
"""
    },

    "complex_nested_conditions": {
        "title": "Complex — Nested Conditionals with Dead Paths",
        "description": (
            "Deeply nested if-else where constant propagation eliminates an inner "
            "else branch. 'p=3, q=7' are constants; p < q is always True so the "
            "outer else is dead. Inside the true branch, 'junk' is computed but "
            "never used — caught by liveness."
        ),
        "code": """\
int evaluate(int x) {
    int p = 3;
    int q = 7;
    int result = 0;
    if (p < q) {
        int junk = p * q * 100;
        if (x > 0) {
            result = x + p;
        } else {
            result = q - x;
        }
    } else {
        result = 999;
    }
    return result;
}

int main() {
    int out = evaluate(5);
    int discard = out * 0;
    return out;
}
"""
    },

    "complex_early_exit_pattern": {
        "title": "Complex — Guard Clauses & Early Returns",
        "description": (
            "A function using guard-clause style returns. Each early return creates "
            "a new basic block; any code placed after them is structurally unreachable. "
            "Dead variables also appear before each guard."
        ),
        "code": """\
int safe_divide(int a, int b) {
    int debug_a = a * 1;
    if (b == 0) {
        int err_code = 1;
        return 0;
        int never = a + b;
    }
    int debug_b = b + 0;
    if (a == 0) {
        return 0;
        int also_never = 42;
    }
    int result = a / b;
    return result;
}

int main() {
    int x = safe_divide(10, 2);
    int y = safe_divide(5, 0);
    int total = x + y;
    return total;
}
"""
    },

    "complex_full": {
        "title": "Complex — Full Pipeline Showcase",
        "description": (
            "The ultimate showcase: dead functions, dead assignments, constant-folded "
            "unreachable branches, code after return, break-unreachable code, dead array "
            "declaration, dead loop variable, and dead char variable — all in one program."
        ),
        "code": """\
int unused_util(int x) {
    int a = x + 1;
    return a;
}

int compute_score(int base) {
    char grade = 'A';
    char dead_grade = 'F';
    int threshold = 50;
    int penalty = 10;
    int score = base;
    if (threshold > penalty) {
        score += base;
    } else {
        score = 0;
    }
    return score;
    int unreachable_cleanup = score * 2;
}

int main() {
    int lookup[4];
    int ghost[8];
    lookup[0] = 5;
    lookup[1] = 10;
    lookup[2] = 15;
    lookup[3] = 20;
    int i = 0;
    int total = 0;
    for (i = 0; i < 4; i++) {
        int temp = lookup[i] * 2;
        total += lookup[i];
    }
    int result = compute_score(total);
    int dead_var = result * 0;
    return result;
}
"""
    },
}

# ─── Dead Function Detection ──────────────────────────────────────────────────

def find_dead_functions(ir_prog) -> list:
    """
    Return the names of functions that are declared but never called
    from any other function.  'main' is treated as the implicit entry
    point and is never considered dead.
    """
    called = set()
    for func in ir_prog.functions:
        for instr in func.instructions:
            # ('call', result_tmp, func_name, n_args)
            if instr[0] == 'call':
                called.add(instr[2])

    dead = []
    for func in ir_prog.functions:
        if func.name != 'main' and func.name not in called:
            dead.append(func.name)
    return dead

# ─── Pipeline ────────────────────────────────────────────────────────────────

def run_pipeline(source: str):
    """
    Run the full analysis pipeline on the given source code.

    Returns: (cfgs, reports)
      cfgs    — list of CFG objects (one per function), after CP edge removal
      reports — list of analysis report dicts
    """
    ir_prog = generate_ir(source)
    cfgs    = build_cfg(ir_prog)

    dead_func_names = set(find_dead_functions(ir_prog))

    cp = ConstantPropagation()
    la = LivenessAnalysis()
    reports = []

    for cfg in cfgs:
        const_results = cp.analyze(cfg)     # modifies CFG edges in-place
        live_results  = la.analyze(cfg)     # annotates bb.dead_instrs
        report        = detect(cfg, const_results, live_results)
        elimination   = eliminate(cfg)

        ir_func = next(f for f in ir_prog.functions if f.name == cfg.func_name)
        report['tac']               = [_fmt_instr(i) for i in ir_func.instructions]
        report['optimized_tac']     = elimination['optimized_tac']
        report['elimination_stats'] = elimination['stats']
        report['is_dead_function']  = cfg.func_name in dead_func_names
        reports.append(report)

    return cfgs, reports

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/samples')
def samples():
    return jsonify(SAMPLES)


@app.route('/analyze', methods=['POST'])
def analyze():
    data   = request.get_json(force=True)
    source = data.get('code', '')
    if not source.strip():
        return jsonify({'error': 'Empty source code'}), 400
    try:
        _, reports = run_pipeline(source)
        return jsonify({'success': True, 'results': reports})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 422


@app.route('/visualize', methods=['POST'])
def visualize():
    data   = request.get_json(force=True)
    source = data.get('code', '')
    fmt    = data.get('format', 'dot')

    if not source.strip():
        return jsonify({'error': 'Empty source code'}), 400

    try:
        cfgs, _ = run_pipeline(source)
        dot_src  = generate_dot_for_all(cfgs)

        if fmt == 'svg':
            try:
                result = subprocess.run(
                    ['dot', '-Tsvg'],
                    input=dot_src.encode('utf-8'),
                    capture_output=True,
                    timeout=10
                )
                if result.returncode == 0:
                    svg = result.stdout.decode('utf-8')
                    return jsonify({'success': True, 'svg': svg, 'dot': dot_src})
                else:
                    return jsonify({
                        'success': True, 'svg': None, 'dot': dot_src,
                        'note': 'Graphviz returned an error; DOT source returned'
                    })
            except FileNotFoundError:
                return jsonify({
                    'success': True, 'svg': None, 'dot': dot_src,
                    'note': 'Graphviz (dot) not found in PATH; install it to get SVG graphs'
                })
            except subprocess.TimeoutExpired:
                return jsonify({
                    'success': True, 'svg': None, 'dot': dot_src,
                    'note': 'Graphviz timed out; DOT source returned'
                })

        return jsonify({'success': True, 'dot': dot_src})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 422


@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_frontend(path):
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    return send_from_directory(frontend_dir, path)


if __name__ == '__main__':
    app.run(debug=True, port=5050)
