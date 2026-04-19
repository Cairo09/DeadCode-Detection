"""
Liveness Analysis — Backward dataflow analysis.

A variable is LIVE at a program point if its current value MAY be used
along some path from that point to the end of the program.

For each basic block B:
  GEN[B]  = variables used in B before any definition
  KILL[B] = variables defined in B
  OUT[B]  = union { IN[S] | S in successors(B) }
  IN[B]   = GEN[B] union (OUT[B] - KILL[B])

Array instructions — conservative approach:
  array_decl name, size  → DEFS {name}       (can be dead if array never loaded)
  load  tmp, name, idx   → USES {name, idx}, DEFS {tmp}
  store name, idx, value → USES {name, idx, value}, DEFS {}
    (stores are never flagged dead — we can't prove no-one reads that memory)
"""

from typing import Dict, Set
from .cfg_builder import CFG


def _uses(instr) -> Set[str]:
    """Variables used (read) by an instruction."""
    op, result, arg1, arg2 = instr
    used: Set[str] = set()

    if op in ('label', 'goto', 'call'):
        return used

    if op == 'return':
        if isinstance(result, str): used.add(result)
        return used

    if op == 'if_false':
        if isinstance(result, str): used.add(result)
        return used

    if op == 'param':
        if isinstance(result, str): used.add(result)
        return used

    if op == 'array_decl':
        # size argument — may be a variable
        if isinstance(arg1, str): used.add(arg1)
        return used

    if op == 'load':
        # ('load', tmp, array_name, index)
        if isinstance(arg1, str): used.add(arg1)  # array name
        if isinstance(arg2, str): used.add(arg2)  # index
        return used

    if op == 'store':
        # ('store', array_name, index, value)
        # Treat as using ALL THREE — conservative: store keeps array alive.
        if isinstance(result, str): used.add(result)  # array name
        if isinstance(arg1, str):   used.add(arg1)    # index
        if isinstance(arg2, str):   used.add(arg2)    # value
        return used

    # Binary / unary / copy instructions: result = f(arg1, arg2)
    if isinstance(arg1, str): used.add(arg1)
    if isinstance(arg2, str): used.add(arg2)
    return used


def _defs(instr) -> Set[str]:
    """Variables defined (written) by an instruction."""
    op, result, arg1, arg2 = instr

    if op in ('label', 'goto', 'if_false', 'return', 'param', 'store'):
        return set()

    if op == 'array_decl':
        if isinstance(result, str): return {result}
        return set()

    if op == 'load':
        if isinstance(result, str): return {result}
        return set()

    # Binary / unary / copy
    if isinstance(result, str) and not result.startswith('func_'):
        return {result}
    return set()


def _can_remove_as_dead(instr) -> bool:
    """True if this instruction can be safely removed when its result is dead."""
    op = instr[0]
    # Keep control-flow, call side-effects, and array stores (conservative).
    return op not in ('label', 'goto', 'if_false', 'return', 'param', 'call', 'store')


class LivenessAnalysis:

    def analyze(self, cfg: CFG) -> Dict[int, Dict[str, object]]:
        """
        Returns: block_id -> {gen, kill, in, out} sets.
        Also annotates BasicBlock objects with dead_instrs / has_dead_code.

        Uses an iterative outer loop so transitively dead instructions
        (e.g. a temp that only feeds another dead temp) are all found.
        """
        blocks = cfg.blocks
        dead_sets: Dict[int, Set[int]] = {bid: set() for bid in blocks}

        while True:
            # ── Compute GEN / KILL ignoring already-dead instructions ────────
            gen:  Dict[int, Set[str]] = {}
            kill: Dict[int, Set[str]] = {}

            for bid, bb in blocks.items():
                g: Set[str] = set()
                k: Set[str] = set()
                for idx, instr in enumerate(bb.instructions):
                    if idx in dead_sets[bid]:
                        continue
                    for u in _uses(instr):
                        if u not in k:
                            g.add(u)
                    k |= _defs(instr)
                gen[bid]  = g
                kill[bid] = k

            # ── Iterative dataflow: IN / OUT ─────────────────────────────────
            in_sets:  Dict[int, Set[str]] = {bid: set() for bid in blocks}
            out_sets: Dict[int, Set[str]] = {bid: set() for bid in blocks}

            changed = True
            while changed:
                changed = False
                for bid in reversed(list(blocks.keys())):
                    bb = blocks[bid]
                    new_out: Set[str] = set()
                    for succ_id in bb.successors:
                        new_out |= in_sets[succ_id]

                    new_in = gen[bid] | (new_out - kill[bid])
                    if new_in != in_sets[bid] or new_out != out_sets[bid]:
                        in_sets[bid]  = new_in
                        out_sets[bid] = new_out
                        changed = True

            # ── Find newly-dead instructions (scan each block backwards) ─────
            new_dead_sets: Dict[int, Set[int]] = {bid: set(dead_sets[bid]) for bid in blocks}

            for bid, bb in blocks.items():
                live: Set[str] = set(out_sets[bid])

                for rev_idx, instr in enumerate(reversed(bb.instructions)):
                    idx = len(bb.instructions) - 1 - rev_idx
                    if idx in dead_sets[bid]:
                        continue

                    defined = _defs(instr)
                    used    = _uses(instr)

                    if defined:
                        var = next(iter(defined))
                        if var not in live and _can_remove_as_dead(instr):
                            new_dead_sets[bid].add(idx)
                            continue  # don't propagate uses from this removed instr
                        live.discard(var)

                    live |= used

            if new_dead_sets == dead_sets:
                break
            dead_sets = new_dead_sets

        # ── Annotate blocks ──────────────────────────────────────────────────
        for bid, bb in blocks.items():
            dead = sorted(dead_sets[bid])
            bb.dead_instrs   = dead
            bb.has_dead_code = bool(dead)

        results: Dict[int, Dict] = {}
        for bid in blocks:
            results[bid] = {
                'gen':  list(gen[bid]),
                'kill': list(kill[bid]),
                'in':   list(in_sets[bid]),
                'out':  list(out_sets[bid]),
            }
        return results
