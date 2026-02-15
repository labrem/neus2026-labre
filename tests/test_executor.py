"""Unit tests for code executor."""

import pytest


@pytest.fixture
def executor():
    """Create executor instance."""
    from src.executor import create_executor
    return create_executor(timeout_seconds=5)


def test_execute_simple_math(executor):
    """Test execution of simple math code."""
    code = """
result = 2 + 2
print(result)
"""
    result = executor.execute(code)

    assert result.success
    assert "4" in result.output


def test_execute_sympy(executor):
    """Test execution of SymPy code."""
    code = """
import sympy
result = sympy.gcd(48, 18)
print(result)
"""
    result = executor.execute(code)

    assert result.success
    assert "6" in result.output


def test_execute_numpy(executor):
    """Test execution of NumPy code."""
    code = """
import numpy as np
result = np.array([1, 2, 3]).sum()
print(result)
"""
    result = executor.execute(code)

    assert result.success
    assert "6" in result.output


def test_block_os_import(executor):
    """Test that os import is blocked."""
    code = "import os"

    result = executor.execute(code)

    assert not result.success
    assert "Unsafe" in result.error_message or "Unauthorized" in result.error_message


def test_block_os_usage(executor):
    """Test that os.system is blocked."""
    code = "os.system('ls')"

    result = executor.execute(code)

    assert not result.success


def test_block_open(executor):
    """Test that open() is blocked."""
    code = "f = open('/etc/passwd', 'r')"

    result = executor.execute(code)

    assert not result.success


def test_block_eval(executor):
    """Test that eval() is blocked."""
    code = "eval('1+1')"

    result = executor.execute(code)

    assert not result.success


def test_block_subprocess(executor):
    """Test that subprocess is blocked."""
    code = "import subprocess"

    result = executor.execute(code)

    assert not result.success


def test_timeout_protection(executor):
    """Test that infinite loops are stopped."""
    code = """
while True:
    pass
"""
    from src.executor import create_executor
    quick_executor = create_executor(timeout_seconds=1)

    result = quick_executor.execute(code)

    assert not result.success
    assert "timed out" in result.error_message.lower()


def test_return_value_extraction(executor):
    """Test extraction of result variable."""
    code = """
import sympy
result = sympy.factorial(5)
"""
    result = executor.execute(code)

    assert result.success
    assert result.return_value == 120
