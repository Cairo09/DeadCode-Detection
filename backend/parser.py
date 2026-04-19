"""
Parser — Recursive-descent parser producing an AST.

Grammar (simplified):
  program        ::= func_decl*
  func_decl      ::= type IDENT '(' params? ')' block
  params         ::= param (',' param)*
  param          ::= type IDENT
  block          ::= '{' stmt* '}'
  stmt           ::= decl_stmt | array_decl_stmt
                   | ident_stmt | prefix_incr_stmt | prefix_decr_stmt
                   | if_stmt | while_stmt | for_stmt | do_while_stmt
                   | break_stmt | continue_stmt | return_stmt | block
  decl_stmt      ::= type IDENT ('=' expr)? ';'
  array_decl_stmt::= type IDENT '[' expr ']' ';'
  ident_stmt     ::= IDENT ( '++'
                            | '--'
                            | '[' expr ']' '=' expr
                            | ('+='|'-='|'*='|'/='|'%=') expr
                            | '=' expr
                            | '(' args ')' ) ';'
  for_stmt       ::= 'for' '(' for_init? ';' expr? ';' for_update? ')' stmt
  do_while_stmt  ::= 'do' stmt 'while' '(' expr ')' ';'
  expr           ::= or_expr
  or_expr        ::= and_expr ('||' and_expr)*
  and_expr       ::= eq_expr ('&&' eq_expr)*
  eq_expr        ::= rel_expr (('=='|'!=') rel_expr)*
  rel_expr       ::= add_expr (('<'|'<='|'>'|'>=') add_expr)*
  add_expr       ::= mul_expr (('+'|'-') mul_expr)*
  mul_expr       ::= unary (('*'|'/'|'%') unary)*
  unary          ::= ('!'|'-') unary | primary
  primary        ::= INT_LIT | BOOL_LIT | CHAR_LIT | IDENT ('[' expr ']')? | IDENT '(' args ')' | '(' expr ')'
"""

from dataclasses import dataclass, field
from typing import Optional, List, Any
from .lexer import Token, TT, tokenize, LexerError

__all__ = [
    # Top-level
    'Program', 'FuncDecl', 'Param', 'Block',
    # Statements
    'DeclStmt', 'ArrayDeclStmt',
    'AssignStmt', 'ArrayAssignStmt', 'CompoundAssign',
    'IncrStmt', 'DecrStmt', 'ExprStmt',
    'IfStmt', 'WhileStmt', 'ForStmt', 'DoWhileStmt',
    'BreakStmt', 'ContinueStmt', 'ReturnStmt',
    # Expressions
    'BinOp', 'UnaryOp', 'Literal', 'Var', 'FuncCall', 'ArrayAccess',
    # Infra
    'ASTNode', 'ParseError', 'parse',
]


# ─── AST Nodes ────────────────────────────────────────────────────────────────

@dataclass
class ASTNode:
    line: int = field(default=0, repr=False)


@dataclass
class Program(ASTNode):
    functions: List['FuncDecl'] = field(default_factory=list)


@dataclass
class FuncDecl(ASTNode):
    ret_type: str = ''
    name: str = ''
    params: List['Param'] = field(default_factory=list)
    body: 'Block' = field(default=None)


@dataclass
class Param(ASTNode):
    type_: str = ''
    name: str = ''


@dataclass
class Block(ASTNode):
    stmts: List[ASTNode] = field(default_factory=list)


# ── Declaration statements ────────────────────────────────────────────────────

@dataclass
class DeclStmt(ASTNode):
    type_: str = ''
    name: str = ''
    init: Optional[ASTNode] = None


@dataclass
class ArrayDeclStmt(ASTNode):
    type_: str = ''
    name: str = ''
    size: ASTNode = field(default=None)


# ── Assignment / mutation statements ─────────────────────────────────────────

@dataclass
class AssignStmt(ASTNode):
    name: str = ''
    expr: ASTNode = field(default=None)


@dataclass
class ArrayAssignStmt(ASTNode):
    name: str = ''
    index: ASTNode = field(default=None)
    expr: ASTNode = field(default=None)


