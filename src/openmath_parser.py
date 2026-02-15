"""
OpenMath Content Dictionary and Small Type System Parser.

This module parses OpenMath .ocd (Content Dictionary) and .sts (Small Type System)
files into structured Python dictionaries for building a mathematical knowledge base.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CDMetadata:
    """Metadata for a Content Dictionary."""
    name: str
    url: str | None = None
    description: str | None = None
    status: str | None = None
    version: str | None = None
    revision: str | None = None
    date: str | None = None


@dataclass
class Symbol:
    """A mathematical symbol definition from a Content Dictionary."""
    id: str  # Format: "cd:name" (e.g., "arith1:gcd")
    cd: str  # Content Dictionary name
    name: str  # Symbol name
    role: str | None = None  # "application", "binder", etc.
    description: str | None = None
    type_signature: str | None = None  # Human-readable type
    type_signature_raw: str | None = None  # Raw XML
    cmp_properties: list[str] = field(default_factory=list)
    fmp_count: int = 0
    examples: list[str] = field(default_factory=list)
    sympy_function: str | None = None
    sympy_signature: str | None = None
    keywords: list[str] = field(default_factory=list)


class OpenMathParser:
    """Parser for OpenMath Content Dictionary and STS files."""

    NAMESPACES = {
        "cd": "http://www.openmath.org/OpenMathCD",
        "sts": "http://www.openmath.org/OpenMathCDS",
        "om": "http://www.openmath.org/OpenMath",
    }

    def __init__(self, cds_dir: Path, include_experimental: bool = False):
        """
        Initialize the parser.

        Args:
            cds_dir: Path to the openmath-cds directory
            include_experimental: If True, also parse CDs from experimental directory
        """
        self.cds_dir = cds_dir
        self.ocd_dir = cds_dir / "cd" / "Official"
        self.experimental_dir = cds_dir / "cd" / "experimental"
        self.sts_dir = cds_dir / "sts"
        self.include_experimental = include_experimental

    def parse_all(self) -> dict[str, Any]:
        """
        Parse all Content Dictionaries and STS files.

        Returns:
            Complete knowledge base dictionary
        """
        logger.info(f"Parsing all CDs from {self.ocd_dir}")

        knowledge_base = {
            "version": "1.0.0",
            "source": "OpenMath Content Dictionaries",
            "content_dictionaries": {},
            "symbols": {},
        }

        # Find all .ocd files from Official directory
        ocd_files = list(self.ocd_dir.glob("*.ocd"))
        logger.info(f"Found {len(ocd_files)} Official Content Dictionaries")

        # Add experimental CDs if requested
        if self.include_experimental and self.experimental_dir.exists():
            experimental_files = list(self.experimental_dir.glob("*.ocd"))
            logger.info(f"Found {len(experimental_files)} Experimental Content Dictionaries")
            ocd_files.extend(experimental_files)

        logger.info(f"Total: {len(ocd_files)} Content Dictionaries to parse")

        for ocd_file in ocd_files:
            try:
                metadata, symbols = self.parse_ocd_file(ocd_file)
                
                # Add metadata to KB
                knowledge_base["content_dictionaries"][metadata.name] = asdict(metadata)

                # Parse corresponding STS file if it exists
                sts_file = self.sts_dir / f"{metadata.name}.sts"
                type_signatures = {}
                if sts_file.exists():
                    try:
                        type_signatures = self.parse_sts_file(sts_file)
                    except Exception as e:
                        logger.error(f"Error parsing STS file {sts_file}: {e}")

                # Process symbols
                for symbol in symbols:
                    # Enrich with type signature if available
                    if symbol.name in type_signatures:
                        symbol.type_signature = type_signatures[symbol.name]
                    
                    # Store in KB
                    knowledge_base["symbols"][symbol.id] = asdict(symbol)
                    
            except Exception as e:
                logger.error(f"Error processing {ocd_file}: {e}")

        logger.info(f"Parsed {len(knowledge_base['symbols'])} symbols total")
        return knowledge_base

    def parse_ocd_file(self, file_path: Path) -> tuple[CDMetadata, list[Symbol]]:
        """
        Parse a single .ocd file.

        Args:
            file_path: Path to the .ocd file

        Returns:
            Tuple of (metadata, list of symbols)
        """
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Extract metadata
        cd_data = {
            "name": self._get_text(root, "CDName", "cd"),
            "url": self._get_text(root, "CDURL", "cd"),
            "description": self._get_text(root, "Description", "cd"),
            "status": self._get_text(root, "CDStatus", "cd"),
            "version": self._get_text(root, "CDVersion", "cd"),
            "revision": self._get_text(root, "CDRevision", "cd"),
            "date": self._get_text(root, "CDDate", "cd"),
        }
        
        # Determine CD name (fallback to filename stem if not in XML)
        if not cd_data["name"]:
            cd_data["name"] = file_path.stem
            
        metadata = CDMetadata(**cd_data)
        
        symbols = []
        # Try both namespaced and non-namespaced just in case
        definitions = root.findall("cd:CDDefinition", self.NAMESPACES)
        if not definitions:
            definitions = root.findall("CDDefinition")

        for defn in definitions:
            symbol = self._parse_cd_definition(defn, metadata.name)
            if symbol:
                symbols.append(symbol)
                
        return metadata, symbols

    def parse_sts_file(self, file_path: Path) -> dict[str, str]:
        """
        Parse a single .sts file.

        Args:
            file_path: Path to the .sts file

        Returns:
            Dictionary mapping symbol names to type signatures
        """
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError:
            logger.warning(f"Failed to parse STS XML: {file_path}")
            return {}
        
        signatures = {}
        
        # Try to find signatures using various strategies
        # 1. Namespaced CDSignatures/Signature
        found_signatures = root.findall(".//sts:Signature", self.NAMESPACES)
        
        # 2. Try non-namespaced
        if not found_signatures:
            found_signatures = root.findall(".//Signature")
            
        # 3. Some files call it CDSignature?
        if not found_signatures:
            found_signatures = root.findall(".//sts:CDSignature", self.NAMESPACES)
        if not found_signatures:
            found_signatures = root.findall(".//CDSignature")
            
        for sig in found_signatures:
            name = sig.get("name")
            if name:
                signatures[name] = self._parse_signature(sig)
                
        return signatures

    def _parse_cd_definition(self, element: ET.Element, cd_name: str) -> Symbol | None:
        """Parse a CDDefinition element into a Symbol."""
        name = self._get_text(element, "Name", "cd")
        if not name:
            return None
            
        symbol = Symbol(
            id=f"{cd_name}:{name}",
            cd=cd_name,
            name=name,
            role=self._get_text(element, "Role", "cd"),
            description=self._get_text(element, "Description", "cd"),
            cmp_properties=self._parse_cmp(element),
            fmp_count=len(element.findall("cd:FMP", self.NAMESPACES) or element.findall("FMP")),
            examples=self._parse_examples(element),
        )
        symbol.keywords = self._extract_keywords(symbol)
        
        return symbol

    def _parse_cmp(self, element: ET.Element) -> list[str]:
        """Extract all CMP text from a CDDefinition."""
        properties = []
        # Try namespaced CMP
        cmps = element.findall("cd:CMP", self.NAMESPACES)
        if not cmps:
            cmps = element.findall("CMP")
            
        for cmp_elem in cmps:
            if cmp_elem.text:
                # Clean up whitespace
                text = " ".join(cmp_elem.text.split())
                properties.append(text)
        return properties

    def _parse_examples(self, element: ET.Element) -> list[str]:
        """Extract examples."""
        examples = []
        # Try namespaced Example
        exs = element.findall("cd:Example", self.NAMESPACES)
        if not exs:
            exs = element.findall("Example")
            
        for example in exs:
            text = "".join(example.itertext()).strip()
            if not text:
                 text = ET.tostring(example, encoding="unicode").strip()
            
            if text:
                examples.append(" ".join(text.split())) # Normalize whitespace
        return examples

    def _parse_signature(self, element: ET.Element) -> str:
        """
        Convert STS signature XML to human-readable string.
        """
        # Find OMOBJ inside the signature
        omobj = element.find("om:OMOBJ", self.NAMESPACES)
        if omobj is None:
            # Maybe it uses default namespace without prefix in this context?
            # Or try searching by local name logic if namespace differs
            omobj = element.find("OMOBJ") 
            if omobj is None:
                # Fallback: search for any child with tag ending in OMOBJ
                for child in element:
                    if child.tag.endswith("OMOBJ"):
                        omobj = child
                        break
            
        if omobj is None:
            return ""

        return self._sts_to_string(omobj)

    def _sts_to_string(self, element: ET.Element) -> str:
        """Recursively convert STS XML to string representation."""
        # Get tag name without namespace
        tag = element.tag.split('}')[-1]

        if tag == "OMS":
            return element.get("name", "?")
        elif tag == "OMV":
            return element.get("name", "?")
        elif tag == "OMA":
            children = list(element)
            if not children:
                return ""
            op = self._sts_to_string(children[0])
            args = [self._sts_to_string(c) for c in children[1:]]

            if op == "mapsto":
                # Function type: inputs -> output
                if len(args) >= 2:
                    inputs = ", ".join(args[:-1])
                    output = args[-1]
                    if len(args) > 2:
                        return f"({inputs}) -> {output}"
                    return f"{inputs} -> {output}"
                elif len(args) == 1:
                     return f"-> {args[0]}"
            elif op in ("nassoc", "nary"):
                # N-ary operator
                if len(args) == 1:
                     return f"{op}({args[0]})"
                return f"{op}({', '.join(args)})"

            return f"{op}({', '.join(args)})"
        elif tag == "OMOBJ":
            children = list(element)
            if children:
                return self._sts_to_string(children[0])

        return ""

    # Comprehensive stopwords for keyword extraction
    # These are common English words that appear in symbol descriptions
    # but are not discriminative for retrieval. Using a minimal set leads
    # to index pollution where words like "used", "indicate", "first" map
    # to hundreds of symbols, degrading retrieval precision.
    #
    # Phase 6i Update: Added missing verb forms and reference noise words
    # identified from index analysis (words mapping to 15+ symbols).
    PARSER_STOP_WORDS = {
        # Core articles/determiners
        "a", "an", "the", "this", "that", "these", "those",
        # Common verbs (all forms)
        "is", "are", "was", "were", "be", "been", "being",
        "has", "have", "had", "do", "does", "did",
        "find", "calculate", "compute", "solve", "determine", "evaluate",
        "show", "prove", "verify", "check", "get", "give", "let",
        "takes", "express", "answer", "write", "put", "simplify",
        # Phase 6i: Added missing verb forms
        "applied", "applying", "applies",
        "representing", "represented",
        "denote", "denotes", "denoted", "denoting",
        "specify", "specifying", "specified",
        "described", "describing", "describes",
        "evaluated", "evaluating", "evaluates",
        "construct", "constructs", "constructed", "constructing",
        "consists", "consisting",
        "intended", "intending",
        "corresponds", "corresponding",
        # Prepositions
        "of", "in", "to", "for", "with", "on", "at", "by", "from",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "over",
        # Conjunctions
        "and", "or", "but", "if", "then", "when", "while", "although",
        # Pronouns
        "it", "its", "they", "their", "we", "our", "you", "your",
        "he", "she", "him", "her", "his",
        # Question words
        "what", "which", "who", "whom", "whose", "where", "how", "why",
        # Other common words
        "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "any", "only", "own", "same", "so", "than",
        "too", "very", "just", "also", "now", "here", "there",
        "can", "will", "shall", "may", "might", "must", "should", "would", "could",
        "about", "as", "like", "using", "given", "following", "use",
        # OpenMath description noise words (appear frequently but non-discriminative)
        "symbol", "represent", "represents", "function", "return", "returns",
        "denotes", "used", "defined", "element", "object",
        "argument", "arguments", "result", "type", "called", "name", "list", "apply",
        "first", "second", "third", "last", "next", "new", "old",
        "number", "numbers", "value", "values", "form", "many", "much",
        "indicates", "indicate", "contains", "specifies", "provides",
        "one", "two", "three", "true", "false", "case", "cases",
        "default", "usually", "typically", "either", "whether", "not",
        # Phase 6i: Added reference/documentation noise words
        "standard", "section", "note", "notes", "fact", "facts",
        "abramowitz", "stegun",  # Textbook reference appearing in many descriptions
        "openmath",  # Meta reference, not mathematical content
        "example", "examples",
        "see", "chapter", "page", "definition", "definitions",
        "reference", "references", "refer", "refers",
        "similar", "way", "ways", "manner",
        "particular", "general", "specific", "certain",
        # Single letters (often internal references in descriptions)
        "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
        "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    }

    def _extract_keywords(self, symbol: Symbol) -> list[str]:
        """Extract searchable keywords from a symbol.

        Phase 6i Enhancement: Now extracts keywords from both Description
        and CMP (Commented Mathematical Properties) fields. CMPs contain
        important mathematical terms like 'factorial', 'integral',
        'differentiate' that aren't always in the description.
        """
        keywords = set()

        # Add name (always include the symbol name)
        if symbol.name:
            keywords.add(symbol.name.lower())

        # Helper to extract keywords from text
        def extract_from_text(text: str) -> None:
            words = text.lower().split()
            for word in words:
                # Remove punctuation
                clean_word = "".join(c for c in word if c.isalnum())
                if len(clean_word) > 2 and clean_word not in self.PARSER_STOP_WORDS:
                    keywords.add(clean_word)

        # Add words from description (filtered by comprehensive stopwords)
        if symbol.description:
            extract_from_text(symbol.description)

        # Phase 6i: Also extract keywords from CMP properties
        # CMPs contain valuable mathematical terms (e.g., "factorial",
        # "integral", "differentiate", "compose") that aid retrieval
        if symbol.cmp_properties:
            for cmp in symbol.cmp_properties:
                extract_from_text(cmp)

        return list(keywords)
        
    def _get_text(self, element: ET.Element, tag: str, ns_prefix: str = None) -> Optional[str]:
        """Get text content of a child element, handling namespaces."""
        # Try with namespace if prefix provided
        if ns_prefix:
            child = element.find(f"{ns_prefix}:{tag}", self.NAMESPACES)
            if child is not None and child.text:
                return child.text.strip()
                
        # Try without namespace (fallback)
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
            
        return None
