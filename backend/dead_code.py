"""
Dead Code & Unreachable Path Detection.
Combines CFG + Constant Propagation + Liveness Analysis to produce
a comprehensive analysis report.
"""

from typing import List, Dict, Any
from .cfg_builder import CFG, BasicBlock


def _fmt_instr(instr) -> str:
    """Format a TAC instruction tuple as a human-readable string."""
    op, result, arg1, arg2 = instr

    if op == 'label':
        return f"LABEL {result}:"
    if op == 'goto':
        return f"GOTO {result}"
    if op == 'if_false':
        return f"IF_FALSE {result} GOTO {arg1}"
    if op == 'return':
        val = result if result is not None else ''
        return f"RETURN {val}"
    if op == 'param':
        return f"PARAM {result}"
    if op == 'call':
        return f"{result} = CALL {arg1}({arg2} args)"
    if op == 'array_decl':
        return f"ARRAY {result}[{arg1}]"
    if op == 'load':
        idx = arg2 if isinstance(arg2, str) else str(arg2)
        return f"{result} = {arg1}[{idx}]"
    if op == 'store':
        idx = arg1 if isinstance(arg1, str) else str(arg1)
        val = arg2 if isinstance(arg2, str) else str(arg2)
        return f"{result}[{idx}] = {val}"
    if op == '=':
        return f"{result} = {arg1}"
    if op == 'unary-':
        return f"{result} = -{arg1}"
    if op == '!':
        return f"{result} = !{arg1}"
    if arg2 is not None:
        return f"{result} = {arg1} {op} {arg2}"
    return f"{result} = {op} {arg1}"


def detect(cfg: CFG, const_results: Dict, liveness_results: Dict) -> Dict[str, Any]:
    """
    Main detection function. Returns a structured report dict.
    """
    reachable = cfg.reachable_from_entry()
    unreachable_structural = []
    unreachable_constant   = []
    dead_code_items        = []
    summary_blocks         = []

    for bid, bb in cfg.blocks.items():
        is_struct_unreachable = bid not in reachable and not bb.is_entry

        # A block is constant-folding unreachable when it has no predecessors
        # (and isn't the entry) AFTER constant-propagation edge removal.
        is_const_unreachable = (
            not is_struct_unreachable
            and not bb.is_entry
            and len(bb.predecessors) == 0
        )

        if is_struct_unreachable or is_const_unreachable:
            bb.is_unreachable = True
            info = {
                'block_id': bid,
                'label':    bb.label or f"Block {bid}",
                'reason':   'structural' if is_struct_unreachable else 'constant_folding',
                'instructions': [_fmt_instr(i) for i in bb.instructions if i[0] != 'label'],
            }
            if is_struct_unreachable:
                unreachable_structural.append(info)
            else:
                unreachable_constant.append(info)

        # Dead instruction report for this block
        block_dead = []
        for idx in bb.dead_instrs:
            instr = bb.instructions[idx]
            defined_var = None
            if instr[0] not in ('label', 'goto', 'if_false', 'return', 'store'):
                defined_var = instr[1] if isinstance(instr[1], str) else None
            block_dead.append({
                'instr_index':  idx,
                'instruction':  _fmt_instr(instr),
                'defined_var':  defined_var,
            })

        if block_dead:
            dead_code_items.append({
                'block_id':         bid,
                'label':            bb.label or f"Block {bid}",
                'is_unreachable':   bb.is_unreachable,
                'dead_instructions': block_dead,
            })

        # Per-block summary
        const_env = const_results.get(bid, {})
        live_info = liveness_results.get(bid, {})

        summary_blocks.append({
            'id':           bid,
            'label':        bb.label or f"B{bid}",
            'is_entry':     bb.is_entry,
            'is_exit':      bb.is_exit,
            'is_unreachable': bb.is_unreachable,
            'has_dead_code':  bb.has_dead_code,
            'successors':   bb.successors,
            'predecessors': bb.predecessors,
            'instructions': [_fmt_instr(i) for i in bb.instructions],
            'constants':    {k: str(v) for k, v in const_env.items() if v not in ('TOP',)},
            'live_in':      live_info.get('in', []),
            'live_out':     live_info.get('out', []),
        })

    return {
        'function':                    cfg.func_name,
        'total_blocks':                len(cfg.blocks),
        'reachable_blocks':            len(reachable),
        'unreachable_structural':      unreachable_structural,
        'unreachable_constant_folding': unreachable_constant,
        'dead_code':                   dead_code_items,
        'blocks':                      summary_blocks,
    }