@dataclass
class CompoundAssign(ASTNode):
    """x += expr  (op is one of '+=', '-=', '*=', '/=', '%=')"""
    name: str = ''
    op: str = ''
    expr: ASTNode = field(default=None)


@dataclass
class IncrStmt(ASTNode):
    """i++ or ++i used as a statement (return value discarded)."""
    name: str = ''
    prefix: bool = False


@dataclass
class DecrStmt(ASTNode):
    """i-- or --i used as a statement (return value discarded)."""
    name: str = ''
    prefix: bool = False


@dataclass
class ExprStmt(ASTNode):
    """Expression used as a statement, e.g. a bare function call: foo(x);"""
    expr: ASTNode = field(default=None)


# ── Control-flow statements ───────────────────────────────────────────────────

@dataclass
class IfStmt(ASTNode):
    cond: ASTNode = field(default=None)
    then_: ASTNode = field(default=None)
    else_: Optional[ASTNode] = None


@dataclass
class WhileStmt(ASTNode):
    cond: ASTNode = field(default=None)
    body: ASTNode = field(default=None)


@dataclass
class ForStmt(ASTNode):
    init: Optional[ASTNode] = None    # DeclStmt / AssignStmt / CompoundAssign / None
    cond: Optional[ASTNode] = None    # expr or None (infinite loop)
    update: Optional[ASTNode] = None  # IncrStmt / DecrStmt / AssignStmt / CompoundAssign / None
    body: ASTNode = field(default=None)


@dataclass
class DoWhileStmt(ASTNode):
    body: ASTNode = field(default=None)
    cond: ASTNode = field(default=None)


@dataclass
class BreakStmt(ASTNode):
    pass


@dataclass
class ContinueStmt(ASTNode):
    pass


@dataclass
class ReturnStmt(ASTNode):
    expr: Optional[ASTNode] = None


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class BinOp(ASTNode):
    op: str = ''
    left: ASTNode = field(default=None)
    right: ASTNode = field(default=None)


@dataclass
class UnaryOp(ASTNode):
    op: str = ''
    operand: ASTNode = field(default=None)


@dataclass
class Literal(ASTNode):
    value: Any = None


@dataclass
class Var(ASTNode):
    name: str = ''


@dataclass
class FuncCall(ASTNode):
    name: str = ''
    args: List[ASTNode] = field(default_factory=list)


@dataclass
class ArrayAccess(ASTNode):
    name: str = ''
    index: ASTNode = field(default=None)


# ─── Parser ───────────────────────────────────────────────────────────────────

class ParseError(Exception):
    def __init__(self, msg, line):
        super().__init__(msg)
        self.line = line


_TYPE_TOKENS = (TT.INT, TT.BOOL, TT.CHAR, TT.VOID)

_COMPOUND_OPS = {
    TT.PLUS_ASSIGN:    '+=',
    TT.MINUS_ASSIGN:   '-=',
    TT.STAR_ASSIGN:    '*=',
    TT.SLASH_ASSIGN:   '/=',
    TT.PERCENT_ASSIGN: '%=',
}


