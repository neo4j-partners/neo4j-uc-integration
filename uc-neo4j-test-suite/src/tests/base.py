"""Base classes and types for test infrastructure."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from config import Config


T = TypeVar("T")


class TestStatus(Enum):
    """Test result status."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    INFO = "INFO"
    TIMEOUT = "TIMEOUT"


class TestTimeoutError(Exception):
    """Raised when a test exceeds its timeout."""


@dataclass
class TestResult:
    """Result of a single test execution."""

    name: str
    status: TestStatus
    message: str
    details: dict[str, str] = field(default_factory=dict)

    def print(self) -> None:
        """Print the test result to stdout."""
        status_symbol = {
            TestStatus.PASS: "[PASS]",
            TestStatus.FAIL: "[FAIL]",
            TestStatus.SKIP: "[SKIP]",
            TestStatus.INFO: "[INFO]",
            TestStatus.TIMEOUT: "[TIMEOUT]",
        }[self.status]

        print(f"{status_symbol} {self.message}")

        for key, value in self.details.items():
            print(f"       {key}: {value}")


def with_timeout(timeout_seconds: int) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that adds a timeout to a function.

    Uses ThreadPoolExecutor to avoid SIGALRM issues with Py4J/PySpark.
    The decorated function will raise TestTimeoutError if it exceeds the timeout.

    Args:
        timeout_seconds: Maximum seconds the function can run.

    Returns:
        Decorated function with timeout behavior.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_seconds)
                except FuturesTimeoutError:
                    raise TestTimeoutError(
                        f"Test timed out after {timeout_seconds} seconds"
                    )
        return wrapper
    return decorator


def run_with_timeout(
    func: Callable[..., T],
    timeout_seconds: int,
    *args,
    **kwargs,
) -> T:
    """
    Run a function with a timeout.

    Uses ThreadPoolExecutor to avoid SIGALRM issues with Py4J/PySpark.
    Note: The function continues running in background if timeout occurs,
    but the result is ignored.

    Args:
        func: Function to execute.
        timeout_seconds: Maximum seconds the function can run.
        *args: Positional arguments for func.
        **kwargs: Keyword arguments for func.

    Returns:
        The return value of func.

    Raises:
        TestTimeoutError: If the function exceeds the timeout.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise TestTimeoutError(
                f"Operation timed out after {timeout_seconds} seconds"
            )


class BaseTest(ABC):
    """Base class for all diagnostic tests."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the test."""

    @abstractmethod
    def run(self) -> list[TestResult]:
        """
        Execute the test and return results.

        Returns:
            List of TestResult objects for each check performed.
        """

    def print_header(self) -> None:
        """Print a formatted section header."""
        print("=" * 60)
        print(f"TEST: {self.name}")
        print("=" * 60)
