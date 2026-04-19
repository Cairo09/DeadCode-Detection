"""
IR Generator — Translates AST to Three-Address Code (TAC).

TAC instruction forms:
  (op, result, arg1, arg2)     — binary op:      result = arg1 op arg2
  (op, result, arg1, None)     — unary / copy:   result = op arg1
  ('label',      name,  None, None)
  ('goto',       label, None, None)
  ('if_false',   cond,  label, None)  — jump if cond is false
  ('param',      arg,   None, None)
  ('call',       result, func, n_args)
  ('return',     value,  None, None)
  ('array_decl', name,   size, None)  — declare array of given size
  ('load',       result, name, index) — result = name[index]
  ('store',      name,   index, value)— name[index] = value
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from .parser import (
    Program, FuncDecl, Block, DeclStmt, ArrayDeclStmt,
    AssignStmt, ArrayAssignStmt, CompoundAssign, IncrStmt, DecrStmt, ExprStmt,
    IfStmt, WhileStmt, ForStmt, DoWhileStmt, BreakStmt, ContinueStmt, ReturnStmt,
    BinOp, UnaryOp, Literal, Var, FuncCall, ArrayAccess, ASTNode
)

Instruction = Tuple


@dataclass
class IRFunction:
    name: str
    params: List[str]
    instructions: List[Instruction] = field(default_factory=list)


@dataclass
class IRProgram:
    functions: List[IRFunction] = field(default_factory=list)


class IRGenerator:
    def __init__(self):
        self._tmp_count = 0
        self._label_count = 0
        self._instrs: List[Instruction] = []
        # Stack of (continue_label, break_label) for enclosing loops.
        self._loop_stack: List[Tuple[str, str]] = []

    def _new_tmp(self) -> str:
        self._tmp_count += 1
        return f"_t{self._tmp_count}"

    def _new_label(self, prefix="L") -> str:
        self._label_count += 1
        return f"{prefix}{self._label_count}"

    def _emit(self, *args):
        self._instrs.append(tuple(args))

    # ─── Public API ─────────────────────────────────────────────────────────

    def generate(self, program: Program) -> IRProgram:
        ir = IRProgram()
        for func in program.functions:
            ir.functions.append(self._gen_func(func))
        return ir

    def _gen_func(self, func: FuncDecl) -> IRFunction:
        self._instrs = []
        self._loop_stack = []
        self._emit('label', f"func_{func.name}", None, None)
        self._gen_block(func.body)
        return IRFunction(
            name=func.name,
            params=[p.name for p in func.params],
            instructions=list(self._instrs)
        )

    # ─── Statements ─────────────────────────────────────────────────────────

    def _gen_block(self, block: Block):
        for stmt in block.stmts:
            self._gen_stmt(stmt)

    def _gen_stmt(self, stmt: ASTNode):
        if isinstance(stmt, Block):            self._gen_block(stmt)
        elif isinstance(stmt, DeclStmt):       self._gen_decl(stmt)
        elif isinstance(stmt, ArrayDeclStmt):  self._gen_array_decl(stmt)
        elif isinstance(stmt, AssignStmt):     self._gen_assign(stmt)
        elif isinstance(stmt, ArrayAssignStmt):self._gen_array_assign(stmt)
        elif isinstance(stmt, CompoundAssign): self._gen_compound_assign(stmt)
        elif isinstance(stmt, IncrStmt):       self._gen_incr(stmt)
        elif isinstance(stmt, DecrStmt):       self._gen_decr(stmt)
        elif isinstance(stmt, ExprStmt):       self._gen_expr(stmt.expr)  # discard result
        elif isinstance(stmt, IfStmt):         self._gen_if(stmt)
        elif isinstance(stmt, WhileStmt):      self._gen_while(stmt)
        elif isinstance(stmt, ForStmt):        self._gen_for(stmt)
        elif isinstance(stmt, DoWhileStmt):    self._gen_do_while(stmt)
        elif isinstance(stmt, BreakStmt):      self._gen_break(stmt)
        elif isinstance(stmt, ContinueStmt):   self._gen_continue(stmt)
        elif isinstance(stmt, ReturnStmt):     self._gen_return(stmt)

    def _gen_decl(self, stmt: DeclStmt):
        if stmt.init is not None:
            val = self._gen_expr(stmt.init)
            self._emit('=', stmt.name, val, None)

    def _gen_array_decl(self, stmt: ArrayDeclStmt):
        size_val = self._gen_expr(stmt.size)
        self._emit('array_decl', stmt.name, size_val, None)

    def _gen_assign(self, stmt: AssignStmt):
        val = self._gen_expr(stmt.expr)
        self._emit('=', stmt.name, val, None)

    def _gen_array_assign(self, stmt: ArrayAssignStmt):
        idx = self._gen_expr(stmt.index)
        val = self._gen_expr(stmt.expr)
        self._emit('store', stmt.name, idx, val)

    def _gen_compound_assign(self, stmt: CompoundAssign):
        # x += expr  →  _t = x op expr; x = _t
        op_map = {'+=': '+', '-=': '-', '*=': '*', '/=': '/', '%=': '%'}
        rhs = self._gen_expr(stmt.expr)
        tmp = self._new_tmp()
        self._emit(op_map[stmt.op], tmp, stmt.name, rhs)
        self._emit('=', stmt.name, tmp, None)

    def _gen_incr(self, stmt: IncrStmt):
        # i++  or  ++i  as a statement — return value is discarded
        tmp = self._new_tmp()
        self._emit('+', tmp, stmt.name, 1)
        self._emit('=', stmt.name, tmp, None)

    def _gen_decr(self, stmt: DecrStmt):
        tmp = self._new_tmp()
        self._emit('-', tmp, stmt.name, 1)
        self._emit('=', stmt.name, tmp, None)

    def _gen_if(self, stmt: IfStmt):
        cond = self._gen_expr(stmt.cond)
        else_label = self._new_label("else")
        end_label  = self._new_label("endif")

        self._emit('if_false', cond, else_label, None)
        self._gen_stmt(stmt.then_)
        self._emit('goto', end_label, None, None)
        self._emit('label', else_label, None, None)
        if stmt.else_:
            self._gen_stmt(stmt.else_)
        self._emit('label', end_label, None, None)

    def _gen_while(self, stmt: WhileStmt):
        cond_label = self._new_label("while_cond")
        end_label  = self._new_label("while_end")

        self._loop_stack.append((cond_label, end_label))

        self._emit('label', cond_label, None, None)
        cond = self._gen_expr(stmt.cond)
        self._emit('if_false', cond, end_label, None)
        self._gen_stmt(stmt.body)
        self._emit('goto', cond_label, None, None)
        self._emit('label', end_label, None, None)

        self._loop_stack.pop()

    def _gen_for(self, stmt: ForStmt):
        cond_label   = self._new_label("for_cond")
        update_label = self._new_label("for_upd")
        end_label    = self._new_label("for_end")

        # continue → update_label, break → end_label
        self._loop_stack.append((update_label, end_label))

        # Init
        if stmt.init is not None:
            self._gen_stmt(stmt.init)

        # Condition
        self._emit('label', cond_label, None, None)
        if stmt.cond is not None:
            cond = self._gen_expr(stmt.cond)
            self._emit('if_false', cond, end_label, None)
        # else: no condition → infinite loop (until break/return)

        # Body
        self._gen_stmt(stmt.body)

        # Update label (target for 'continue')
        self._emit('label', update_label, None, None)
        if stmt.update is not None:
            self._gen_stmt(stmt.update)

        self._emit('goto', cond_label, None, None)
        self._emit('label', end_label, None, None)

        self._loop_stack.pop()

    def _gen_do_while(self, stmt: DoWhileStmt):
        body_label = self._new_label("do_body")
        cond_label = self._new_label("do_cond")
        end_label  = self._new_label("do_end")

        # continue → cond_label, break → end_label
        self._loop_stack.append((cond_label, end_label))

        self._emit('label', body_label, None, None)
        self._gen_stmt(stmt.body)

        self._emit('label', cond_label, None, None)
        cond = self._gen_expr(stmt.cond)
        self._emit('if_false', cond, end_label, None)
        self._emit('goto', body_label, None, None)
        self._emit('label', end_label, None, None)

        self._loop_stack.pop()

    def _gen_break(self, stmt: BreakStmt):
        if not self._loop_stack:
            raise ValueError(f"'break' used outside of a loop (line {stmt.line})")
        _, end_label = self._loop_stack[-1]
        self._emit('goto', end_label, None, None)

    def _gen_continue(self, stmt: ContinueStmt):
        if not self._loop_stack:
            raise ValueError(f"'continue' used outside of a loop (line {stmt.line})")
        cont_label, _ = self._loop_stack[-1]
        self._emit('goto', cont_label, None, None)

    def _gen_return(self, stmt: ReturnStmt):
        val = self._gen_expr(stmt.expr) if stmt.expr else None
        self._emit('return', val, None, None)

    # ─── Expressions ────────────────────────────────────────────────────────

    def _gen_expr(self, node: ASTNode):
        if isinstance(node, Literal):
            return node.value  # int, bool, or char (already an int)

        if isinstance(node, Var):
            return node.name

        if isinstance(node, ArrayAccess):
            idx = self._gen_expr(node.index)
            tmp = self._new_tmp()
            self._emit('load', tmp, node.name, idx)
            return tmp

        if isinstance(node, UnaryOp):
            operand = self._gen_expr(node.operand)
            tmp = self._new_tmp()
            op = 'unary-' if node.op == '-' else node.op
            self._emit(op, tmp, operand, None)
            return tmp

        if isinstance(node, BinOp):
            left  = self._gen_expr(node.left)
            right = self._gen_expr(node.right)
            tmp   = self._new_tmp()
            self._emit(node.op, tmp, left, right)
            return tmp

        if isinstance(node, FuncCall):
            arg_vals = [self._gen_expr(a) for a in node.args]
            for av in arg_vals:
                self._emit('param', av, None, None)
            tmp = self._new_tmp()
            self._emit('call', tmp, node.name, len(node.args))
            return tmp

        raise ValueError(f"Unknown expression node: {type(node)}")


def generate_ir(source: str) -> IRProgram:
    from .parser import parse
    ast = parse(source)
    return IRGenerator().generate(ast)
