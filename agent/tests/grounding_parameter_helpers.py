"""Explicit chosen coefficients for derivation fixtures."""


def declared_parameter(value: str, label: str = "Chosen coefficient") -> str:
    """Show a parameter to the reader and declare the same value and label."""
    return f"\n\n{label}: {value}.\n\n```figures\n{value} | count | {label}\n```\n"
