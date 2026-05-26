"""Pytest config — put dashboard/server on sys.path so `import schemas` works."""
import sys
from pathlib import Path

# dashboard/server/ is the parent of the tests/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
