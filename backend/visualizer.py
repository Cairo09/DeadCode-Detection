"""
CFG Visualizer — Converts CFG to Graphviz DOT format.
Color coding:
  - Entry block: #00c853 (green)
  - Exit block:  #1565c0 (blue)
  - Unreachable: #c62828 (red)
  - Dead code:   #e65100 (orange)
  - Normal:      #1a237e (dark blue)
"""

from typing import List
from .cfg_builder import CFG
from .dead_code import _fmt_instr


def _escape_dot(text: str) -> str:
    """Escape a string for safe inclusion in a Graphviz DOT label."""
    text = text.replace('\\', '\\\\')
    text = text.replace('"',  '\\"')
    text = text.replace('{',  '\\{')
    text = text.replace('}',  '\\}')
    text = text.replace('<',  '\\<')
    text = text.replace('>',  '\\>')
    text = text.replace('|',  '\\|')
    return text


def cfg_to_dot(cfg: CFG, prefix: str = '') -> str:
    """Generate a Graphviz DOT string for a single CFG.

    prefix — prepended to every node ID so that multiple functions
             combined into one digraph don't share node names.
    """
    lines = [
        f'digraph "{cfg.func_name}" {{',
        '  graph [rankdir=TB, bgcolor="#0d1117", fontname="Courier New", pad="0.5"];',
        '  node [shape=box, style="filled,rounded", fontname="Courier New", fontsize=10, margin="0.2,0.1"];',
        '  edge [color="#78909c", fontcolor="#78909c", fontsize=9, fontname="Courier New"];',
    ]

    def nid(bid):
        return f'{prefix}B{bid}'

    for bid, bb in cfg.blocks.items():
        if bb.is_unreachable:
            fill, border, font = '#7f1d1d', '#ef4444', '#fecaca'
        elif bb.is_entry:
            fill, border, font = '#14532d', '#22c55e', '#bbf7d0'
        elif bb.is_exit:
            fill, border, font = '#1e3a5f', '#3b82f6', '#bfdbfe'
        elif bb.has_dead_code:
            fill, border, font = '#7c2d12', '#f97316', '#fed7aa'
        else:
            fill, border, font = '#1e293b', '#475569', '#e2e8f0'

        header = bb.label or f"Block {bid}"
        if bb.is_entry:       header += "  [ENTRY]"
        if bb.is_exit:        header += "  [EXIT]"
        if bb.is_unreachable: header += "  [UNREACHABLE]"

        instr_lines = []
        for i, instr in enumerate(bb.instructions):
            txt = _fmt_instr(instr)
            if i in bb.dead_instrs:
                txt = f"[DEAD] {txt}"
            instr_lines.append(_escape_dot(txt))

        body  = "\\l".join(instr_lines) + "\\l" if instr_lines else ""
        sep   = _escape_dot("─" * 28)
        label = f"{_escape_dot(header)}\\n{sep}\\l{body}"

        lines.append(
            f'  {nid(bid)} [label="{label}", '
            f'fillcolor="{fill}", color="{border}", fontcolor="{font}"];'
        )

    for bid, bb in cfg.blocks.items():
        for succ in bb.successors:
            if bb.instructions:
                last = bb.instructions[-1]
                if last[0] == 'if_false':
                    false_label = last[2]
                    target_bid  = cfg.label_to_block.get(false_label)
                    if succ == target_bid:
                        lines.append(f'  {nid(bid)} -> {nid(succ)} [label="false", color="#ef4444"];')
                    else:
                        lines.append(f'  {nid(bid)} -> {nid(succ)} [label="true",  color="#22c55e"];')
                    continue
            lines.append(f'  {nid(bid)} -> {nid(succ)};')

    lines.append("}")
    return "\n".join(lines)


def generate_dot_for_all(cfgs: List[CFG]) -> str:
    """Combine multiple CFGs into one DOT digraph using cluster subgraphs.

    Each function gets a unique node-ID prefix (f0_, f1_, …) so that
    blocks with the same numeric ID in different functions do not collide.
    """
    parts = []
    for i, cfg in enumerate(cfgs):
        prefix = f'f{i}_'
        dot    = cfg_to_dot(cfg, prefix=prefix)
        inner  = "\n".join(dot.split("\n")[1:-1])   # strip outer digraph { }
        parts.append(
            f'  subgraph cluster_{i} {{\n'
            f'    label="{cfg.func_name}()";\n'
            f'    fontcolor="white"; fontsize=14; color="#334155"; style=dashed;\n'
            f'{inner}\n'
            f'  }}'
        )
    return (
        'digraph Program {\n'
        '  graph [rankdir=TB, bgcolor="#0d1117", fontname="Courier New", pad="1"];\n'
        '  node [shape=box, style="filled,rounded", fontname="Courier New", fontsize=10];\n'
        '  edge [color="#78909c"];\n'
        + "\n".join(parts) +
        "\n}"
    )
