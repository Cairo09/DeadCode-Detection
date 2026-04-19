"""
Constant Propagation — Forward dataflow analysis.

Each block maintains a mapping: variable -> constant value | TOP | BOTTOM
  TOP     = unknown (before any info reaches here)
  BOTTOM  = not a constant (conflicting values from different paths)

Algorithm: two-phase Kildall worklist.

  Phase 1 — run worklist to full convergence WITHOUT any edge pruning.
             Using intermediate (unconverged) values to prune edges is
             UNSOUND for loops: e.g. the do-while condition looks True on
             the first pass but becomes non-constant once the back-edge
             is factored in, so we must not commit to pruning until the
             fixed point is reached.

  Phase 2 — once out-states are stable, inspect every if_false block.
             If its condition is still a compile-time constant in the
             converged state, prune the infeasible branch edge.

  Limitation: a while-loop whose condition variable IS modified inside
  the body will converge to BOTTOM (because the back-edge contributes a
  different value), so constant-folding unreachability won't be reported
  for that pattern.  Use variables that the loop body does NOT modify for
  reliable detection (e.g. a constant flag set before the loop).
"""

from typing import Dict, List, Set, Any
from .cfg_builder import CFG

# ── Lattice sentinels ────────────────────────────────────────────────────────
_TOP    = object()   # above everything — no information yet
_BOTTOM = object()   # below everything — not a constant (NAC)

BINARY_OPS = frozenset(('+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', '&&', '||'))


def _is_const(val) -> bool:
    return val is not _TOP and val is not _BOTTOM


def _meet(a, b):
    if a is _TOP: return b
    if b is _TOP: return a
    if a is _BOTTOM or b is _BOTTOM: return _BOTTOM
    if type(a) == type(b) and a == b: return a
    return _BOTTOM


def _eval_binop(op: str, a, b):
    if not (_is_const(a) and _is_const(b)): return _BOTTOM
    if not (isinstance(a, (int, bool)) and isinstance(b, (int, bool))): return _BOTTOM
    try:
        if op == '+':  return a + b
        if op == '-':  return a - b
        if op == '*':  return a * b
        if op == '/':  return a // b if b != 0 else _BOTTOM
        if op == '%':  return a % b  if b != 0 else _BOTTOM
        if op == '==': return a == b
        if op == '!=': return a != b
        if op == '<':  return a < b
        if op == '<=': return a <= b
        if op == '>':  return a > b
        if op == '>=': return a >= b
        if op == '&&': return bool(a) and bool(b)
        if op == '||': return bool(a) or  bool(b)
    except Exception:
        pass
    return _BOTTOM


def _eval_unary(op: str, a):
    if not _is_const(a) or not isinstance(a, (int, bool)): return _BOTTOM
    if op == '!':      return not a
    if op == 'unary-': return -a
    return _BOTTOM


def _lookup(env: dict, name) -> Any:
    if name is None:           return _BOTTOM
    if isinstance(name, bool): return name
    if isinstance(name, int):  return name
    if isinstance(name, str):  return env.get(name, _TOP)
    return _BOTTOM


def _rebuild_predecessors(cfg: CFG):
    for bb in cfg.blocks.values():
        bb.predecessors = []
    for src, bb in cfg.blocks.items():
        for dst in bb.successors:
            if src not in cfg.blocks[dst].predecessors:
                cfg.blocks[dst].predecessors.append(src)


def _prune_edges_from_unreachable_blocks(cfg: CFG):
    """Remove edges out of structurally unreachable blocks, then rebuild preds."""
    reachable = cfg.reachable_from_entry()
    for bid, bb in cfg.blocks.items():
        if bid in reachable or bb.is_entry:
            continue
        bb.successors = []
    _rebuild_predecessors(cfg)


def _transfer(bb, in_env: dict) -> dict:
    """Compute the out-environment for bb given in_env (no side effects)."""
    env = dict(in_env)
    for instr in bb.instructions:
        op, result, arg1, arg2 = instr

        if op in ('label', 'return', 'goto', 'if_false', 'param'):
            continue

        elif op == 'call':
            if isinstance(result, str): env[result] = _BOTTOM

        elif op == 'array_decl':
            if isinstance(result, str): env[result] = _TOP

        elif op == 'store':
            if isinstance(result, str): env[result] = _BOTTOM

        elif op == 'load':
            if isinstance(result, str): env[result] = _BOTTOM

        elif op == '=':
            if isinstance(result, str): env[result] = _lookup(env, arg1)

        elif op in BINARY_OPS and arg2 is not None:
            v1 = _lookup(env, arg1)
            v2 = _lookup(env, arg2)
            if isinstance(result, str):
                env[result] = _eval_binop(op, v1, v2) if (_is_const(v1) and _is_const(v2)) else _BOTTOM

        elif op == 'unary-':
            v1 = _lookup(env, arg1)
            if isinstance(result, str):
                env[result] = _eval_unary('unary-', v1) if _is_const(v1) else _BOTTOM

        elif op == '!':
            v1 = _lookup(env, arg1)
            if isinstance(result, str):
                env[result] = _eval_unary('!', v1) if _is_const(v1) else _BOTTOM

        elif op in BINARY_OPS and arg2 is None:
            if isinstance(result, str): env[result] = _BOTTOM

    return env


