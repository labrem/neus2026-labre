"""
Code and Answer Extractor for LLM Responses.

Extracts Python code blocks and boxed answers from LLM-generated
responses to mathematical problems.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of extracting code and answers from LLM response."""

    response: str
    code_blocks: list[str] = field(default_factory=list)
    boxed_answers: list[str] = field(default_factory=list)
    natural_answers: list[str] = field(default_factory=list)

    @property
    def has_code(self) -> bool:
        """Check if any code blocks were extracted."""
        return len(self.code_blocks) > 0

    @property
    def has_answer(self) -> bool:
        """Check if any answer was extracted."""
        return len(self.boxed_answers) > 0 or len(self.natural_answers) > 0

    @property
    def primary_code(self) -> str | None:
        """Return the first/main code block, or None."""
        return self.code_blocks[0] if self.code_blocks else None

    @property
    def primary_answer(self) -> str | None:
        """Return the most reliable answer (boxed first, then natural)."""
        if self.boxed_answers:
            return self.boxed_answers[-1]  # Last boxed is usually final answer
        if self.natural_answers:
            return self.natural_answers[-1]
        return None

    @property
    def all_candidate_answers(self) -> list[str]:
        """
        Return all candidate answers in priority order.

        Priority: boxed answers (last first) > natural answers (last first)

        This is useful for multi-candidate comparison where the comparator
        can check each candidate against the ground truth.
        """
        candidates = []
        # Add boxed answers in reverse order (last = highest priority)
        for ans in reversed(self.boxed_answers):
            if ans not in candidates:
                candidates.append(ans)
        # Add natural answers in reverse order
        for ans in reversed(self.natural_answers):
            if ans not in candidates:
                candidates.append(ans)
        return candidates


