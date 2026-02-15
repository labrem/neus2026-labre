"""
This script parses all OpenMath CDs and STS files to create:
1. data/openmath.json - Complete knowledge base
2. data/index.json - Keyword search index

Usage:
    python pipeline/1a_build_knowledge_base.py                     # Official CDs only
    python pipeline/1a_build_knowledge_base.py --experimental      # Official + Experimental CDs
"""

from pathlib import Path
import json
from datetime import datetime, timezone
import sys
import logging
import argparse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openmath_parser import OpenMathParser
from sympy_mapper import SympyMapper

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    # Parse command-line arguments
    arg_parser = argparse.ArgumentParser(description="Build OpenMath Knowledge Base")
    arg_parser.add_argument(
        "--experimental", "-e",
        action="store_true",
        help="Include experimental CDs in addition to Official CDs"
    )
    args = arg_parser.parse_args()

    project_root = Path(__file__).parent.parent
    cds_dir = project_root / "openmath-cds"
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)

    if not cds_dir.exists():
        logger.error(f"OpenMath CDs directory not found at {cds_dir}")
        logger.error("Please run: git submodule update --init --recursive")
        sys.exit(1)

    logger.info("Starting OpenMath Knowledge Base build...")
    if args.experimental:
        logger.info("Including EXPERIMENTAL Content Dictionaries")

    # Parse all CDs
    parser = OpenMathParser(cds_dir, include_experimental=args.experimental)
    kb = parser.parse_all()

    # Add SymPy mappings
    logger.info("Adding SymPy mappings...")
    mapper = SympyMapper()
    mapped_count = 0
    total_symbols = len(kb["symbols"])
    
    for symbol_id, symbol_data in kb["symbols"].items():
        sympy_func = mapper.get_sympy_function(symbol_id)
        if sympy_func:
            symbol_data["sympy_function"] = sympy_func
            symbol_data["sympy_signature"] = sympy_func # Using logic from instructions
            mapped_count += 1
        else:
            symbol_data["sympy_function"] = None
            symbol_data["sympy_signature"] = None

    logger.info(f"Mapped {mapped_count}/{total_symbols} symbols to SymPy ({mapped_count/total_symbols*100:.1f}%)")

    # Add metadata
    kb["version"] = "1.0.0"
    kb["generated"] = datetime.now(timezone.utc).isoformat()
    
    # Add statistics to metadata
    kb["statistics"] = {
        "total_cds": len(kb["content_dictionaries"]),
        "total_symbols": total_symbols,
        "sympy_mapped": mapped_count
    }

    # Save knowledge base
    kb_path = data_dir / "openmath.json"
    with open(kb_path, "w") as f:
        json.dump(kb, f, indent=2)
    logger.info(f"Knowledge base saved to: {kb_path}")

    # Build and save keyword index
    logger.info("Building keyword index...")
    index = build_keyword_index(kb)
    index_path = data_dir / "index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    logger.info(f"Keyword index saved to: {index_path}")
    logger.info(f"  - Keywords: {len(index['index'])}")