class ConstantPropagation:

    def analyze(self, cfg: CFG) -> Dict[int, Dict[str, Any]]:
        """
        SCCP-style reachability-aware worklist algorithm.

        Phase 1: propagate values AND reachability together.
                 For an if_false whose condition is a known constant,
                 only the taken branch is added to the executable set —
                 the other branch never receives values, so its back-edge
                 cannot poison the analysis.  This correctly detects loop
                 bodies that are unreachable from the very first iteration
                 (e.g. while(i < 10) with i=15).

        Phase 2: prune infeasible CFG edges using the converged out-states.
        """
        in_state:   Dict[int, dict] = {bid: {} for bid in cfg.blocks}
        out_state:  Dict[int, dict] = {bid: {} for bid in cfg.blocks}
        executable: Set[int]        = {cfg.entry_id}

        worklist:    List[int] = [cfg.entry_id]
        in_worklist: Set[int]  = {cfg.entry_id}

        # ── Phase 1: reachability-aware convergence ──────────────────────────
        while worklist:
            bid = worklist.pop(0)
            in_worklist.discard(bid)

            if bid not in executable:
                continue

            bb = cfg.blocks[bid]

            # Meet only over executable predecessors so that unreachable
            # back-edges don't contribute conflicting values.
            merged: dict = {}
            if not bb.is_entry:
                for pred_id in bb.predecessors:
                    if pred_id not in executable:
                        continue
                    for var, val in out_state[pred_id].items():
                        merged[var] = _meet(merged.get(var, _TOP), val)
            in_state[bid] = merged

            env = _transfer(bb, merged)
            if env == out_state[bid]:
                continue
            out_state[bid] = env

            # Decide which successors become reachable
            last = bb.instructions[-1] if bb.instructions else None
            if last is not None and last[0] == 'if_false':
                cond_var    = last[1]
                false_label = last[2]
                cond_val    = _lookup(env, cond_var)
                false_bid   = cfg.label_to_block.get(false_label)
                true_bid    = next((s for s in bb.successors if s != false_bid), None)

                if _is_const(cond_val):
                    # Only the taken branch becomes reachable
                    reachable_succs = []
                    if cond_val and true_bid is not None:
                        reachable_succs = [true_bid]
                    elif not cond_val and false_bid is not None:
                        reachable_succs = [false_bid]
                else:
                    reachable_succs = list(bb.successors)
            else:
                reachable_succs = list(bb.successors)

            for succ_id in reachable_succs:
                executable.add(succ_id)
                if succ_id not in in_worklist:
                    worklist.append(succ_id)
                    in_worklist.add(succ_id)

        # ── Phase 2: prune infeasible edges using converged out-states ───────
        for bid, bb in cfg.blocks.items():
            if not bb.instructions:
                continue
            last = bb.instructions[-1]
            if last[0] != 'if_false':
                continue

            cond_var    = last[1]
            false_label = last[2]
            cond_val    = _lookup(out_state[bid], cond_var)

            if not _is_const(cond_val):
                continue

            false_bid = cfg.label_to_block.get(false_label)

            if cond_val:
                # Always true → false branch infeasible
                if false_bid is not None and false_bid in bb.successors:
                    bb.successors.remove(false_bid)
                    cfg.blocks[false_bid].predecessors = [
                        p for p in cfg.blocks[false_bid].predecessors if p != bid
                    ]
            else:
                # Always false → true (fall-through) branch infeasible
                true_bid = next((s for s in bb.successors if s != false_bid), None)
                if true_bid is not None:
                    bb.successors.remove(true_bid)
                    cfg.blocks[true_bid].predecessors = [
                        p for p in cfg.blocks[true_bid].predecessors if p != bid
                    ]

        # Always clean up stale predecessor entries from unreachable blocks.
        _prune_edges_from_unreachable_blocks(cfg)

        # ── Serialize ────────────────────────────────────────────────────────
        serialized: Dict[int, Dict[str, Any]] = {}
        for bid, env in out_state.items():
            serialized[bid] = {}
            for var, val in env.items():
                if val is _TOP:
                    serialized[bid][var] = 'TOP'
                elif val is _BOTTOM:
                    serialized[bid][var] = 'NAC'
                else:
                    serialized[bid][var] = val
        return serialized
