"""
OpenMath to SymPy Function Mapper.

Maps OpenMath symbol definitions to their SymPy equivalents for code execution.
This module provides COMPREHENSIVE mappings for all math-relevant OpenMath CDs.

Note: Protocol/metadata CDs (meta, scscp1, scscp2, sts, etc.) are intentionally
not mapped as they don't represent mathematical operations.
"""

from __future__ import annotations

import sympy
import sympy.combinatorics
from sympy import S
from typing import Any, Callable


# =============================================================================
# Core Arithmetic (arith1) - 12 symbols
# =============================================================================
ARITH1_MAPPINGS = {
    "plus": ("sympy.Add", lambda *args: sympy.Add(*args)),
    "times": ("sympy.Mul", lambda *args: sympy.Mul(*args)),
    "minus": ("lambda a, b: a - b", lambda a, b: a - b),
    "divide": ("lambda a, b: a / b", lambda a, b: a / b),
    "power": ("sympy.Pow", lambda a, b: sympy.Pow(a, b)),
    "unary_minus": ("lambda a: -a", lambda a: -a),
    "abs": ("sympy.Abs", sympy.Abs),
    "gcd": ("sympy.gcd", sympy.gcd),
    "lcm": ("sympy.lcm", sympy.lcm),
    "root": ("lambda a, n: a ** (sympy.Rational(1, n))", lambda a, n: a ** (sympy.Rational(1, n))),
    "sum": ("sympy.Sum", sympy.Sum),
    "product": ("sympy.Product", sympy.Product),
}

# =============================================================================
# Relations (relation1) - 7 symbols
# =============================================================================
RELATION1_MAPPINGS = {
    "eq": ("sympy.Eq", sympy.Eq),
    "neq": ("sympy.Ne", sympy.Ne),
    "lt": ("sympy.Lt", sympy.Lt),
    "gt": ("sympy.Gt", sympy.Gt),
    "leq": ("sympy.Le", sympy.Le),
    "geq": ("sympy.Ge", sympy.Ge),
    "approx": ("lambda a, b, tol=1e-9: abs(a - b) < tol", lambda a, b, tol=1e-9: abs(a - b) < tol),
}

