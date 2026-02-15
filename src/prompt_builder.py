"""
Prompt Builder for OpenMath-Augmented LLM Prompts.

Composes prompts with retrieved OpenMath definitions based on
experimental condition configurations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

ConditionType = Literal["baseline", "definitions", "openmath", "full_system"]


@dataclass
class PromptConfig:
    """Configuration for a prompt condition."""

    name: str
    description: str
    include_definitions: bool
    include_types: bool
    include_properties: bool
    include_sympy: bool
    include_code_instructions: bool


@dataclass
class ComposedPrompt:
    """A composed prompt ready for LLM inference."""

    condition: str
    system_prompt: str
    user_prompt: str
    problem: str
    retrieved_symbols: list[str]

    def to_messages(self) -> list[dict[str, str]]:
        """Convert to chat message format."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_prompt},
        ]

    def to_single_prompt(self, include_system: bool = True) -> str:
        """Convert to a single string prompt."""
        if include_system:
            return f"{self.system_prompt}\n\n{self.user_prompt}"
        return self.user_prompt


class PromptBuilder:
    """Builds OpenMath-augmented prompts for LLM inference."""

    def __init__(self, templates_path: Path):
        """
        Initialize the prompt builder.

        Args:
            templates_path: Path to templates.yaml
        """
        self.templates_path = templates_path
        self.templates: dict[str, Any] = {}
        self.conditions: dict[str, PromptConfig] = {}
        self.symbol_formats: dict[str, str] = {}
        self.sympy_section: str = ""

        self._load_templates()

    def _load_templates(self) -> None:
        """Load and parse templates from YAML."""
        with open(self.templates_path) as f:
            data = yaml.safe_load(f)

        # Load conditions
        for cond_name, cond_data in data.get("conditions", {}).items():
            self.conditions[cond_name] = PromptConfig(
                name=cond_data["name"],
                description=cond_data["description"],
                include_definitions=cond_data.get("include_definitions", False),
                include_types=cond_data.get("include_types", False),
                include_properties=cond_data.get("include_properties", False),
                include_sympy=cond_data.get("include_sympy", False),
                include_code_instructions=cond_data.get("include_code_instructions", False),
            )

        # Load templates
        self.templates = data.get("templates", {})

        # Load symbol formats
        self.symbol_formats = data.get("symbol_formats", {})

        # Load SymPy section template
        self.sympy_section = data.get("sympy_section", "")

        logger.info(f"Loaded {len(self.conditions)} conditions, {len(self.templates)} templates")

    def build(
        self,
        problem: str,
        symbols: list[dict[str, Any]],
        condition: ConditionType = "full_system",
    ) -> ComposedPrompt:
        """
        Build a complete prompt for the given problem and condition.

        Args:
            problem: The mathematical problem statement
            symbols: List of retrieved OpenMath symbol dicts
            condition: Experimental condition name

        Returns:
            ComposedPrompt ready for LLM inference
        """
        if condition not in self.conditions:
            raise ValueError(f"Unknown condition: {condition}. Available: {list(self.conditions.keys())}")

        config = self.conditions[condition]
        template = self.templates.get(condition, {})

        # Build OpenMath context section
        openmath_context = self._format_symbols(symbols, config)

        # Build SymPy functions section
        sympy_functions = ""
        if config.include_sympy:
            sympy_functions = self._format_sympy_functions(symbols)

        # Build system prompt
        system_template = template.get("system", "")
        system_prompt = system_template.format(
            openmath_context=openmath_context,
            sympy_functions=sympy_functions,
        ).strip()

        # Build user prompt
        user_template = template.get("user", "Problem: {problem}\n\nSolution:")
        user_prompt = user_template.format(problem=problem).strip()

        return ComposedPrompt(
            condition=condition,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            problem=problem,
            retrieved_symbols=[s.get("id", "") for s in symbols],
        )

    def _format_symbols(
        self,
        symbols: list[dict[str, Any]],
        config: PromptConfig,
    ) -> str:
        """
        Format symbols according to the condition configuration.

        Args:
            symbols: List of symbol dicts
            config: Prompt configuration

        Returns:
            Formatted string of symbol definitions
        """
        if not config.include_definitions:
            return ""

        if not symbols:
            return "(No relevant mathematical definitions found.)"

        formatted_symbols = []

        for symbol in symbols:
            formatted = self._format_single_symbol(symbol, config)
            formatted_symbols.append(formatted)

        return "\n\n".join(formatted_symbols)

    def _format_single_symbol(
        self,
        symbol: dict[str, Any],
        config: PromptConfig,
    ) -> str:
        """
        Format a single symbol according to configuration.

        Args:
            symbol: Symbol dict from knowledge base
            config: Prompt configuration

        Returns:
            Formatted symbol string
        """
        symbol_id = symbol.get("id", "unknown")
        description = symbol.get("description", "No description available.")
        type_sig = symbol.get("type_signature", "")
        properties = symbol.get("cmp_properties", [])
        sympy_func = symbol.get("sympy_function", "")

        # Clean up description
        description = " ".join(description.split())

        # Build output based on config
        lines = [f"### {symbol_id}"]
        lines.append(f"**Description:** {description}")

        if config.include_types and type_sig:
            lines.append(f"**Type:** {type_sig}")

        if config.include_properties and properties:
            lines.append("**Properties:**")
            for prop in properties:
                prop_clean = " ".join(prop.split())
                lines.append(f"  - {prop_clean}")

        if config.include_sympy and sympy_func:
            lines.append(f"**SymPy:** `{sympy_func}`")

        return "\n".join(lines)

    def _format_sympy_functions(self, symbols: list[dict[str, Any]]) -> str:
        """
        Format SymPy function references.

        Args:
            symbols: List of symbol dicts

        Returns:
            Formatted SymPy functions section
        """
        functions = []

        for symbol in symbols:
            sympy_func = symbol.get("sympy_function")
            if sympy_func:
                symbol_id = symbol.get("id", "")
                functions.append(f"- `{sympy_func}` ({symbol_id})")

        if not functions:
            return "(No SymPy functions available for retrieved symbols.)"

        function_list = "\n".join(functions)
        return self.sympy_section.format(function_list=function_list)

    def get_available_conditions(self) -> list[str]:
        """Return list of available condition names."""
        return list(self.conditions.keys())

    def get_condition_config(self, condition: str) -> PromptConfig | None:
        """Get configuration for a condition."""
        return self.conditions.get(condition)


def create_prompt_builder(project_root: Path | None = None) -> PromptBuilder:
    """
    Factory function to create a prompt builder with default paths.

    Args:
        project_root: Path to project root (auto-detected if None)

    Returns:
        Configured PromptBuilder instance
    """
    if project_root is None:
        possible_roots = [
            Path.cwd(),
            Path.cwd().parent,
            Path(__file__).parent.parent,
        ]
        for root in possible_roots:
            if (root / "prompts" / "templates.yaml").exists():
                project_root = root
                break

    if project_root is None:
        raise FileNotFoundError("Could not locate project root with prompts/templates.yaml")

    return PromptBuilder(
        templates_path=project_root / "prompts" / "templates.yaml",
    )
