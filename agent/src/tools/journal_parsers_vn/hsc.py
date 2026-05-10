"""HSC broker journal parser — STUB (Sprint 2.2 Phase 2).

Implementation pending. detect() returns False so this stub does not
falsely match any real journal file during Phase 1.
"""

from __future__ import annotations

import pandas as pd

from src.tools.journal_parsers_vn import register_vn_parser


class HSCParser:
    name = "hsc"

    def detect(self, df: pd.DataFrame) -> bool:
        return False  # stub — Phase 2 will fill in

    def parse(self, df: pd.DataFrame) -> list:
        raise NotImplementedError("Sprint 2.2 Phase 2: HSCParser.parse()")


register_vn_parser(HSCParser())
