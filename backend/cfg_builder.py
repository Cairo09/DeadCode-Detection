"""
CFG Builder — Partitions TAC instructions into Basic Blocks and builds
the Control Flow Graph (directed graph of basic blocks with edges).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from .ir_generator import Instruction, IRFunction, IRProgram


@dataclass
class BasicBlock:
    id: int
    label: Optional[str]          # entry label of this block (if any)
    instructions: List[Instruction] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)   # block IDs
    predecessors: List[int] = field(default_factory=list)

    # Analysis annotations (filled later)
    is_entry: bool = False
    is_exit: bool = False
    is_unreachable: bool = False    # structural unreachability
    has_dead_code: bool = False
    dead_instrs: List[int] = field(default_factory=list)  # instruction indices


@dataclass
class CFG:
    func_name: str
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)
    entry_id: int = 0
    label_to_block: Dict[str, int] = field(default_factory=dict)

    def add_edge(self, src: int, dst: int):
        if dst not in self.blocks[src].successors:
            self.blocks[src].successors.append(dst)
        if src not in self.blocks[dst].predecessors:
            self.blocks[dst].predecessors.append(src)

    def reachable_from_entry(self) -> Set[int]:
        """BFS/DFS from entry to find structurally reachable blocks."""
        visited = set()
        stack = [self.entry_id]
        while stack:
            bid = stack.pop()
            if bid in visited:
                continue
            visited.add(bid)
            for succ in self.blocks[bid].successors:
                if succ not in visited:
                    stack.append(succ)
        return visited


class CFGBuilder:

    def build(self, ir_func: IRFunction) -> CFG:
        cfg = CFG(func_name=ir_func.name)
        instrs = ir_func.instructions

        # ── Step 1: Find leaders (start of basic blocks) ──────────────────
        leaders: Set[int] = {0}
        label_positions: Dict[str, int] = {}

        for i, instr in enumerate(instrs):
            op = instr[0]
            if op == 'label':
                leaders.add(i)
                label_positions[instr[1]] = i
            elif op in ('goto', 'if_false', 'return'):
                if i + 1 < len(instrs):
                    leaders.add(i + 1)

        sorted_leaders = sorted(leaders)

        # ── Step 2: Create basic blocks ───────────────────────────────────
        for idx, leader in enumerate(sorted_leaders):
            end = sorted_leaders[idx + 1] if idx + 1 < len(sorted_leaders) else len(instrs)
            block_instrs = instrs[leader:end]
            block_label = block_instrs[0][1] if block_instrs and block_instrs[0][0] == 'label' else None

            bb = BasicBlock(id=idx, label=block_label, instructions=block_instrs)
            cfg.blocks[idx] = bb
            if block_label:
                cfg.label_to_block[block_label] = idx

        # Mark entry
        cfg.entry_id = 0
        cfg.blocks[0].is_entry = True

        # ── Step 3: Add edges ─────────────────────────────────────────────
        for idx, (leader, bb) in enumerate(zip(sorted_leaders, cfg.blocks.values())):
            if not bb.instructions:
                continue
            last = bb.instructions[-1]
            op = last[0]

            if op == 'goto':
                target_label = last[1]
                if target_label in cfg.label_to_block:
                    cfg.add_edge(idx, cfg.label_to_block[target_label])

            elif op == 'if_false':
                # True branch: fall through (next block)
                # False branch: jump to label
                false_label = last[2]
                if idx + 1 < len(cfg.blocks):
                    cfg.add_edge(idx, idx + 1)   # fall-through (true branch)
                if false_label in cfg.label_to_block:
                    cfg.add_edge(idx, cfg.label_to_block[false_label])

            elif op == 'return':
                bb.is_exit = True
                # No successors — exit block

            else:
                # Fall through to next block
                if idx + 1 < len(cfg.blocks):
                    cfg.add_edge(idx, idx + 1)

        # Mark any block with no successors (and not return) as exit too
        for bb in cfg.blocks.values():
            if not bb.successors and not bb.is_exit:
                bb.is_exit = True

        return cfg


def build_cfg(ir_prog: IRProgram) -> List[CFG]:
    builder = CFGBuilder()
    return [builder.build(f) for f in ir_prog.functions]
