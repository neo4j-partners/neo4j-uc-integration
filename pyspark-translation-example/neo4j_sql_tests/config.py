"""
Configuration management for Neo4j JDBC tests.

This module handles loading environment variables and constructing
the JDBC connection URL with appropriate parameters.

Environment Variables:
    NEO4J_URI       - Neo4j connection URI (e.g., neo4j+s://xxx.databases.neo4j.io)
    NEO4J_DATABASE  - Database name (default: "neo4j")
    NEO4J_USERNAME  - Neo4j username
    NEO4J_PASSWORD  - Neo4j password
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """
    Configuration container for Neo4j JDBC connection.

    Attributes:
        uri: Neo4j connection URI (e.g., neo4j+s://host)
        database: Neo4j database name
        username: Authentication username
        password: Authentication password
        jar_path: Path to Neo4j JDBC driver JAR file
        jdbc_url: Constructed JDBC URL with SQL translation enabled
    """
    uri: str
    database: str
    username: str
    password: str
    jar_path: Path

    @property
    def jdbc_url(self) -> str:
        """
        Construct JDBC URL with SQL translation enabled.

        The enableSQLTranslation=true parameter activates the Neo4j JDBC
        driver's SQL-to-Cypher translation feature.

        Returns:
            JDBC connection URL string
        """
        return f"jdbc:{self.uri}:7687/{self.database}?enableSQLTranslation=true"

    def validate(self) -> list[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.uri:
            errors.append("NEO4J_URI is required")
        if not self.username:
            errors.append("NEO4J_USERNAME is required")
        if not self.password:
            errors.append("NEO4J_PASSWORD is required")
        if not self.jar_path.exists():
            errors.append(f"JDBC JAR not found at {self.jar_path}")

        return errors


def load_config(env_path: Path | None = None) -> Config:
    """
    Load configuration from environment variables.

    Args:
        env_path: Optional path to .env file. If None, looks for .env
                  in the pyspark-translation-example directory.

    Returns:
        Config object with loaded values

    Example:
        config = load_config()
        if errors := config.validate():
            for error in errors:
                print(f"ERROR: {error}")
            return
    """
    # Determine .env file location
    if env_path is None:
        # Look for .env relative to this module's package
        package_dir = Path(__file__).parent.parent
        env_path = package_dir / ".env"

    # Load environment variables from .env file
    load_dotenv(env_path)

    # Get values from environment
    uri = os.getenv("NEO4J_URI", "")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    username = os.getenv("NEO4J_USERNAME", "")
    password = os.getenv("NEO4J_PASSWORD", "")

    # Determine JAR path (same directory as .env)
    jar_path = env_path.parent / "neo4j-jdbc-full-bundle-6.0.0.jar"

    return Config(
        uri=uri,
        database=database,
        username=username,
        password=password,
        jar_path=jar_path,
    )


def print_jar_download_instructions():
    """Print instructions for downloading the JDBC JAR."""
    print("Download the Neo4j JDBC driver with:")
    print('  curl -L -o neo4j-jdbc-full-bundle-6.0.0.jar \\')
    print('    "https://repo1.maven.org/maven2/org/neo4j/neo4j-jdbc-full-bundle/6.0.0/neo4j-jdbc-full-bundle-6.0.0.jar"')