def build_keyword_index(kb: dict) -> dict:
    """Build keyword search index from knowledge base with synonyms."""

    # Comprehensive synonym mappings for natural language retrieval
    SYNONYMS = {
        # Trigonometric
        "sine": ["sin"],
        "cosine": ["cos"],
        "tangent": ["tan"],
        "cotangent": ["cot"],
        "secant": ["sec"],
        "cosecant": ["csc"],
        "arcsine": ["arcsin"],
        "arccosine": ["arccos"],
        "arctangent": ["arctan"],
        "inverse sine": ["arcsin"],
        "inverse cosine": ["arccos"],
        "inverse tangent": ["arctan"],
        # Hyperbolic
        "hyperbolic sine": ["sinh"],
        "hyperbolic cosine": ["cosh"],
        "hyperbolic tangent": ["tanh"],
        # Arithmetic
        "addition": ["plus"],
        "add": ["plus"],
        "sum": ["plus"],
        "subtraction": ["minus"],
        "subtract": ["minus"],
        "difference": ["minus"],
        "multiplication": ["times"],
        "multiply": ["times"],
        "product": ["times"],
        "division": ["divide"],
        "divide": ["divide"],
        "quotient": ["divide", "quotient"],
        "exponent": ["power"],
        "exponentiation": ["power"],
        "raise to power": ["power"],
        "square root": ["root"],
        "nth root": ["root"],
        "cube root": ["root"],
        "absolute value": ["abs"],
        "modulus": ["abs"],
        "magnitude": ["abs"],
        # Number theory
        "greatest common divisor": ["gcd"],
        "highest common factor": ["gcd"],
        "hcf": ["gcd"],
        "least common multiple": ["lcm"],
        "lowest common multiple": ["lcm"],
        "factorial": ["factorial"],
        "remainder": ["remainder"],
        "modulo": ["remainder"],
        "mod": ["remainder"],
        # Relations
        "equal": ["eq"],
        "equals": ["eq"],
        "equality": ["eq"],
        "not equal": ["neq"],
        "unequal": ["neq"],
        "inequality": ["neq"],
        "less than": ["lt"],
        "smaller": ["lt"],
        "greater than": ["gt"],
        "larger": ["gt"],
        "bigger": ["gt"],
        "less than or equal": ["leq"],
        "at most": ["leq"],
        "greater than or equal": ["geq"],
        "at least": ["geq"],
        "approximately": ["approx"],
        "approximately equal": ["approx"],
        # Logic
        "negation": ["not"],
        "conjunction": ["and"],
        "disjunction": ["or"],
        "implication": ["implies"],
        "biconditional": ["equivalent"],
        "exclusive or": ["xor"],
        # Calculus
        "derivative": ["diff"],
        "differentiate": ["diff"],
        "differentiation": ["diff"],
        "partial derivative": ["partialdiff"],
        "integral": ["int"],
        "integrate": ["int"],
        "integration": ["int"],
        "definite integral": ["defint"],
        "antiderivative": ["int"],
        "limit": ["limit"],
        # Sets
        "union": ["union"],
        "intersection": ["intersect"],
        "set difference": ["setdiff"],
        "complement": ["setdiff"],
        "element of": ["in"],
        "member of": ["in"],
        "belongs to": ["in"],
        "not element of": ["notin"],
        "subset": ["subset"],
        "superset": ["subset"],
        "proper subset": ["prsubset"],
        "empty set": ["emptyset"],
        "null set": ["emptyset"],
        "cartesian product": ["cartesian_product"],
        "cross product": ["cartesian_product"],
        # Constants
        "euler's number": ["e"],
        "natural base": ["e"],
        "imaginary unit": ["i"],
        "pi": ["pi"],
        "euler-mascheroni": ["gamma"],
        "infinity": ["infinity"],
        "infinite": ["infinity"],
        # Number sets
        "natural numbers": ["N"],
        "naturals": ["N"],
        "integers": ["Z"],
        "whole numbers": ["Z"],
        "rational numbers": ["Q"],
        "rationals": ["Q"],
        "real numbers": ["R"],
        "reals": ["R"],
        "complex numbers": ["C"],
        "complexes": ["C"],
        "primes": ["P"],
        "prime numbers": ["P"],
        # Rounding
        "ceiling": ["ceiling"],
        "round up": ["ceiling"],
        "floor": ["floor"],
        "round down": ["floor"],
        "truncate": ["trunc"],
        # Complex
        "real part": ["real"],
        "imaginary part": ["imaginary"],
        "complex conjugate": ["conjugate"],
        "argument": ["argument"],
        "phase": ["argument"],
        # Linear algebra
        "matrix": ["matrix"],
        "vector": ["vector"],
        "determinant": ["determinant"],
        "det": ["determinant"],
        "transpose": ["transpose"],
        "dot product": ["scalarproduct"],
        "scalar product": ["scalarproduct"],
        "inner product": ["scalarproduct"],
        "cross product": ["vectorproduct"],
        "vector product": ["vectorproduct"],
        "outer product": ["outerproduct"],
        # Statistics
        "average": ["mean"],
        "standard deviation": ["sdev"],
        "variance": ["variance"],
        "median": ["median"],
        "mode": ["mode"],
        # Min/Max
        "minimum": ["min"],
        "maximum": ["max"],
        # Combinatorics
        "binomial coefficient": ["binomial"],
        "choose": ["binomial"],
        "n choose k": ["binomial"],
        "combinations": ["binomial"],
        # Intervals
        "open interval": ["interval_oo"],
        "closed interval": ["interval_cc"],
        # Piecewise
        "piecewise function": ["piecewise"],
        "conditional": ["piecewise"],
        # Quantifiers
        "for all": ["forall"],
        "universal": ["forall"],
        "there exists": ["exists"],
        "existential": ["exists"],
        # Vector calculus
        "gradient": ["grad"],
        "divergence": ["divergence"],
        "curl": ["curl"],
        "laplacian": ["Laplacian"],
    }

    index_data = {
        "version": "1.0.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "index": {},
        "aliases": {
            # Mathematical operators
            "+": ["arith1:plus"],
            "-": ["arith1:minus", "arith1:unary_minus"],
            "*": ["arith1:times"],
            "/": ["arith1:divide"],
            "^": ["arith1:power"],
            "**": ["arith1:power"],
            "!": ["integer1:factorial"],
            # Relations
            "=": ["relation1:eq"],
            "==": ["relation1:eq"],
            "!=": ["relation1:neq"],
            "<>": ["relation1:neq"],
            "<": ["relation1:lt"],
            ">": ["relation1:gt"],
            "<=": ["relation1:leq"],
            ">=": ["relation1:geq"],
            "≤": ["relation1:leq"],
            "≥": ["relation1:geq"],
            "≠": ["relation1:neq"],
            "≈": ["relation1:approx"],
            # Logic
            "∧": ["logic1:and"],
            "∨": ["logic1:or"],
            "¬": ["logic1:not"],
            "→": ["logic1:implies"],
            "↔": ["logic1:equivalent"],
            "⊕": ["logic1:xor"],
            # Sets
            "∈": ["set1:in"],
            "∉": ["set1:notin"],
            "⊂": ["set1:prsubset"],
            "⊆": ["set1:subset"],
            "∪": ["set1:union"],
            "∩": ["set1:intersect"],
            "∅": ["set1:emptyset"],
            "×": ["set1:cartesian_product"],
            # Quantifiers
            "∀": ["quant1:forall"],
            "∃": ["quant1:exists"],
            # Constants
            "π": ["nums1:pi"],
            "∞": ["nums1:infinity"],
            # Calculus
            "∂": ["calculus1:partialdiff"],
            "∫": ["calculus1:int"],
            "∇": ["veccalc1:grad"],
        },
        "synonyms": SYNONYMS,
    }

    keyword_map = {}

    # Add keywords from symbol data
    for symbol_id, symbol_data in kb["symbols"].items():
        for keyword in symbol_data.get("keywords", []):
            kw_lower = keyword.lower()
            if kw_lower not in keyword_map:
                keyword_map[kw_lower] = []
            if symbol_id not in keyword_map[kw_lower]:
                keyword_map[kw_lower].append(symbol_id)

    # Add synonyms to keyword map
    for synonym, targets in SYNONYMS.items():
        synonym_lower = synonym.lower()
        for target in targets:
            # Find all symbols that have target as a keyword
            for symbol_id, symbol_data in kb["symbols"].items():
                if target in symbol_data.get("keywords", []) or symbol_data.get("name") == target:
                    if synonym_lower not in keyword_map:
                        keyword_map[synonym_lower] = []
                    if symbol_id not in keyword_map[synonym_lower]:
                        keyword_map[synonym_lower].append(symbol_id)

    index_data["index"] = keyword_map

    # Log synonym additions
    logger.info(f"  - Synonyms added: {len(SYNONYMS)}")
    logger.info(f"  - Unicode aliases: {len(index_data['aliases'])}")

    return index_data


if __name__ == "__main__":
    main()
