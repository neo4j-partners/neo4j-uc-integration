"""
Output formatting helpers for test results.

This module provides consistent formatting for test output including
headers, test names, success/failure indicators, and result summaries.

Output Conventions:
    [TEST]    - Test name and SQL being executed
    ✓ SUCCESS - Test passed
    ✗ ERROR   - Test failed
    [INFO]    - Informational messages
"""

from __future__ import annotations

# Width for header separators
HEADER_WIDTH = 70


def print_header(title: str) -> None:
    """
    Print a prominent section header.

    Creates a visually distinct header with equals-sign borders
    to separate major test sections.

    Args:
        title: Header text to display

    Example Output:
        ======================================================================
         SCHEMA DISCOVERY TESTS
        ======================================================================
    """
    print(f"\n{'=' * HEADER_WIDTH}")
    print(f" {title}")
    print("=" * HEADER_WIDTH)


def print_subheader(title: str) -> None:
    """
    Print a subsection header with dashes.

    Used for grouping related tests within a section.

    Args:
        title: Subheader text to display

    Example Output:
        --- WORKING PATTERNS ---
    """
    print(f"\n--- {title} ---")


def print_test(name: str, sql: str, max_sql_length: int = 80) -> None:
    """
    Print test name and SQL query being executed.

    Long SQL queries are truncated with ellipsis for readability.

    Args:
        name: Descriptive test name
        sql: SQL query string
        max_sql_length: Maximum SQL length before truncation (default: 80)

    Example Output:
        [TEST] COUNT aggregate
          SQL: SELECT COUNT(*) AS flight_count FROM Flight
    """
    truncated = sql[:max_sql_length] + "..." if len(sql) > max_sql_length else sql
    print(f"\n[TEST] {name}")
    print(f"  SQL: {truncated}")


def print_success(message: str = "SUCCESS") -> None:
    """
    Print a success indicator with optional message.

    Args:
        message: Success message (default: "SUCCESS")

    Example Output:
        ✓ SUCCESS - NATURAL JOIN translated to Cypher
    """
    print(f"  ✓ {message}")


def print_error(message: str, max_length: int = 200) -> None:
    """
    Print an error indicator with message.

    Long error messages are truncated for readability.

    Args:
        message: Error message
        max_length: Maximum message length before truncation (default: 200)

    Example Output:
        ✗ ERROR: Connection refused...
    """
    truncated = message[:max_length] + "..." if len(message) > max_length else message
    print(f"  ✗ ERROR: {truncated}")


def print_expected_failure(reason: str) -> None:
    """
    Print indicator for expected/known failure.

    Used when a test is expected to fail due to known limitations.

    Args:
        reason: Explanation of why failure was expected

    Example Output:
        ✓ EXPECTED FAIL: Spark subquery alias issue
    """
    print(f"  ✓ EXPECTED FAIL: {reason}")


def print_unexpected_success() -> None:
    """
    Print indicator when a test expected to fail actually succeeded.

    This indicates the underlying issue may have been fixed.

    Example Output:
        ✓ UNEXPECTED SUCCESS
    """
    print("  ✓ UNEXPECTED SUCCESS")


def print_info(message: str) -> None:
    """
    Print an informational message.

    Used for non-test output like configuration details or summaries.

    Args:
        message: Information to display

    Example Output:
        [INFO] This demonstrates Neo4j JDBC schema discovery
    """
    print(f"[INFO] {message}")


def print_columns(columns: list[tuple[str, str]], indent: int = 4) -> None:
    """
    Print a list of column name/type pairs.

    Args:
        columns: List of (column_name, column_type) tuples
        indent: Number of spaces to indent (default: 4)

    Example Output:
        - aircraft_id: StringType
        - tail_number: StringType
    """
    prefix = " " * indent
    for col_name, col_type in columns:
        print(f"{prefix}- {col_name}: {col_type}")


def print_schema_summary(schemas: dict[str, list[tuple[str, str]]]) -> None:
    """
    Print a summary of discovered schemas.

    Args:
        schemas: Dictionary mapping label names to list of (column, type) tuples

    Example Output:
        Discovered schemas for 5 labels:

          Aircraft:
            Columns: aircraft_id, tail_number, icao24, model, operator...
            Count: 6
    """
    print(f"Discovered schemas for {len(schemas)} labels:\n")

    for label, cols in schemas.items():
        col_names = [c[0] for c in cols]
        # Show first 5 column names, with ellipsis if more
        col_preview = ", ".join(col_names[:5])
        if len(cols) > 5:
            col_preview += "..."

        print(f"  {label}:")
        print(f"    Columns: {col_preview}")
        print(f"    Count: {len(cols)}")
