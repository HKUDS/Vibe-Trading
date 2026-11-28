'Shared CLI paths, exit codes and presentation dependencies.'
from __future__ import annotations
import argparse as argparse
import csv as csv
import json as json
import os as os
import re as re
import shutil as shutil
import signal as signal
import subprocess as subprocess
import sys as sys
import threading as threading
import time as time
import uuid as uuid
from datetime import datetime as datetime
from pathlib import Path as Path
from typing import TYPE_CHECKING as TYPE_CHECKING, Any as Any, Dict as Dict, List as List, Optional as Optional
import warnings as warnings
from rich import box as box
from rich.columns import Columns as Columns
from rich.live import Live as Live
from rich.markup import escape as rich_escape  # noqa: F401 - shared rendering dependency
from rich.panel import Panel as Panel
from rich.prompt import Confirm as Confirm, IntPrompt as IntPrompt, Prompt as Prompt
from rich.syntax import Syntax as Syntax
from rich.table import Table as Table
from rich.text import Text as Text
from cli.theme import get_console as get_console
from src.config.accessor import get_env_config as get_env_config, reset_env_config as reset_env_config
from src.config.paths import get_runs_dir as get_runs_dir, get_sessions_dir as get_sessions_dir, get_swarm_runs_dir as get_swarm_runs_dir, get_uploads_dir as get_uploads_dir
from cli._version import __version__ as _VERSION  # noqa: F401 - command version
from src.providers.registry import setup_choices as setup_choices
from src.config.dotenv import render_env as _render_env_content  # noqa: F401 - setup dependency
from src.memory.persistent import MEMORY_TYPES as MEMORY_TYPES
for _s in ('stdout', 'stderr'):
    _r = getattr(getattr(sys, _s, None), 'reconfigure', None)
    if callable(_r):
        _r(encoding='utf-8', errors='replace')
console = get_console()
AGENT_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = get_runs_dir()
SWARM_DIR = get_swarm_runs_dir()
SESSIONS_DIR = get_sessions_dir()
UPLOADS_DIR = get_uploads_dir()
EXIT_SUCCESS = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE_ERROR = 2
_PORTFOLIO_CLI_MAX_HOLDINGS = 25
RICH_TAG_PATTERN = re.compile('\\[/?[^\\]]+\\]')
SWARM_RUN_USAGE = '--swarm-run PRESET \'{"k":"v"}\''
SWARM_RUN_VARS_PREVIEW_CHARS = 80
if TYPE_CHECKING:
    from src.agent.runtime import AgentRuntime as AgentRuntime
_AGENT_STYLES = ['cyan', 'magenta', 'green', 'yellow', 'blue', 'bright_red', 'bright_cyan', 'bright_magenta']
_agent_color_map: dict[str, str] = {}
_INIT_ENV_PATH = Path.home() / '.vibe-trading' / '.env'
_PROVIDER_CHOICES = setup_choices()
_MEMORY_TYPE_STYLES = {'user': 'cyan', 'feedback': 'yellow', 'project': 'green', 'reference': 'magenta'}
assert set(_MEMORY_TYPE_STYLES) == set(MEMORY_TYPES), f'MEMORY_TYPES vs _MEMORY_TYPE_STYLES drift: types={sorted(MEMORY_TYPES)}, styles={sorted(_MEMORY_TYPE_STYLES)}'
