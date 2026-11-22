"""Global swarm option registration."""
from __future__ import annotations
import argparse

def register_global_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--swarm-presets", action="store_true", help="List swarm presets")
    parser.add_argument("--swarm-inspect", metavar="PRESET", help="Inspect a swarm preset without running it")
    parser.add_argument("--swarm-run", nargs="+", metavar=("PRESET", "VARS"), help="Run a swarm preset")
    parser.add_argument("--swarm-list", action="store_true", help="List swarm runs")
    parser.add_argument("--swarm-show", metavar="RUN_ID", help="Show a swarm run")
    parser.add_argument("--swarm-cancel", metavar="RUN_ID", help="Cancel a swarm run")
    parser.add_argument("--swarm-retry", metavar="RUN_ID", help="Retry a prior swarm run")
    parser.add_argument("--swarm-resume", action="store_true", help="Keep completed tasks when retrying a swarm run")
