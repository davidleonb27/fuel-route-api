import re
import unicodedata

US_STATES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}

_LSAD_SUFFIX = re.compile(
    r"\s+(city and borough|consolidated government|metropolitan government|metro government|"
    r"unified government|urban county|city|town|village|borough|cdp|municipality|comunidad|"
    r"zona urbana|township|plantation|ccd|gore|grant|location|purchase|reservation|"
    r"unorganized territory|precinct|district|census subarea)$"
)
_TOKEN_ALIASES = {"saint": "st", "sainte": "ste", "fort": "ft", "mount": "mt"}


def _ascii_lower(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return folded.lower()


def normalize_place_name(name: str, strip_census_suffix: bool = False) -> str:
    # Census names carry a legal suffix ("Kansas City city"); stripping it from user
    # input would eat real words, so it is opt-in.
    text = _ascii_lower(name).replace("(balance)", "").strip()
    if strip_census_suffix:
        text = _LSAD_SUFFIX.sub("", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [_TOKEN_ALIASES.get(token, token) for token in text.split()]
    return " ".join(tokens)


def normalize_state(value: str) -> str | None:
    cleaned = _ascii_lower(value).strip().strip(".")
    if len(cleaned) == 2 and cleaned.upper() in US_STATES:
        return cleaned.upper()
    return _STATE_BY_NAME.get(cleaned)
