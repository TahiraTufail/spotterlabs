"""Offline "City, ST" lookup backed by stations/data/us_cities.csv (built from GeoNames)."""
import csv
import re
from functools import lru_cache
from pathlib import Path

CITY_INDEX_PATH = Path(__file__).parent / "data" / "us_cities.csv"

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)

_ABBREVIATIONS = {"st": "saint", "mt": "mount", "ft": "fort"}
_QUERY_RE = re.compile(r"^(.*?)[,\s]+([A-Za-z]{2})\s*$")


def normalize_place(text: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("'", "")).split()
    if tokens and tokens[0] in _ABBREVIATIONS:
        tokens[0] = _ABBREVIATIONS[tokens[0]]
    return " ".join(tokens)


def parse_place_query(text: str):
    """"Dallas, TX" or "dallas tx" -> ("dallas", "TX"); None when no valid state is present."""
    match = _QUERY_RE.match(text.strip())
    if not match:
        return None
    state = match.group(2).upper()
    name = normalize_place(match.group(1))
    if state not in US_STATES or not name:
        return None
    return name, state


@lru_cache(maxsize=1)
def _load_index():
    if not CITY_INDEX_PATH.exists():
        return {}
    with open(CITY_INDEX_PATH, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)  # header: name,state,lat,lng
        return {(name, state): (float(lat), float(lng)) for name, state, lat, lng in reader}


def lookup_city(city: str, state: str):
    """Return (lat, lng) for a city or None. The index keeps the most populous match per name."""
    return _load_index().get((normalize_place(city), state.strip().upper()))
