"""
Lexer — Tokenizer for a C-like language.
Supports: int/bool/char/void types, if/else/while/for/do, break/continue,
          return, true/false, arithmetic/relational/logical operators,
          compound assignments, ++/--, arrays, char literals, identifiers.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):
    """Token types."""
    # Literals
    INT_LIT    = auto()
    BOOL_LIT   = auto()
    CHAR_LIT   = auto()
    # Keywords — types
    INT        = auto()
    BOOL       = auto()
    CHAR       = auto()
    VOID       = auto()
    # Keywords — control flow
    IF         = auto()
    ELSE       = auto()
    WHILE      = auto()
    FOR        = auto()
    DO         = auto()
    BREAK      = auto()
    CONTINUE   = auto()
    RETURN     = auto()
    # Identifiers
    IDENT      = auto()
    # Compound assignment operators
    PLUS_ASSIGN    = auto()   # +=
    MINUS_ASSIGN   = auto()   # -=
    STAR_ASSIGN    = auto()   # *=
    SLASH_ASSIGN   = auto()   # /=
    PERCENT_ASSIGN = auto()   # %=
    # Increment / decrement
    PLUSPLUS   = auto()   # ++
    MINUSMINUS = auto()   # --
    # Comparison operators
    EQ         = auto()   # ==
    NEQ        = auto()   # !=
    LT         = auto()
    LE         = auto()
    GT         = auto()
    GE         = auto()
    # Logical operators
    AND        = auto()   # &&
    OR         = auto()   # ||
    NOT        = auto()   # !
    # Arithmetic operators
    PLUS       = auto()
    MINUS      = auto()
    STAR       = auto()
    SLASH      = auto()
    PERCENT    = auto()
    # Assignment
    ASSIGN     = auto()   # =
    # Punctuation
    LPAREN     = auto()
    RPAREN     = auto()
    LBRACE     = auto()
    RBRACE     = auto()
    LBRACKET   = auto()   # [
    RBRACKET   = auto()   # ]
    SEMICOLON  = auto()
    COMMA      = auto()
    # Special
    EOF        = auto()


@dataclass
class Token:
    type: TT
    value: object
    line: int


KEYWORDS = {
    'int':      TT.INT,
    'bool':     TT.BOOL,
    'char':     TT.CHAR,
    'void':     TT.VOID,
    'if':       TT.IF,
    'else':     TT.ELSE,
    'while':    TT.WHILE,
    'for':      TT.FOR,
    'do':       TT.DO,
    'break':    TT.BREAK,
    'continue': TT.CONTINUE,
    'return':   TT.RETURN,
    'true':     TT.BOOL_LIT,
    'false':    TT.BOOL_LIT,
}

# ORDER IS CRITICAL — longer/compound tokens must come before their prefixes.
# e.g. '++' before '+', '+=' before '+' and '=', '==' before '=', etc.
TOKEN_PATTERNS = [
    (r"'(?:[^'\\]|\\.)'",  'CHAR_LIT'),       # char literal: 'a', '\n', '\\'
    (r'\d+',               'INT_LIT'),
    (r'==',                'EQ'),
    (r'!=',                'NEQ'),
    (r'<=',                'LE'),
    (r'>=',                'GE'),
    (r'&&',                'AND'),
    (r'\|\|',              'OR'),
    (r'\+\+',              'PLUSPLUS'),
    (r'--',                'MINUSMINUS'),
    (r'\+=',               'PLUS_ASSIGN'),
    (r'-=',                'MINUS_ASSIGN'),
    (r'\*=',               'STAR_ASSIGN'),
    (r'/=',                'SLASH_ASSIGN'),
    (r'%=',                'PERCENT_ASSIGN'),
    (r'<',                 'LT'),
    (r'>',                 'GT'),
    (r'!',                 'NOT'),
    (r'\+',                'PLUS'),
    (r'-',                 'MINUS'),
    (r'\*',                'STAR'),
    (r'/',                 'SLASH'),
    (r'%',                 'PERCENT'),
    (r'=',                 'ASSIGN'),
    (r'\(',                'LPAREN'),
    (r'\)',                'RPAREN'),
    (r'\{',                'LBRACE'),
    (r'\}',                'RBRACE'),
    (r'\[',                'LBRACKET'),
    (r'\]',                'RBRACKET'),
    (r';',                 'SEMICOLON'),
    (r',',                 'COMMA'),
    (r'[A-Za-z_]\w*',      'IDENT'),
]

MASTER_RE = re.compile('|'.join(f'(?P<P{i}>{p})' for i, (p, _) in enumerate(TOKEN_PATTERNS)))

_CHAR_ESCAPES = {
    'n': 10, 't': 9, 'r': 13, '0': 0,
    '\\': 92, "'": 39, '"': 34, 'a': 7, 'b': 8,
}


class LexerError(Exception):
    def __init__(self, msg, line):
        super().__init__(msg)
        self.line = line


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    line = 1

    # Strip single-line comments
    source = re.sub(r'//[^\n]*', '', source)
    # Strip multi-line comments
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)

    i = 0
    while i < len(source):
        c = source[i]
        if c == '\n':
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue

        m = MASTER_RE.match(source, i)
        if not m:
            raise LexerError(f"Unexpected character '{c}'", line)

        text = m.group()
        pattern_idx = next(j for j, g in enumerate(m.groups()) if g is not None)
        _, ttype_name = TOKEN_PATTERNS[pattern_idx]

        if ttype_name == 'CHAR_LIT':
            tt = TT.CHAR_LIT
            inner = text[1:-1]  # strip surrounding quotes
            if inner and inner[0] == '\\' and len(inner) >= 2:
                val = _CHAR_ESCAPES.get(inner[1], ord(inner[1]))
            elif inner:
                val = ord(inner[0])
            else:
                val = 0

        elif ttype_name == 'INT_LIT':
            tt = TT.INT_LIT
            val = int(text)

        elif ttype_name == 'IDENT' and text in KEYWORDS:
            tt = KEYWORDS[text]
            val = True if text == 'true' else (False if text == 'false' else text)

        elif ttype_name == 'IDENT':
            tt = TT.IDENT
            val = text

        else:
            tt = TT[ttype_name]
            val = text

        tokens.append(Token(tt, val, line))
        i = m.end()

    tokens.append(Token(TT.EOF, None, line))
    return tokens
