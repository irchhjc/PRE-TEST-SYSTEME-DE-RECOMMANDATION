import logging
import re
import unicodedata
import uuid
from typing import Iterable

import pandas as pd

from config import BRUIT_PATTERNS, SECTEUR_CASSE_MAP, VILLE_NORMALIZE


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("etl")


def clean_whitespace(value):
    if value is None or pd.isna(value):
        return value
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_details_annonce(value: str) -> str:
    if not isinstance(value, str):
        return ""

    text = clean_whitespace(value)
    for pattern in BRUIT_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE | re.DOTALL)
    return clean_whitespace(text) or ""


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _split_multivalue(value: str) -> list[str]:
    if not isinstance(value, str):
        return []

    text = clean_whitespace(value)
    text = re.sub(r"\s+(?:et|ou)\s+", ",", text, flags=re.IGNORECASE)
    parts = re.split(r"[,;|/\n]+", text)
    return [clean_whitespace(part) for part in parts if clean_whitespace(part)]


def _deduplicate_keep_order(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = _strip_accents(value).casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def normalize_ville(value: str) -> list[str]:
    villes = []
    for part in _split_multivalue(value):
        key = part.casefold()
        key_no_accents = _strip_accents(key)
        mapped = (
            VILLE_NORMALIZE.get(key)
            or VILLE_NORMALIZE.get(key_no_accents)
            or part.title()
        )
        if mapped:
            villes.append(mapped)
    return _deduplicate_keep_order(villes)


def normalize_secteurs(value: str) -> list[str]:
    secteurs = []
    for part in _split_multivalue(value):
        key = part.upper()
        mapped = SECTEUR_CASSE_MAP.get(key) or SECTEUR_CASSE_MAP.get(part) or part.title()
        if mapped:
            secteurs.append(mapped)
    return _deduplicate_keep_order(secteurs)


def normalize_skills(value: str) -> list[str]:
    skills = []
    for part in _split_multivalue(value):
        cleaned = clean_whitespace(part)
        if cleaned:
            skills.append(cleaned)
    return _deduplicate_keep_order(skills)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _make_hashable(value):
    if isinstance(value, list):
        return tuple(_make_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _make_hashable(val)) for key, val in value.items()))
    if isinstance(value, set):
        return tuple(sorted(_make_hashable(item) for item in value))
    return value


def _nunique_safe(series: pd.Series) -> int:
    try:
        return int(series.nunique(dropna=True))
    except TypeError:
        normalized = series.dropna().map(_make_hashable)
        return int(normalized.nunique(dropna=True))


def profil_qualite(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    rows = []
    total = len(df)
    for col in df.columns:
        non_null = int(df[col].notna().sum())
        missing = total - non_null
        fill_rate = round((non_null / total * 100), 2) if total else 0.0
        rows.append(
            {
                "dataset": dataset_name,
                "colonne": col,
                "dtype": str(df[col].dtype),
                "non_nuls": non_null,
                "manquants": missing,
                "taux_remplissage": fill_rate,
                "uniques": _nunique_safe(df[col]),
            }
        )
    return pd.DataFrame(rows)


def log_etape(nom: str, df_before: pd.DataFrame, df_after: pd.DataFrame) -> None:
    before = len(df_before)
    after = len(df_after)
    delta = after - before
    log.info(f"{nom}: {before} -> {after} lignes ({delta:+d})")
