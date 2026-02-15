"""
Sandboxed Code Executor for LLM-Generated Python Code.

Executes Python/SymPy code in a restricted environment with
timeout protection and safety validation.
"""

from __future__ import annotations

import io
import os
import re
import sys
import signal
import logging
import traceback
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Default timeout from environment or fallback
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("EXECUTOR_TIMEOUT_SECONDS", "10"))


class ExecutionTimeout(Exception):
    """Raised when code execution exceeds the timeout."""
    pass


class UnsafeCodeError(Exception):
    """Raised when code contains forbidden patterns."""
    pass


@dataclass
class ExecutionResult:
    """Result of code execution."""

    code: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    error_message: str = ""
    execution_time: float = 0.0

    @property
    def output(self) -> str:
        """Return stdout, or error message if failed."""
        if self.success:
            return self.stdout.strip()
        return self.error_message


class CodeExecutor:
    """Executes Python code in a sandboxed environment."""

    # Allowed imports for mathematical computation
    ALLOWED_IMPORTS = frozenset([
        'sympy',
        'math',
        'numpy',
        'fractions',
        'decimal',
        'cmath',
        'functools',
        'itertools',
        'collections',
        'time',  # For timing operations, low security risk
    ])

    # Forbidden patterns indicating dangerous code
    FORBIDDEN_PATTERNS = [
        r'\bos\.',
        r'\bsubprocess\b',
        r'\bopen\s*\(',
        r'\beval\s*\(',
        r'\bexec\s*\(',
        r'\b__import__\b',
        r'\bimportlib\b',
        r'\bsys\.',
        r'\bbuiltins\b',
        r'\b__builtins__\b',
        r'\bglobals\s*\(',
        r'\blocals\s*\(',
        r'\bcompile\s*\(',
        r'\bgetattr\s*\(',
        r'\bsetattr\s*\(',
        r'\bdelattr\s*\(',
        r'\bfile\b',
        r'\binput\s*\(',
        r'\bbreakpoint\s*\(',
        r'\bpickle\b',
        r'\bsocket\b',
        r'\brequests\b',
        r'\burllib\b',
    ]

    def __init__(self, timeout_seconds: int = 10):
        """
        Initialize the executor.

        Args:
            timeout_seconds: Maximum execution time (default 10s)
        """
        self.timeout_seconds = timeout_seconds
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.FORBIDDEN_PATTERNS
        ]

    def execute(self, code: str) -> ExecutionResult:
        """
        Execute Python code safely.

        Args:
            code: Python code to execute

        Returns:
            ExecutionResult with output and status
        """
        import time
        start_time = time.time()

        result = ExecutionResult(code=code, success=False)

        # Step 1: Validate code safety
        try:
            self._validate_code(code)
        except UnsafeCodeError as e:
            result.error_message = f"Unsafe code detected: {e}"
            logger.warning(f"Blocked unsafe code: {e}")
            return result

        # Step 2: Execute with timeout
        try:
            stdout, stderr, return_val = self._execute_with_timeout(code)
            result.success = True
            result.stdout = stdout
            result.stderr = stderr
            result.return_value = return_val
        except ExecutionTimeout:
            result.error_message = f"Execution timed out after {self.timeout_seconds}s"
            logger.warning(f"Code execution timed out")
        except Exception as e:
            result.error_message = f"Execution error: {type(e).__name__}: {str(e)}"
            result.stderr = traceback.format_exc()
            logger.debug(f"Code execution failed: {e}")

        result.execution_time = time.time() - start_time
        return result

    def _validate_code(self, code: str) -> None:
        """
        Validate that code does not contain forbidden patterns.

        Args:
            code: Python code to validate

        Raises:
            UnsafeCodeError: If forbidden patterns are found
        """
        for pattern in self._compiled_patterns:
            match = pattern.search(code)
            if match:
                raise UnsafeCodeError(f"Forbidden pattern: {match.group()}")

        # Check imports
        self._validate_imports(code)

    def _validate_imports(self, code: str) -> None:
        """
        Validate that only allowed imports are used.

        Args:
            code: Python code to validate

        Raises:
            UnsafeCodeError: If unauthorized imports are found
        """
        # Match import statements
        import_pattern = re.compile(
            r'^\s*(?:from\s+(\w+)|import\s+(\w+))',
            re.MULTILINE
        )

        for match in import_pattern.finditer(code):
            module = match.group(1) or match.group(2)
            # Get root module name
            root_module = module.split('.')[0] if module else None

            if root_module and root_module not in self.ALLOWED_IMPORTS:
                raise UnsafeCodeError(f"Unauthorized import: {root_module}")

    def _execute_with_timeout(self, code: str) -> tuple[str, str, Any]:
        """
        Execute code with timeout protection.

        Args:
            code: Python code to execute

        Returns:
            Tuple of (stdout, stderr, return_value)

        Raises:
            ExecutionTimeout: If execution exceeds timeout
        """
        def timeout_handler(signum, frame):
            raise ExecutionTimeout()

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Set up timeout (Unix only)
        old_handler = None
        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(self.timeout_seconds)
        except (AttributeError, ValueError):
            # signal.SIGALRM not available on Windows
            pass

        try:
            # Create restricted execution environment
            exec_globals = self._create_safe_globals()
            exec_locals = {}

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, exec_globals, exec_locals)

            # Try to find a result variable
            return_value = None
            for var_name in ['result', 'answer', 'output', 'x', 'y', 'solution']:
                if var_name in exec_locals:
                    return_value = exec_locals[var_name]
                    break

            return (
                stdout_capture.getvalue(),
                stderr_capture.getvalue(),
                return_value
            )

        finally:
            # Cancel timeout
            try:
                signal.alarm(0)
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)
            except (AttributeError, ValueError):
                pass

    def _create_safe_globals(self) -> dict[str, Any]:
        """
        Create a restricted globals dictionary for code execution.

        Returns:
            Dictionary with only allowed modules and builtins
        """
        # Create a safe __import__ that only allows whitelisted modules
        allowed = self.ALLOWED_IMPORTS

        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Restricted import that only allows whitelisted modules."""
            root_module = name.split('.')[0]
            if root_module not in allowed:
                raise ImportError(f"Import of '{name}' is not allowed")
            return __builtins__['__import__'](name, globals, locals, fromlist, level)

        safe_globals = {
            '__builtins__': {
                # Safe builtins only
                '__import__': safe_import,
                'abs': abs,
                'all': all,
                'any': any,
                'bin': bin,
                'bool': bool,
                'chr': chr,
                'complex': complex,
                'dict': dict,
                'divmod': divmod,
                'enumerate': enumerate,
                'filter': filter,
                'float': float,
                'format': format,
                'frozenset': frozenset,
                'hex': hex,
                'int': int,
                'isinstance': isinstance,
                'len': len,
                'list': list,
                'map': map,
                'max': max,
                'min': min,
                'oct': oct,
                'ord': ord,
                'pow': pow,
                'print': print,
                'range': range,
                'repr': repr,
                'reversed': reversed,
                'round': round,
                'set': set,
                'slice': slice,
                'sorted': sorted,
                'str': str,
                'sum': sum,
                'tuple': tuple,
                'type': type,
                'zip': zip,
                'True': True,
                'False': False,
                'None': None,
            }
        }

        # Pre-import allowed modules
        try:
            import sympy
            safe_globals['sympy'] = sympy
        except ImportError:
            pass

        try:
            import math
            safe_globals['math'] = math
        except ImportError:
            pass

        try:
            import numpy as np
            safe_globals['numpy'] = np
            safe_globals['np'] = np
        except ImportError:
            pass

        try:
            import fractions
            safe_globals['fractions'] = fractions
            safe_globals['Fraction'] = fractions.Fraction
        except ImportError:
            pass

        try:
            import decimal
            safe_globals['decimal'] = decimal
            safe_globals['Decimal'] = decimal.Decimal
        except ImportError:
            pass

        try:
            import cmath
            safe_globals['cmath'] = cmath
        except ImportError:
            pass

        return safe_globals


def create_executor(timeout_seconds: int | None = None) -> CodeExecutor:
    """
    Factory function to create a code executor.

    Args:
        timeout_seconds: Maximum execution time in seconds.
                         If None, uses EXECUTOR_TIMEOUT_SECONDS from .env (default: 10)

    Returns:
        Configured CodeExecutor instance
    """
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    return CodeExecutor(timeout_seconds=timeout_seconds)
