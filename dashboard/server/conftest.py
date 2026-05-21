"""Pytest config — put the server dir on sys.path so `import schemas` works
regardless of the directory pytest is invoked from.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
