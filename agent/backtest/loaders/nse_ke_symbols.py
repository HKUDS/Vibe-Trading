"""Nairobi Securities Exchange security names -> NSE trading codes.

The NSE daily equity price list identifies each security by its registered
name and ISIN, not by its trading code (SCOM, KCB, ...). This table maps the
trading codes that users type onto the name forms the price list prints, so
``SCOM.NR`` can be found in a list that only says "Safaricom Plc Ord 0.05".

Matching is a prefix test on a normalized name (lower-cased, punctuation turned
into spaces, whitespace collapsed), because the registered name always leads the
security name and the trailing part carries the share class and par value.
Preference shares are excluded from every ordinary-share entry unless the entry
asks for them.

The ISIN is the exact identifier. Pass it directly (``KE0000000281.NR``) to
bypass name matching altogether — the loader accepts either form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NseSecurity:
    """One NSE trading code and the name prefixes that identify it."""

    code: str
    name: str
    prefixes: tuple[str, ...]
    #: Substrings the normalized name must contain (e.g. ``"4%"``).
    requires: tuple[str, ...] = ()
    #: Substrings that disqualify a name (e.g. ``"pref"`` for ordinary shares).
    excludes: tuple[str, ...] = field(default=("pref",))


_SECURITIES: tuple[NseSecurity, ...] = (
    # Banking
    NseSecurity("ABSA", "Absa Bank Kenya", ("absa bank",)),
    NseSecurity("BKG", "BK Group", ("bk group",)),
    NseSecurity("COOP", "Co-operative Bank of Kenya", ("co operative bank", "cooperative bank", "co op bank")),
    NseSecurity("DTK", "Diamond Trust Bank Kenya", ("diamond trust",)),
    NseSecurity("EQTY", "Equity Group Holdings", ("equity group",)),
    NseSecurity("FMLY", "Family Bank", ("family bank",)),
    NseSecurity("HFCK", "HF Group", ("hf group", "hfcb", "housing finance")),
    NseSecurity("IMH", "I&M Group", ("i&m", "i & m", "i and m")),
    NseSecurity("KCB", "KCB Group", ("kcb group",)),
    NseSecurity("NCBA", "NCBA Group", ("ncba",)),
    NseSecurity("SBIC", "Stanbic Holdings", ("stanbic",)),
    NseSecurity("SCBK", "Standard Chartered Bank Kenya", ("standard chartered",)),
    # Insurance & investment
    NseSecurity("BRIT", "Britam Holdings", ("britam",)),
    NseSecurity("CIC", "CIC Insurance Group", ("cic insurance",)),
    NseSecurity("JUB", "Jubilee Holdings", ("jubilee",)),
    NseSecurity("KNRE", "Kenya Re-Insurance Corporation", ("kenya re insurance", "kenya reinsurance", "kenya re ")),
    NseSecurity("LBTY", "Liberty Kenya Holdings", ("liberty kenya",)),
    NseSecurity("SLAM", "Sanlam Allianz Holdings Kenya", ("sanlam",)),
    NseSecurity("CTUM", "Centum Investment Company", ("centum",)),
    NseSecurity("OCH", "Olympia Capital Holdings", ("olympia capital",)),
    NseSecurity("KURV", "Kurwitu Ventures", ("kurwitu",)),
    NseSecurity("NSE", "Nairobi Securities Exchange", ("nairobi securities exchange",)),
    NseSecurity("HAFR", "Home Afrika", ("home afrika",)),
    # Agriculture
    NseSecurity("AMAC", "Africa Mega Agricorp", ("africa mega agricorp", "kenya orchards")),
    NseSecurity("EGAD", "Eaagads", ("eaagads",)),
    NseSecurity("KAPC", "Kapchorua Tea Kenya", ("kapchorua",)),
    NseSecurity("KUKZ", "Kakuzi", ("kakuzi",)),
    NseSecurity("LIMT", "Limuru Tea", ("limuru tea",)),
    NseSecurity("MSC", "Mumias Sugar Company", ("mumias",)),
    NseSecurity("SASN", "Sasini", ("sasini",)),
    NseSecurity("WTK", "Williamson Tea Kenya", ("williamson tea",)),
    # Manufacturing & construction
    NseSecurity("ARM", "ARM Cement", ("arm cement", "athi river mining")),
    NseSecurity("BAMB", "Bamburi Cement", ("bamburi",)),
    NseSecurity("BAT", "British American Tobacco Kenya", ("british american tobacco", "b a t kenya", "bat kenya")),
    NseSecurity("BOC", "BOC Kenya", ("boc kenya",)),
    NseSecurity("CABL", "East African Cables", ("east african cables", "e a cables")),
    NseSecurity("CARB", "Carbacid Investments", ("carbacid",)),
    NseSecurity("CRWN", "Crown Paints Kenya", ("crown paints",)),
    NseSecurity("EABL", "East African Breweries", ("east african breweries", "e a breweries")),
    NseSecurity("EVRD", "Eveready East Africa", ("eveready",)),
    NseSecurity("FTGH", "Flame Tree Group Holdings", ("flame tree",)),
    NseSecurity("PORT", "East African Portland Cement", ("east african portland", "e a portland")),
    NseSecurity("SKL", "Shri Krishana Overseas", ("shri krishana",)),
    NseSecurity("SMER", "Sameer Africa", ("sameer",)),
    NseSecurity("UNGA", "Unga Group", ("unga group",)),
    # Telecommunication, media & commercial services
    NseSecurity("SCOM", "Safaricom", ("safaricom",)),
    NseSecurity("CGEN", "Car & General (Kenya)", ("car & general", "car and general")),
    NseSecurity("DCON", "Deacons (East Africa)", ("deacons",)),
    NseSecurity("HBE", "Homeboyz Entertainment", ("homeboyz",)),
    NseSecurity("LKL", "Longhorn Publishers", ("longhorn",)),
    NseSecurity("NBV", "Nairobi Business Ventures", ("nairobi business ventures",)),
    NseSecurity("NMG", "Nation Media Group", ("nation media",)),
    NseSecurity("SCAN", "WPP Scangroup", ("wpp scangroup", "scangroup")),
    NseSecurity("SGL", "Standard Group", ("standard group",)),
    NseSecurity("TCL", "TransCentury", ("trans century", "transcentury")),
    NseSecurity("TPSE", "TPS Eastern Africa (Serena)", ("tps eastern africa", "tps serena")),
    NseSecurity("UCHM", "Uchumi Supermarket", ("uchumi",)),
    NseSecurity("XPRS", "Express Kenya", ("express kenya",)),
    # Energy & petroleum, transport
    NseSecurity("KEGN", "KenGen", ("kengen", "kenya electricity generating")),
    NseSecurity("KPC", "Kenya Pipeline Company", ("kenya pipeline",)),
    NseSecurity("KPLC", "Kenya Power & Lighting", ("kenya power",), excludes=("pref", "%")),
    NseSecurity("KPLC-P4", "Kenya Power 4% Preference", ("kenya power",), requires=("4%",), excludes=()),
    NseSecurity("KPLC-P7", "Kenya Power 7% Preference", ("kenya power",), requires=("7%",), excludes=()),
    NseSecurity("KQ", "Kenya Airways", ("kenya airways",)),
    NseSecurity("TOTL", "TotalEnergies Marketing Kenya", ("totalenergies", "total kenya")),
    NseSecurity("UMME", "Umeme", ("umeme",)),
    # Exchange-traded funds and REITs
    NseSecurity("GLD", "Absa NewGold ETF", ("absa newgold", "newgold")),
    NseSecurity("SMWF", "Satrix MSCI World Feeder ETF", ("satrix msci world", "satrix")),
    NseSecurity("LAPR", "Laptrust Imara I-REIT", ("laptrust",)),
    NseSecurity("TRFC", "TRIFIC Green USD I-REIT", ("trific",)),
)

#: Codes indexed for lookup. Upper-cased keys.
SECURITIES: dict[str, NseSecurity] = {s.code: s for s in _SECURITIES}

_ISIN_RE = re.compile(r"^KE[0-9A-Z]{10}$")
_PUNCT_RE = re.compile(r"[.,()\-/]+")
_SPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalize a security name for prefix matching.

    ``"E.A.Portland Cement Co. Ltd Ord 5.00"`` -> ``"e a portland cement co ltd ord 5 00"``.
    The ``&`` and ``%`` characters are kept: they distinguish I&M and the
    Kenya Power preference classes.
    """
    text = _PUNCT_RE.sub(" ", (name or "").lower())
    return _SPACE_RE.sub(" ", text).strip() + " "


def is_isin(value: str) -> bool:
    """Return whether *value* is a Kenyan ISIN (``KE`` + ten characters)."""
    return bool(_ISIN_RE.match((value or "").strip().upper()))


def strip_suffix(symbol: str) -> str:
    """``SCOM.NR`` -> ``SCOM``; a code without the suffix is returned upper-cased."""
    code = (symbol or "").strip().upper()
    if code.endswith(".NR"):
        code = code[:-3]
    return code


def code_for_name(name: str) -> Optional[str]:
    """Return the NSE trading code whose name prefixes match *name*.

    Args:
        name: Security name as printed on the NSE daily price list.

    Returns:
        The trading code, or ``None`` when no entry — or more than one — matches.
        An ambiguous name returns ``None`` rather than a guess, so a row is
        dropped instead of being filed under the wrong company.
    """
    norm = normalize_name(name)
    hits = []
    for sec in _SECURITIES:
        if not any(norm.startswith(p) for p in sec.prefixes):
            continue
        if any(req not in norm for req in sec.requires):
            continue
        if any(exc in norm for exc in sec.excludes):
            continue
        hits.append(sec.code)
    return hits[0] if len(hits) == 1 else None