class CodeExtractor:
    """Extracts Python code and answers from LLM responses."""

    # Pattern for Python code blocks (```python ... ```)
    CODE_BLOCK_PATTERN = re.compile(
        r"```python\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE
    )

    # Alternative pattern for code blocks without language specifier
    CODE_BLOCK_GENERIC_PATTERN = re.compile(
        r"```\s*\n(.*?)\n```",
        re.DOTALL
    )

    # Patterns for output blocks that should be SKIPPED (not executed)
    # LLMs often format output as ```output ... ``` which is NOT code
    OUTPUT_BLOCK_PATTERN = re.compile(
        r"```output\s*\n.*?\n```",
        re.DOTALL | re.IGNORECASE
    )

    # Patterns for boxed answers (multiple formats)
    BOXED_PATTERNS = [
        re.compile(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"),  # \boxed{...}
        re.compile(r"\$\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\$"),  # $\boxed{...}$
        re.compile(r"\\\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"),  # \\boxed{...}
    ]

    # Patterns for natural language answers (ordered by reliability)
    # NOTE: These are fallbacks - \boxed{} is always preferred
    NATURAL_ANSWER_PATTERNS = [
        # Direct answer statements - capture expressions, not just numbers
        re.compile(r"(?:the\s+)?(?:final\s+)?answer\s+is[:\s]+\$?([^\n$.]+?)\$?(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:the\s+)?result\s+is[:\s]+\$?([^\n$.]+?)\$?(?:\.|$)", re.IGNORECASE),
        re.compile(r"(?:the\s+)?solution\s+is[:\s]+\$?([^\n$.]+?)\$?(?:\.|$)", re.IGNORECASE),
        # Conclusion statements
        re.compile(r"therefore[,:\s]+(?:the\s+answer\s+is\s+)?([^\n.]+)", re.IGNORECASE),
        re.compile(r"thus[,:\s]+(?:the\s+answer\s+is\s+)?([^\n.]+)", re.IGNORECASE),
        # "simplified form is X" - for algebraic expressions
        re.compile(r"(?:the\s+)?simplified\s+(?:form|expression)\s+is[:\s]+\$?([^\n$.]+?)\$?(?:\.|$)", re.IGNORECASE),
        # Variable value statements: "the value of x is Y"
        re.compile(r"(?:the\s+)?value\s+of\s+\$?[a-zA-Z_]\$?\s+is\s+\$?([^\n.$]+)\$?", re.IGNORECASE),
        # LaTeX assignment after "we get" or "we have": "$x = Y$"
        # Only match when preceded by conclusion phrases to avoid problem statements
        re.compile(r"(?:we\s+(?:get|have|obtain|find)|so)\s+\$[a-zA-Z_]\s*=\s*([^$]+)\$", re.IGNORECASE),
        # Final equation result (at end of line, allowing expressions)
        re.compile(r"=\s*(\d+(?:\.\d+)?)\s*$", re.MULTILINE),
    ]

    # Patterns that match problem statements (to filter out)
    # These help avoid extracting from quoted problem text in the response
    PROBLEM_STATEMENT_INDICATORS = [
        "find the",
        "what is",
        "calculate",
        "simplify",
        "given that",
        "if ",
        "suppose",
    ]

    def __init__(self):
        """Initialize the code extractor."""
        pass

    def extract(self, response: str) -> ExtractionResult:
        """
        Extract code blocks and answers from an LLM response.

        Args:
            response: The full LLM response text

        Returns:
            ExtractionResult with extracted code blocks and answers
        """
        result = ExtractionResult(response=response)

        # Extract Python code blocks
        result.code_blocks = self._extract_code_blocks(response)

        # Extract boxed answers
        result.boxed_answers = self._extract_boxed_answers(response)

        # Extract natural language answers (fallback)
        result.natural_answers = self._extract_natural_answers(response)

        logger.debug(
            f"Extracted {len(result.code_blocks)} code blocks, "
            f"{len(result.boxed_answers)} boxed answers, "
            f"{len(result.natural_answers)} natural answers"
        )

        return result

    def _extract_code_blocks(self, text: str) -> list[str]:
        """
        Extract Python code blocks from text.

        Skips output blocks (```output ... ```) which contain execution
        results, not executable code.

        Args:
            text: Response text

        Returns:
            List of code block contents
        """
        # First, remove output blocks to avoid confusion
        # LLMs often format results as ```output ... ``` which is NOT code
        text_without_output = self.OUTPUT_BLOCK_PATTERN.sub('', text)

        # Try Python-specific blocks
        blocks = self.CODE_BLOCK_PATTERN.findall(text_without_output)

        # If no Python blocks, try generic code blocks that look like Python
        if not blocks:
            generic_blocks = self.CODE_BLOCK_GENERIC_PATTERN.findall(text_without_output)
            # Filter to likely Python code (has import or common Python patterns)
            for block in generic_blocks:
                if self._looks_like_python(block):
                    blocks.append(block)

        # Clean up blocks
        cleaned = []
        for block in blocks:
            block = block.strip()
            if block:
                cleaned.append(block)

        return cleaned

    def _looks_like_python(self, code: str) -> bool:
        """
        Check if a code block looks like Python code.

        Args:
            code: Code block content

        Returns:
            True if likely Python code
        """
        python_indicators = [
            "import ",
            "from ",
            "def ",
            "class ",
            "print(",
            "sympy",
            "numpy",
            "math.",
            "= ",
            "if ",
            "for ",
            "while ",
        ]
        return any(indicator in code for indicator in python_indicators)

    def _extract_boxed_answers(self, text: str) -> list[str]:
        """
        Extract answers from \\boxed{} notation.

        Args:
            text: Response text

        Returns:
            List of boxed answer contents (deduplicated, order preserved)
        """
        answers = []
        seen = set()

        for pattern in self.BOXED_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                cleaned = match.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    answers.append(cleaned)

        return answers

    def _extract_natural_answers(self, text: str) -> list[str]:
        """
        Extract answers from natural language patterns.

        Prioritizes answers from the END of the response (more likely to be
        the final answer) and filters out matches that appear to be from
        quoted problem statements.

        Args:
            text: Response text

        Returns:
            List of extracted answers
        """
        answers_with_position = []

        for pattern in self.NATURAL_ANSWER_PATTERNS:
            for match in pattern.finditer(text):
                answer = match.group(1)
                position = match.start()
                answers_with_position.append((answer, position))

        # Clean up and filter answers
        cleaned = []
        for answer, position in answers_with_position:
            answer = answer.strip()
            # Remove trailing punctuation
            answer = re.sub(r"[.,;:!?]+$", "", answer)
            # Remove surrounding $ signs (LaTeX)
            answer = re.sub(r"^\$+|\$+$", "", answer)
            # Skip empty answers
            if not answer:
                continue
            # Skip if it looks like a problem statement fragment
            if self._looks_like_problem_statement(answer):
                logger.debug(f"Skipping answer '{answer}' - looks like problem statement")
                continue
            cleaned.append((answer, position))

        # Sort by position (later = more likely to be final answer)
        # Return answers in order, but the primary_answer property takes the last one
        cleaned.sort(key=lambda x: x[1])
        return [answer for answer, _ in cleaned]

    def _looks_like_problem_statement(self, text: str) -> bool:
        """
        Check if text looks like it's from a problem statement.

        This helps filter out cases where the LLM quotes the problem
        and we accidentally extract from that quote.

        Args:
            text: Text to check

        Returns:
            True if it looks like a problem statement fragment
        """
        text_lower = text.lower()
        for indicator in self.PROBLEM_STATEMENT_INDICATORS:
            if indicator in text_lower:
                return True
        return False

    def merge_code_blocks(self, blocks: list[str]) -> str:
        """
        Merge multiple code blocks into a single executable script.

        Args:
            blocks: List of code blocks

        Returns:
            Merged code as single string
        """
        if not blocks:
            return ""

        # Combine blocks with newlines
        merged = "\n\n".join(blocks)

        # Deduplicate imports
        merged = self._deduplicate_imports(merged)

        return merged

    def _deduplicate_imports(self, code: str) -> str:
        """
        Remove duplicate import statements from code.

        Args:
            code: Python code with potential duplicate imports

        Returns:
            Code with deduplicated imports
        """
        lines = code.split("\n")
        seen_imports = set()
        result_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                if stripped not in seen_imports:
                    seen_imports.add(stripped)
                    result_lines.append(line)
            else:
                result_lines.append(line)

        return "\n".join(result_lines)


def create_code_extractor() -> CodeExtractor:
    """
    Factory function to create a code extractor.

    Returns:
        Configured CodeExtractor instance
    """
    return CodeExtractor()
