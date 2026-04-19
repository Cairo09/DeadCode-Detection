"""
Dead/unreachable code elimination on analyzed CFGs.

Uses annotations populated by:
  - dead_code.detect()   -> bb.is_unreachable
  - liveness analysis    -> bb.dead_instrs
"""

from typing import Dict, Any, List, Tuple
from .cfg_builder import CFG
from .dead_code import _fmt_instr

Instruction = Tuple


def _can_remove_dead_instruction(instr: Instruction) -> bool:
    op = instr[0]
    # Keep: control-flow, call side-effects, array stores (conservative).
    return op not in ('label', 'goto', 'if_false', 'return', 'param', 'call', 'store')


def eliminate(cfg: CFG) -> Dict[str, Any]:
    """
    Build optimized TAC by removing:
      1) All instructions inside unreachable blocks.
      2) Dead instructions (whose defined variable is never used) in reachable blocks.

    Returns a dict with optimized TAC and elimination metrics.
    """
    optimized_instrs: List[Instruction] = []
    removed_unreachable_instrs = 0
    removed_dead_instrs        = 0
    removed_unreachable_blocks = 0
    original_instr_count       = 0

    for bid in sorted(cfg.blocks.keys()):
        bb = cfg.blocks[bid]
        original_instr_count += len(bb.instructions)

        if bb.is_unreachable:
            removed_unreachable_blocks += 1
            removed_unreachable_instrs += len(bb.instructions)
            continue

        dead_idx = set(bb.dead_instrs)
        for idx, instr in enumerate(bb.instructions):
            if idx in dead_idx and _can_remove_dead_instruction(instr):
                removed_dead_instrs += 1
                continue
            optimized_instrs.append(instr)

    optimized_tac         = [_fmt_instr(i) for i in optimized_instrs]
    optimized_instr_count = len(optimized_instrs)

    return {
        'optimized_instructions': optimized_instrs,
        'optimized_tac':          optimized_tac,
        'stats': {
            'original_instruction_count':      original_instr_count,
            'optimized_instruction_count':     optimized_instr_count,
            'removed_unreachable_blocks':      removed_unreachable_blocks,
            'removed_unreachable_instructions': removed_unreachable_instrs,
            'removed_dead_instructions':       removed_dead_instrs,
            'total_removed_instructions':      original_instr_count - optimized_instr_count,
        }
    }