class Parser:
    def __init__(self, tokens: List[Token]):
        self._tokens = tokens
        self._pos = 0

    # ── Primitives ─────────────────────────────────────────────────────────

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _check(self, *types) -> bool:
        return self._peek().type in types

    def _match(self, *types) -> Optional[Token]:
        if self._check(*types):
            return self._advance()
        return None

    def _expect(self, tt: TT, msg: str = None) -> Token:
        tok = self._peek()
        if tok.type != tt:
            raise ParseError(msg or f"Expected {tt.name}, got {tok.value!r}", tok.line)
        return self._advance()

    # ── Top-level ──────────────────────────────────────────────────────────

    def parse(self) -> Program:
        funcs = []
        while not self._check(TT.EOF):
            funcs.append(self._func_decl())
        return Program(functions=funcs, line=1)

    def _type(self) -> str:
        tok = self._match(*_TYPE_TOKENS)
        if tok is None:
            raise ParseError(f"Expected type, got {self._peek().value!r}", self._peek().line)
        return tok.value

    def _func_decl(self) -> FuncDecl:
        line = self._peek().line
        ret_type = self._type()
        name = self._expect(TT.IDENT).value
        self._expect(TT.LPAREN)
        params = []
        if not self._check(TT.RPAREN):
            params = self._params()
        self._expect(TT.RPAREN)
        body = self._block()
        return FuncDecl(ret_type=ret_type, name=name, params=params, body=body, line=line)

    def _params(self) -> List[Param]:
        params = [self._param()]
        while self._match(TT.COMMA):
            params.append(self._param())
        return params

    def _param(self) -> Param:
        line = self._peek().line
        t = self._type()
        n = self._expect(TT.IDENT).value
        return Param(type_=t, name=n, line=line)

    # ── Statements ─────────────────────────────────────────────────────────

    def _block(self) -> Block:
        line = self._peek().line
        self._expect(TT.LBRACE)
        stmts = []
        while not self._check(TT.RBRACE, TT.EOF):
            stmts.append(self._stmt())
        self._expect(TT.RBRACE)
        return Block(stmts=stmts, line=line)

    def _stmt(self) -> ASTNode:
        tok = self._peek()

        if tok.type in _TYPE_TOKENS:
            return self._decl_or_array_decl()
        if tok.type == TT.IF:
            return self._if_stmt()
        if tok.type == TT.WHILE:
            return self._while_stmt()
        if tok.type == TT.FOR:
            return self._for_stmt()
        if tok.type == TT.DO:
            return self._do_while_stmt()
        if tok.type == TT.RETURN:
            return self._return_stmt()
        if tok.type == TT.BREAK:
            return self._break_stmt()
        if tok.type == TT.CONTINUE:
            return self._continue_stmt()
        if tok.type == TT.LBRACE:
            return self._block()
        if tok.type == TT.IDENT:
            return self._ident_stmt()
        if tok.type == TT.PLUSPLUS:
            return self._prefix_incr_stmt()
        if tok.type == TT.MINUSMINUS:
            return self._prefix_decr_stmt()

        raise ParseError(f"Unexpected token {tok.value!r} in statement", tok.line)

    def _decl_or_array_decl(self) -> ASTNode:
        """type IDENT ( '[' expr ']' | ('=' expr)? ) ';'"""
        line = self._peek().line
        t = self._type()
        name = self._expect(TT.IDENT).value

        if self._match(TT.LBRACKET):
            size = self._expr()
            self._expect(TT.RBRACKET)
            self._expect(TT.SEMICOLON)
            return ArrayDeclStmt(type_=t, name=name, size=size, line=line)

        init = None
        if self._match(TT.ASSIGN):
            init = self._expr()
        self._expect(TT.SEMICOLON)
        return DeclStmt(type_=t, name=name, init=init, line=line)

    def _ident_stmt(self) -> ASTNode:
        """Handle all statement forms that start with an identifier."""
        line = self._peek().line
        name = self._expect(TT.IDENT).value

        # Postfix ++
        if self._check(TT.PLUSPLUS):
            self._advance()
            self._expect(TT.SEMICOLON)
            return IncrStmt(name=name, prefix=False, line=line)

        # Postfix --
        if self._check(TT.MINUSMINUS):
            self._advance()
            self._expect(TT.SEMICOLON)
            return DecrStmt(name=name, prefix=False, line=line)

        # Array assignment: arr[idx] = expr
        if self._check(TT.LBRACKET):
            self._advance()
            idx = self._expr()
            self._expect(TT.RBRACKET)
            self._expect(TT.ASSIGN)
            val = self._expr()
            self._expect(TT.SEMICOLON)
            return ArrayAssignStmt(name=name, index=idx, expr=val, line=line)

        # Compound assignment: x += expr
        if self._peek().type in _COMPOUND_OPS:
            op = _COMPOUND_OPS[self._advance().type]
            expr = self._expr()
            self._expect(TT.SEMICOLON)
            return CompoundAssign(name=name, op=op, expr=expr, line=line)

        # Simple assignment: x = expr
        if self._check(TT.ASSIGN):
            self._advance()
            expr = self._expr()
            self._expect(TT.SEMICOLON)
            return AssignStmt(name=name, expr=expr, line=line)

        # Function call as statement: foo(args)
        if self._check(TT.LPAREN):
            self._advance()
            args = []
            if not self._check(TT.RPAREN):
                args.append(self._expr())
                while self._match(TT.COMMA):
                    args.append(self._expr())
            self._expect(TT.RPAREN)
            self._expect(TT.SEMICOLON)
            return ExprStmt(expr=FuncCall(name=name, args=args, line=line), line=line)

        raise ParseError(f"Unexpected token {self._peek().value!r} after identifier '{name}'",
                         self._peek().line)

    def _prefix_incr_stmt(self) -> IncrStmt:
        line = self._peek().line
        self._advance()  # consume ++
        name = self._expect(TT.IDENT).value
        self._expect(TT.SEMICOLON)
        return IncrStmt(name=name, prefix=True, line=line)

    def _prefix_decr_stmt(self) -> DecrStmt:
        line = self._peek().line
        self._advance()  # consume --
        name = self._expect(TT.IDENT).value
        self._expect(TT.SEMICOLON)
        return DecrStmt(name=name, prefix=True, line=line)

    def _if_stmt(self) -> IfStmt:
        line = self._peek().line
        self._expect(TT.IF)
        self._expect(TT.LPAREN)
        cond = self._expr()
        self._expect(TT.RPAREN)
        then_ = self._stmt()
        else_ = None
        if self._match(TT.ELSE):
            else_ = self._stmt()
        return IfStmt(cond=cond, then_=then_, else_=else_, line=line)

    def _while_stmt(self) -> WhileStmt:
        line = self._peek().line
        self._expect(TT.WHILE)
        self._expect(TT.LPAREN)
        cond = self._expr()
        self._expect(TT.RPAREN)
        body = self._stmt()
        return WhileStmt(cond=cond, body=body, line=line)

    def _for_stmt(self) -> ForStmt:
        line = self._peek().line
        self._expect(TT.FOR)
        self._expect(TT.LPAREN)

        # Init part (optional)
        init = None
        if not self._check(TT.SEMICOLON):
            init = self._for_init()
        self._expect(TT.SEMICOLON)

        # Condition part (optional — omit means true/infinite)
        cond = None
        if not self._check(TT.SEMICOLON):
            cond = self._expr()
        self._expect(TT.SEMICOLON)

        # Update part (optional)
        update = None
        if not self._check(TT.RPAREN):
            update = self._for_update()
        self._expect(TT.RPAREN)

        body = self._stmt()
        return ForStmt(init=init, cond=cond, update=update, body=body, line=line)

    def _for_init(self) -> ASTNode:
        """Parse for-init without consuming a trailing semicolon."""
        tok = self._peek()
        if tok.type in _TYPE_TOKENS:
            line = tok.line
            t = self._type()
            name = self._expect(TT.IDENT).value
            init = None
            if self._match(TT.ASSIGN):
                init = self._expr()
            return DeclStmt(type_=t, name=name, init=init, line=line)

        # Must be an ident-based statement
        line = tok.line
        name = self._expect(TT.IDENT).value

        if self._peek().type in _COMPOUND_OPS:
            op = _COMPOUND_OPS[self._advance().type]
            expr = self._expr()
            return CompoundAssign(name=name, op=op, expr=expr, line=line)

        self._expect(TT.ASSIGN)
        expr = self._expr()
        return AssignStmt(name=name, expr=expr, line=line)

    def _for_update(self) -> ASTNode:
        """Parse for-update without consuming a trailing semicolon."""
        tok = self._peek()

        # Prefix ++/--
        if tok.type == TT.PLUSPLUS:
            self._advance()
            name = self._expect(TT.IDENT).value
            return IncrStmt(name=name, prefix=True, line=tok.line)
        if tok.type == TT.MINUSMINUS:
            self._advance()
            name = self._expect(TT.IDENT).value
            return DecrStmt(name=name, prefix=True, line=tok.line)

        # Must start with IDENT
        line = tok.line
        name = self._expect(TT.IDENT).value

        if self._check(TT.PLUSPLUS):
            self._advance()
            return IncrStmt(name=name, prefix=False, line=line)
        if self._check(TT.MINUSMINUS):
            self._advance()
            return DecrStmt(name=name, prefix=False, line=line)
        if self._peek().type in _COMPOUND_OPS:
            op = _COMPOUND_OPS[self._advance().type]
            expr = self._expr()
            return CompoundAssign(name=name, op=op, expr=expr, line=line)
        if self._check(TT.ASSIGN):
            self._advance()
            expr = self._expr()
            return AssignStmt(name=name, expr=expr, line=line)

        raise ParseError(f"Expected for-update expression", tok.line)

    def _do_while_stmt(self) -> DoWhileStmt:
        line = self._peek().line
        self._expect(TT.DO)
        body = self._stmt()
        self._expect(TT.WHILE)
        self._expect(TT.LPAREN)
        cond = self._expr()
        self._expect(TT.RPAREN)
        self._expect(TT.SEMICOLON)
        return DoWhileStmt(body=body, cond=cond, line=line)

    def _break_stmt(self) -> BreakStmt:
        line = self._peek().line
        self._expect(TT.BREAK)
        self._expect(TT.SEMICOLON)
        return BreakStmt(line=line)

    def _continue_stmt(self) -> ContinueStmt:
        line = self._peek().line
        self._expect(TT.CONTINUE)
        self._expect(TT.SEMICOLON)
        return ContinueStmt(line=line)

    def _return_stmt(self) -> ReturnStmt:
        line = self._peek().line
        self._expect(TT.RETURN)
        expr = None
        if not self._check(TT.SEMICOLON):
            expr = self._expr()
        self._expect(TT.SEMICOLON)
        return ReturnStmt(expr=expr, line=line)

    # ── Expressions ────────────────────────────────────────────────────────

    def _expr(self): return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        while self._check(TT.OR):
            op = self._advance().value
            right = self._and_expr()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _and_expr(self):
        left = self._eq_expr()
        while self._check(TT.AND):
            op = self._advance().value
            right = self._eq_expr()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _eq_expr(self):
        left = self._rel_expr()
        while self._check(TT.EQ, TT.NEQ):
            op = self._advance().value
            right = self._rel_expr()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _rel_expr(self):
        left = self._add_expr()
        while self._check(TT.LT, TT.LE, TT.GT, TT.GE):
            op = self._advance().value
            right = self._add_expr()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _add_expr(self):
        left = self._mul_expr()
        while self._check(TT.PLUS, TT.MINUS):
            op = self._advance().value
            right = self._mul_expr()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _mul_expr(self):
        left = self._unary()
        while self._check(TT.STAR, TT.SLASH, TT.PERCENT):
            op = self._advance().value
            right = self._unary()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _unary(self):
        if self._check(TT.NOT, TT.MINUS):
            tok = self._advance()
            operand = self._unary()
            return UnaryOp(op=tok.value, operand=operand, line=tok.line)
        return self._primary()

    def _primary(self):
        tok = self._peek()

        if tok.type == TT.INT_LIT:
            self._advance()
            return Literal(value=tok.value, line=tok.line)

        if tok.type == TT.BOOL_LIT:
            self._advance()
            return Literal(value=tok.value, line=tok.line)

        if tok.type == TT.CHAR_LIT:
            self._advance()
            return Literal(value=tok.value, line=tok.line)

        if tok.type == TT.IDENT:
            self._advance()
            # Function call: IDENT '(' args ')'
            if self._check(TT.LPAREN):
                self._advance()
                args = []
                if not self._check(TT.RPAREN):
                    args.append(self._expr())
                    while self._match(TT.COMMA):
                        args.append(self._expr())
                self._expect(TT.RPAREN)
                return FuncCall(name=tok.value, args=args, line=tok.line)
            # Array access: IDENT '[' expr ']'
            if self._check(TT.LBRACKET):
                self._advance()
                idx = self._expr()
                self._expect(TT.RBRACKET)
                return ArrayAccess(name=tok.value, index=idx, line=tok.line)
            return Var(name=tok.value, line=tok.line)

        if tok.type == TT.LPAREN:
            self._advance()
            expr = self._expr()
            self._expect(TT.RPAREN)
            return expr

        raise ParseError(f"Unexpected token {tok.value!r} in expression", tok.line)


def parse(source: str) -> Program:
    tokens = tokenize(source)
    return Parser(tokens).parse()