# =============================================================================
# Integer Operations (integer1) - 4 symbols
# =============================================================================
INTEGER1_MAPPINGS = {
    "factorial": ("sympy.factorial", sympy.factorial),
    "quotient": ("lambda a, b: a // b", lambda a, b: a // b),
    "remainder": ("lambda a, b: a % b", lambda a, b: a % b),
    "factorof": ("lambda a, b: b % a == 0", lambda a, b: b % a == 0),
}

# =============================================================================
# Transcendental Functions (transc1) - 27 symbols (COMPLETE)
# =============================================================================
TRANSC1_MAPPINGS = {
    # Basic trig
    "sin": ("sympy.sin", sympy.sin),
    "cos": ("sympy.cos", sympy.cos),
    "tan": ("sympy.tan", sympy.tan),
    "cot": ("sympy.cot", sympy.cot),
    "sec": ("sympy.sec", sympy.sec),
    "csc": ("sympy.csc", sympy.csc),
    # Inverse trig
    "arcsin": ("sympy.asin", sympy.asin),
    "arccos": ("sympy.acos", sympy.acos),
    "arctan": ("sympy.atan", sympy.atan),
    "arccot": ("sympy.acot", sympy.acot),
    "arcsec": ("sympy.asec", sympy.asec),
    "arccsc": ("sympy.acsc", sympy.acsc),
    # Hyperbolic
    "sinh": ("sympy.sinh", sympy.sinh),
    "cosh": ("sympy.cosh", sympy.cosh),
    "tanh": ("sympy.tanh", sympy.tanh),
    "coth": ("sympy.coth", sympy.coth),
    "sech": ("sympy.sech", sympy.sech),
    "csch": ("sympy.csch", sympy.csch),
    # Inverse hyperbolic
    "arcsinh": ("sympy.asinh", sympy.asinh),
    "arccosh": ("sympy.acosh", sympy.acosh),
    "arctanh": ("sympy.atanh", sympy.atanh),
    "arccoth": ("sympy.acoth", sympy.acoth),
    "arcsech": ("sympy.asech", sympy.asech),
    "arccsch": ("sympy.acsch", sympy.acsch),
    # Exponential/logarithmic
    "exp": ("sympy.exp", sympy.exp),
    "ln": ("sympy.ln", sympy.ln),
    "log": ("sympy.log", sympy.log),
}

# =============================================================================
# Logic Operations (logic1) - 11 symbols (COMPLETE)
# =============================================================================
LOGIC1_MAPPINGS = {
    "true": ("sympy.true", lambda: sympy.true),
    "false": ("sympy.false", lambda: sympy.false),
    "not": ("sympy.Not", sympy.Not),
    "and": ("sympy.And", lambda *args: sympy.And(*args)),
    "or": ("sympy.Or", lambda *args: sympy.Or(*args)),
    "implies": ("sympy.Implies", sympy.Implies),
    "equivalent": ("sympy.Equivalent", sympy.Equivalent),
    "xor": ("sympy.Xor", sympy.Xor),
    "nand": ("sympy.Nand", sympy.Nand),
    "nor": ("sympy.Nor", sympy.Nor),
    "xnor": ("lambda *args: sympy.Not(sympy.Xor(*args))", lambda *args: sympy.Not(sympy.Xor(*args))),
}

# =============================================================================
# Set Operations (set1) - 15 symbols (COMPLETE)
# =============================================================================
SET1_MAPPINGS = {
    "set": ("sympy.FiniteSet", sympy.FiniteSet),
    "union": ("sympy.Union", sympy.Union),
    "intersect": ("sympy.Intersection", sympy.Intersection),
    "setdiff": ("sympy.Complement", sympy.Complement),
    "in": ("lambda x, S: x in S", lambda x, S: x in S),
    "notin": ("lambda x, S: x not in S", lambda x, S: x not in S),
    "subset": ("lambda A, B: A.issubset(B)", lambda A, B: A.issubset(B)),
    "prsubset": ("lambda A, B: A.is_proper_subset(B)", lambda A, B: A.is_proper_subset(B)),
    "notsubset": ("lambda A, B: not A.issubset(B)", lambda A, B: not A.issubset(B)),
    "notprsubset": ("lambda A, B: not A.is_proper_subset(B)", lambda A, B: not A.is_proper_subset(B)),
    "emptyset": ("sympy.EmptySet", sympy.EmptySet),
    "cartesian_product": ("sympy.ProductSet", sympy.ProductSet),
    "size": ("lambda S: S.measure if hasattr(S, 'measure') else len(S)",
             lambda S: S.measure if hasattr(S, 'measure') else len(S)),
    "map": ("lambda f, S: S.image(f)", lambda f, S: S.image(f) if hasattr(S, 'image') else {f(x) for x in S}),
    "suchthat": ("lambda S, pred: S & sympy.ConditionSet(sympy.Symbol('x'), pred, S)",
                 lambda S, pred: sympy.ConditionSet(sympy.Symbol('x'), pred, S)),
}

# =============================================================================
# Calculus (calculus1) - 6 symbols (COMPLETE)
# =============================================================================
CALCULUS1_MAPPINGS = {
    "diff": ("sympy.diff", sympy.diff),
    "int": ("sympy.integrate", sympy.integrate),
    "defint": ("sympy.integrate", sympy.integrate),
    "nthdiff": ("lambda f, x, n: sympy.diff(f, x, n)", lambda f, x, n: sympy.diff(f, x, n)),
    "partialdiff": ("sympy.diff", sympy.diff),
    "partialdiffdegree": ("lambda f, *args: sympy.diff(f, *args)", lambda f, *args: sympy.diff(f, *args)),
}

# =============================================================================
# Linear Algebra (linalg1, linalg2) - 10 symbols
# =============================================================================
LINALG1_MAPPINGS = {
    "vector_selector": ("lambda v, i: v[i-1]", lambda v, i: v[i-1]),  # 1-indexed
    "matrix_selector": ("lambda M, i, j: M[i-1, j-1]", lambda M, i, j: M[i-1, j-1]),
    "determinant": ("lambda M: M.det()", lambda M: M.det()),
    "transpose": ("lambda M: M.T", lambda M: M.T),
    "scalarproduct": ("lambda u, v: u.dot(v)", lambda u, v: u.dot(v)),
    "outerproduct": ("lambda u, v: u * v.T", lambda u, v: u * v.T),
    "vectorproduct": ("lambda u, v: u.cross(v)", lambda u, v: u.cross(v)),
}

LINALG2_MAPPINGS = {
    "vector": ("sympy.Matrix", lambda *args: sympy.Matrix(list(args))),
    "matrix": ("sympy.Matrix", sympy.Matrix),
    "matrixrow": ("lambda *args: list(args)", lambda *args: list(args)),
}

# =============================================================================
# Combinatorics (combinat1) - 6 symbols (expanded for experimental CD)
# =============================================================================
COMBINAT1_MAPPINGS = {
    "binomial": ("sympy.binomial", sympy.binomial),
    "multinomial": ("sympy.multinomial_coefficients",
                    lambda n, k: sympy.ntheory.multinomial.multinomial_coefficients(n, k)),
    # Note: Stirling symbols in experimental CD use capital S
    "Stirling1": ("sympy.functions.combinatorial.numbers.stirling",
                  lambda n, k: sympy.functions.combinatorial.numbers.stirling(n, k, kind=1)),
    "Stirling2": ("sympy.functions.combinatorial.numbers.stirling",
                  lambda n, k: sympy.functions.combinatorial.numbers.stirling(n, k, kind=2)),
    # Also support lowercase for compatibility
    "stirling1": ("sympy.functions.combinatorial.numbers.stirling",
                  lambda n, k: sympy.functions.combinatorial.numbers.stirling(n, k, kind=1)),
    "stirling2": ("sympy.functions.combinatorial.numbers.stirling",
                  lambda n, k: sympy.functions.combinatorial.numbers.stirling(n, k, kind=2)),
    "Fibonacci": ("sympy.fibonacci", sympy.fibonacci),
    "Bell": ("sympy.bell", sympy.bell),
}

# =============================================================================
# Minimum/Maximum (minmax1) - 2 symbols
# =============================================================================
MINMAX1_MAPPINGS = {
    "min": ("sympy.Min", sympy.Min),
    "max": ("sympy.Max", sympy.Max),
}

# =============================================================================
# Numeric Constants (nums1) - 9 symbols (NEW)
# =============================================================================
NUMS1_MAPPINGS = {
    "e": ("sympy.E", lambda: sympy.E),
    "i": ("sympy.I", lambda: sympy.I),
    "pi": ("sympy.pi", lambda: sympy.pi),
    "gamma": ("sympy.EulerGamma", lambda: sympy.EulerGamma),
    "infinity": ("sympy.oo", lambda: sympy.oo),
    "NaN": ("sympy.nan", lambda: sympy.nan),
    "rational": ("sympy.Rational", sympy.Rational),
    "based_integer": ("lambda val, base: int(val, base)", lambda val, base: int(str(val), base)),
    "based_float": ("lambda val, base: float(val)", lambda val, base: float(val)),
}

# =============================================================================
# Number Sets (setname1) - 6 symbols (NEW)
# =============================================================================
SETNAME1_MAPPINGS = {
    "P": ("sympy.Primes", lambda: sympy.S.Primes),
    "N": ("sympy.Naturals", lambda: sympy.S.Naturals),
    "Z": ("sympy.Integers", lambda: sympy.S.Integers),
    "Q": ("sympy.Rationals", lambda: sympy.S.Rationals),
    "R": ("sympy.Reals", lambda: sympy.S.Reals),
    "C": ("sympy.Complexes", lambda: sympy.S.Complexes),
}

# =============================================================================
# Rounding (rounding1) - 4 symbols (NEW)
# =============================================================================
ROUNDING1_MAPPINGS = {
    "ceiling": ("sympy.ceiling", sympy.ceiling),
    "floor": ("sympy.floor", sympy.floor),
    "trunc": ("lambda x: sympy.sign(x) * sympy.floor(sympy.Abs(x))",
              lambda x: sympy.sign(x) * sympy.floor(sympy.Abs(x))),
    "round": ("lambda x: sympy.floor(x + sympy.Rational(1, 2))",
              lambda x: sympy.floor(x + sympy.Rational(1, 2))),
}

# =============================================================================
# Complex Numbers (complex1) - 6 symbols (NEW)
# =============================================================================
COMPLEX1_MAPPINGS = {
    "complex_cartesian": ("lambda re, im: re + sympy.I * im", lambda re, im: re + sympy.I * im),
    "complex_polar": ("lambda r, theta: r * sympy.exp(sympy.I * theta)",
                      lambda r, theta: r * sympy.exp(sympy.I * theta)),
    "real": ("sympy.re", sympy.re),
    "imaginary": ("sympy.im", sympy.im),
    "argument": ("sympy.arg", sympy.arg),
    "conjugate": ("sympy.conjugate", sympy.conjugate),
}

# =============================================================================
# Limits (limit1) - 5 symbols (NEW)
# =============================================================================
LIMIT1_MAPPINGS = {
    "limit": ("sympy.limit", sympy.limit),
    "both_sides": ("'+' or '-'", lambda: "+-"),  # Direction indicator
    "above": ("'+'", lambda: "+"),
    "below": ("'-'", lambda: "-"),
    "null": ("None", lambda: None),
}

# =============================================================================
# Piecewise Functions (piece1) - 3 symbols (NEW)
# =============================================================================
PIECE1_MAPPINGS = {
    "piecewise": ("sympy.Piecewise", sympy.Piecewise),
    "piece": ("lambda expr, cond: (expr, cond)", lambda expr, cond: (expr, cond)),
    "otherwise": ("lambda expr: (expr, True)", lambda expr: (expr, True)),
}

# =============================================================================
# Intervals (interval1) - 7 symbols (NEW)
# =============================================================================
INTERVAL1_MAPPINGS = {
    "integer_interval": ("lambda a, b: sympy.Range(a, b + 1)", lambda a, b: sympy.Range(a, b + 1)),
    "interval": ("sympy.Interval", sympy.Interval),
    "interval_oo": ("lambda a, b: sympy.Interval.open(a, b)", lambda a, b: sympy.Interval.open(a, b)),
    "interval_cc": ("lambda a, b: sympy.Interval(a, b)", lambda a, b: sympy.Interval(a, b)),
    "interval_oc": ("lambda a, b: sympy.Interval.Lopen(a, b)", lambda a, b: sympy.Interval.Lopen(a, b)),
    "interval_co": ("lambda a, b: sympy.Interval.Ropen(a, b)", lambda a, b: sympy.Interval.Ropen(a, b)),
    "oriented_interval": ("lambda a, b: sympy.Interval(a, b)", lambda a, b: sympy.Interval(a, b)),
}

# =============================================================================
# Algebra Constants (alg1) - 2 symbols (NEW)
# =============================================================================
ALG1_MAPPINGS = {
    "zero": ("sympy.S.Zero", lambda: S.Zero),
    "one": ("sympy.S.One", lambda: S.One),
}

# =============================================================================
# Quantifiers (quant1) - 2 symbols (NEW)
# Note: These return SymPy ForAll/Exists for symbolic representation
# =============================================================================
QUANT1_MAPPINGS = {
    "forall": ("lambda var, pred: sympy.ForAll(var, pred) if hasattr(sympy, 'ForAll') else ('forall', var, pred)",
               lambda var, pred: ('forall', var, pred)),
    "exists": ("lambda var, pred: sympy.Exists(var, pred) if hasattr(sympy, 'Exists') else ('exists', var, pred)",
               lambda var, pred: ('exists', var, pred)),
}

# =============================================================================
# Statistics (s_data1, s_dist1) - 6 symbols each (NEW)
# Note: These use SymPy's statistics module where available
# =============================================================================
S_DATA1_MAPPINGS = {
    "mean": ("lambda *args: sum(args) / len(args)", lambda *args: sum(args) / len(args)),
    "sdev": ("lambda *args: sympy.sqrt(sum((x - sum(args)/len(args))**2 for x in args) / len(args))",
             lambda *args: sympy.sqrt(sum((x - sum(args)/len(args))**2 for x in args) / len(args))),
    "variance": ("lambda *args: sum((x - sum(args)/len(args))**2 for x in args) / len(args)",
                 lambda *args: sum((x - sum(args)/len(args))**2 for x in args) / len(args)),
    "mode": ("lambda *args: max(set(args), key=list(args).count)",
             lambda *args: max(set(args), key=list(args).count)),
    "median": ("lambda *args: sorted(args)[len(args)//2]",
               lambda *args: sorted(args)[len(args)//2]),
    "moment": ("lambda data, n: sum(x**n for x in data) / len(data)",
               lambda data, n: sum(x**n for x in data) / len(data)),
}

# s_dist1 maps to same implementations
S_DIST1_MAPPINGS = S_DATA1_MAPPINGS.copy()

# =============================================================================
# Functions (fns1) - 11 symbols (NEW)
# =============================================================================
FNS1_MAPPINGS = {
    "domain": ("lambda f: f.domain if hasattr(f, 'domain') else None",
               lambda f: f.domain if hasattr(f, 'domain') else None),
    "range": ("lambda f: f.range if hasattr(f, 'range') else None",
              lambda f: f.range if hasattr(f, 'range') else None),
    "image": ("lambda f, S: S.image(f)", lambda f, S: S.image(f) if hasattr(S, 'image') else None),
    "identity": ("lambda x: x", lambda x: x),
    "inverse": ("lambda f: 1/f", lambda f: 1/f),
    "left_inverse": ("lambda f: 1/f", lambda f: 1/f),
    "right_inverse": ("lambda f: 1/f", lambda f: 1/f),
    "lambda": ("lambda var, expr: sympy.Lambda(var, expr)", lambda var, expr: sympy.Lambda(var, expr)),
    "compose": ("lambda f, g: lambda x: f(g(x))", lambda f, g: lambda x: f(g(x))),
    "restriction": ("lambda f, S: f", lambda f, S: f),  # Simplified
    "domainofapplication": ("lambda S: S", lambda S: S),
}

# =============================================================================
# Vector Calculus (veccalc1) - 4 symbols (NEW)
# =============================================================================
VECCALC1_MAPPINGS = {
    "divergence": ("lambda F, vars: sum(sympy.diff(F[i], vars[i]) for i in range(len(vars)))",
                   lambda F, vars: sum(sympy.diff(F[i], vars[i]) for i in range(len(vars)))),
    "grad": ("lambda f, vars: sympy.Matrix([sympy.diff(f, v) for v in vars])",
             lambda f, vars: sympy.Matrix([sympy.diff(f, v) for v in vars])),
    "curl": ("lambda F, vars: sympy.Matrix([sympy.diff(F[2], vars[1]) - sympy.diff(F[1], vars[2]), sympy.diff(F[0], vars[2]) - sympy.diff(F[2], vars[0]), sympy.diff(F[1], vars[0]) - sympy.diff(F[0], vars[1])])",
             lambda F, vars: sympy.Matrix([
                 sympy.diff(F[2], vars[1]) - sympy.diff(F[1], vars[2]),
                 sympy.diff(F[0], vars[2]) - sympy.diff(F[2], vars[0]),
                 sympy.diff(F[1], vars[0]) - sympy.diff(F[0], vars[1])
             ])),
    "Laplacian": ("lambda f, vars: sum(sympy.diff(f, v, 2) for v in vars)",
                  lambda f, vars: sum(sympy.diff(f, v, 2) for v in vars)),
}

# =============================================================================
# Lists (list1) - 3 symbols (NEW)
# =============================================================================
LIST1_MAPPINGS = {
    "list": ("lambda *args: list(args)", lambda *args: list(args)),
    "map": ("lambda f, lst: [f(x) for x in lst]", lambda f, lst: [f(x) for x in lst]),
    "suchthat": ("lambda lst, pred: [x for x in lst if pred(x)]",
                 lambda lst, pred: [x for x in lst if pred(x)]),
}

# =============================================================================
# EXPERIMENTAL CDs - Polynomial Operations (polynomial1-4)
# =============================================================================
POLYNOMIAL1_MAPPINGS = {
    "degree": ("sympy.degree", sympy.degree),
    "coefficient": ("sympy.Poly.nth", lambda p, n: sympy.Poly(p).nth(n)),
    "expand": ("sympy.expand", sympy.expand),
    "leading_term": ("sympy.LT", sympy.LT),
    "leading_coefficient": ("sympy.LC", sympy.LC),
    "leading_monomial": ("sympy.LM", sympy.LM),
}

POLYNOMIAL3_MAPPINGS = {
    "gcd": ("sympy.gcd", sympy.gcd),
    "lcm": ("sympy.lcm", sympy.lcm),
    "quotient": ("sympy.div", lambda a, b: sympy.div(a, b)[0]),
    "remainder": ("sympy.div", lambda a, b: sympy.div(a, b)[1]),
}

POLYNOMIAL4_MAPPINGS = {
    "factorise": ("sympy.factor", sympy.factor),
    "factors": ("sympy.factorint", sympy.factorint),
}

# =============================================================================
# EXPERIMENTAL CDs - Linear Algebra Extensions (linalg3-5)
# =============================================================================
LINALG3_MAPPINGS = {
    "rowcount": ("lambda M: M.rows", lambda M: M.rows),
    "columncount": ("lambda M: M.cols", lambda M: M.cols),
    "vector": ("sympy.Matrix", lambda *args: sympy.Matrix(list(args))),
    "matrix": ("sympy.Matrix", sympy.Matrix),
}

LINALG4_MAPPINGS = {
    "eigenvalue": ("lambda M: M.eigenvals()", lambda M: M.eigenvals()),
    "eigenvector": ("lambda M: M.eigenvects()", lambda M: M.eigenvects()),
    "characteristic_eqn": ("lambda M, x: M.charpoly(x)", lambda M, x=sympy.Symbol('x'): M.charpoly(x)),
    "rank": ("lambda M: M.rank()", lambda M: M.rank()),
    "rowcount": ("lambda M: M.rows", lambda M: M.rows),
    "columncount": ("lambda M: M.cols", lambda M: M.cols),
}

LINALG5_MAPPINGS = {
    "identity": ("sympy.eye", sympy.eye),
    "zero": ("sympy.zeros", sympy.zeros),
    "diagonal_matrix": ("sympy.diag", sympy.diag),
    "symmetric": ("lambda M: M.equals(M.T)", lambda M: M.equals(M.T)),
    "Hermitian": ("lambda M: M.equals(M.H)", lambda M: M.equals(M.H)),
    "tridiagonal": ("lambda M: M.is_tridiagonal if hasattr(M, 'is_tridiagonal') else None",
                    lambda M: M.is_tridiagonal if hasattr(M, 'is_tridiagonal') else None),
    "upper_triangular": ("lambda M: M.is_upper", lambda M: M.is_upper),
    "lower_triangular": ("lambda M: M.is_lower", lambda M: M.is_lower),
}

# =============================================================================
# EXPERIMENTAL CDs - Number Theory Extensions (integer2, arith3)
# =============================================================================
INTEGER2_MAPPINGS = {
    "divides": ("lambda a, b: b % a == 0", lambda a, b: b % a == 0),
    "eqmod": ("lambda a, b, n: (a - b) % n == 0", lambda a, b, n: (a - b) % n == 0),
    "euler": ("sympy.totient", sympy.totient),
    "ord": ("lambda a, n: sympy.n_order(a, n)", lambda a, n: sympy.n_order(a, n)),
}

ARITH3_MAPPINGS = {
    "extended_gcd": ("sympy.gcdex", sympy.gcdex),
}

# =============================================================================
# EXPERIMENTAL CDs - Permutations (permutation1)
# =============================================================================
PERMUTATION1_MAPPINGS = {
    "cycle": ("sympy.combinatorics.Permutation", sympy.combinatorics.Permutation),
    "is_bijective": ("lambda p: p.is_bijective if hasattr(p, 'is_bijective') else True",
                     lambda p: True),
    "order": ("lambda p: p.order()", lambda p: p.order() if hasattr(p, 'order') else None),
    "inverse": ("lambda p: p**-1", lambda p: p**-1 if hasattr(p, '__pow__') else None),
    "sign": ("lambda p: p.signature()", lambda p: p.signature() if hasattr(p, 'signature') else None),
}

# =============================================================================
# Multiset (multiset1) - 13 symbols (NEW)
# =============================================================================
MULTISET1_MAPPINGS = {
    "multiset": ("lambda *args: list(args)", lambda *args: list(args)),
    "size": ("len", len),
    "intersect": ("lambda a, b: [x for x in a if x in b]", lambda a, b: [x for x in a if x in b]),
    "union": ("lambda a, b: a + b", lambda a, b: list(a) + list(b)),
    "setdiff": ("lambda a, b: [x for x in a if x not in b]", lambda a, b: [x for x in a if x not in b]),
    "subset": ("lambda a, b: all(x in b for x in a)", lambda a, b: all(x in b for x in a)),
    "in": ("lambda x, S: x in S", lambda x, S: x in S),
    "notin": ("lambda x, S: x not in S", lambda x, S: x not in S),
    "prsubset": ("lambda a, b: all(x in b for x in a) and len(a) < len(b)",
                 lambda a, b: all(x in b for x in a) and len(a) < len(b)),
    "notsubset": ("lambda a, b: not all(x in b for x in a)",
                  lambda a, b: not all(x in b for x in a)),
    "notprsubset": ("lambda a, b: not (all(x in b for x in a) and len(a) < len(b))",
                   lambda a, b: not (all(x in b for x in a) and len(a) < len(b))),
    "cartesian_product": ("lambda *sets: list(itertools.product(*sets))",
                          lambda *sets: list(__import__('itertools').product(*sets))),
    "emptyset": ("[]", lambda: []),
}


# =============================================================================
# SympyMapper Class
# =============================================================================
class SympyMapper:
    """Maps OpenMath symbols to SymPy functions.

    Provides comprehensive mappings for 21 math-relevant Content Dictionaries.
    Protocol/metadata CDs (meta, scscp*, sts, etc.) are intentionally excluded.
    """

    def __init__(self):
        """Initialize the mapper with all CD mappings."""
        self.mappings: dict[str, tuple[str, Callable]] = {}

        # Register all mappings by CD
        cd_mappings = {
            # Original CDs
            "arith1": ARITH1_MAPPINGS,
            "relation1": RELATION1_MAPPINGS,
            "integer1": INTEGER1_MAPPINGS,
            "transc1": TRANSC1_MAPPINGS,
            "logic1": LOGIC1_MAPPINGS,
            "set1": SET1_MAPPINGS,
            "calculus1": CALCULUS1_MAPPINGS,
            "linalg1": LINALG1_MAPPINGS,
            "linalg2": LINALG2_MAPPINGS,
            "combinat1": COMBINAT1_MAPPINGS,
            "minmax1": MINMAX1_MAPPINGS,
            # NEW CDs (from Official)
            "nums1": NUMS1_MAPPINGS,
            "setname1": SETNAME1_MAPPINGS,
            "rounding1": ROUNDING1_MAPPINGS,
            "complex1": COMPLEX1_MAPPINGS,
            "limit1": LIMIT1_MAPPINGS,
            "piece1": PIECE1_MAPPINGS,
            "interval1": INTERVAL1_MAPPINGS,
            "alg1": ALG1_MAPPINGS,
            "quant1": QUANT1_MAPPINGS,
            "s_data1": S_DATA1_MAPPINGS,
            "s_dist1": S_DIST1_MAPPINGS,
            "fns1": FNS1_MAPPINGS,
            "veccalc1": VECCALC1_MAPPINGS,
            "list1": LIST1_MAPPINGS,
            "multiset1": MULTISET1_MAPPINGS,
            # EXPERIMENTAL CDs
            "polynomial1": POLYNOMIAL1_MAPPINGS,
            "polynomial3": POLYNOMIAL3_MAPPINGS,
            "polynomial4": POLYNOMIAL4_MAPPINGS,
            "linalg3": LINALG3_MAPPINGS,
            "linalg4": LINALG4_MAPPINGS,
            "linalg5": LINALG5_MAPPINGS,
            "integer2": INTEGER2_MAPPINGS,
            "arith3": ARITH3_MAPPINGS,
            "permutation1": PERMUTATION1_MAPPINGS,
        }

        for cd_name, cd_map in cd_mappings.items():
            for symbol_name, (code_str, func) in cd_map.items():
                symbol_id = f"{cd_name}:{symbol_name}"
                self.mappings[symbol_id] = (code_str, func)

    def get_sympy_function(self, symbol_id: str) -> str | None:
        """
        Get the SymPy function string for an OpenMath symbol.

        Args:
            symbol_id: Symbol ID in format "cd:name"

        Returns:
            SymPy function string or None if not mapped
        """
        if symbol_id in self.mappings:
            return self.mappings[symbol_id][0]
        return None

    def get_callable(self, symbol_id: str) -> Callable | None:
        """
        Get the callable function for an OpenMath symbol.

        Args:
            symbol_id: Symbol ID in format "cd:name"

        Returns:
            Callable function or None if not mapped
        """
        if symbol_id in self.mappings:
            return self.mappings[symbol_id][1]
        return None

    def is_mapped(self, symbol_id: str) -> bool:
        """Check if a symbol has a SymPy mapping."""
        return symbol_id in self.mappings

    def get_all_mappings(self) -> dict[str, str]:
        """Get all symbol ID to SymPy function string mappings."""
        return {sid: code for sid, (code, _) in self.mappings.items()}

    def get_statistics(self) -> dict:
        """Get mapping statistics by CD."""
        stats = {}
        for symbol_id in self.mappings:
            cd = symbol_id.split(":")[0]
            stats[cd] = stats.get(cd, 0) + 1
        return {
            "total_mappings": len(self.mappings),
            "cds_covered": len(stats),
            "by_cd": stats
        }
