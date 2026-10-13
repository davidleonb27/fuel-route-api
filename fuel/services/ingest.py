import csv
import io
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from .names import normalize_state

CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
PRICE_QUANTUM = Decimal("0.0001")
# Anything outside this is a data-entry error rather than an expensive pump.
MIN_PLAUSIBLE_PRICE = Decimal("0.50")
MAX_PLAUSIBLE_PRICE = Decimal("15.00")

# Canonical field -> accepted header spellings (compared case/space/punctuation-insensitively).
HEADER_ALIASES = {
    "opis_id": {"opistruckstopid", "opisid", "truckstopid", "id", "stationid"},
    "name": {"truckstopname", "name", "stationname"},
    "address": {"address", "streetaddress"},
    "city": {"city"},
    "state": {"state", "st", "statecode"},
    "rack_id": {"rackid", "rack"},
    "price": {"retailprice", "price", "priceperg", "pricepergallon"},
}
REQUIRED = ("opis_id", "name", "city", "state", "price")


class IngestError(Exception):
    pass


@dataclass
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int | None
    price: Decimal
    price_min: Decimal
    price_max: Decimal
    observations: int


@dataclass
class IngestReport:
    rows_read: int = 0
    rows_accepted: int = 0
    skipped: Counter = field(default_factory=Counter)
    non_us_rows: Counter = field(default_factory=Counter)
    duplicate_ids: int = 0
    duplicate_ids_with_price_conflict: int = 0
    max_duplicate_price_spread: Decimal = Decimal(0)
    names_reconciled: int = 0
    text_repaired: int = 0
    price_outliers: list[tuple[int, str, Decimal]] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            f"rows read: {self.rows_read}, accepted: {self.rows_accepted}",
            f"duplicate station ids: {self.duplicate_ids} "
            f"({self.duplicate_ids_with_price_conflict} with conflicting prices, "
            f"max spread ${self.max_duplicate_price_spread}); price = median of observations",
            f"names reconciled across duplicates: {self.names_reconciled}",
            f"text fields repaired (mojibake): {self.text_repaired}",
        ]
        if self.non_us_rows:
            out.append(f"non-US rows excluded: {dict(self.non_us_rows)}")
        for reason, count in sorted(self.skipped.items()):
            out.append(f"skipped ({reason}): {count}")
        if self.price_outliers:
            sample = ", ".join(f"#{i} {n} ${p}" for i, n, p in self.price_outliers[:5])
            out.append(f"price outliers kept (> Q3 + 3*IQR): {len(self.price_outliers)}: {sample}")
        return out


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    mapping = {}
    for raw in fieldnames:
        key = _header_key(raw or "")
        for canonical, aliases in HEADER_ALIASES.items():
            if key in aliases and canonical not in mapping:
                mapping[canonical] = raw
    missing = [name for name in REQUIRED if name not in mapping]
    if missing:
        raise IngestError(f"CSV is missing required columns: {missing}. Found: {fieldnames}")
    return mapping


def repair_text(value: str) -> tuple[str, bool]:
    """Undo UTF-8 read as cp1252 ('Stuckeyâ€™s' -> 'Stuckey’s') and collapse whitespace."""
    cleaned = " ".join(value.split())
    if any(marker in cleaned for marker in ("â€", "Ã", "Â")):
        try:
            fixed = cleaned.encode("cp1252").decode("utf-8")
            return fixed, fixed != cleaned
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return cleaned, False


def display_city(value: str) -> str:
    return value.title() if value.isupper() or value.islower() else value


def parse_price(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace("$", "").replace(" ", "")
    if cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")  # "3,459" written with a decimal comma
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_fuel_csv(source: Path | str | bytes) -> tuple[list[StationRecord], IngestReport]:
    if isinstance(source, Path):
        text = decode_bytes(source.read_bytes())
    elif isinstance(source, bytes):
        text = decode_bytes(source)
    else:
        text = source
    if not text.strip():
        raise IngestError("CSV is empty")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = _map_headers(reader.fieldnames or [])

    report = IngestReport()
    observations: dict[int, list[dict]] = defaultdict(list)

    for raw in reader:
        if not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
            continue
        report.rows_read += 1

        def get(name: str, row: dict = raw) -> str:
            value = row.get(columns[name]) if name in columns else ""
            return value if isinstance(value, str) else ""

        id_text = get("opis_id").strip()
        if not id_text.isdigit():
            report.skipped["invalid station id"] += 1
            continue
        price = parse_price(get("price"))
        if price is None:
            report.skipped["unparseable price"] += 1
            continue
        if not MIN_PLAUSIBLE_PRICE <= price <= MAX_PLAUSIBLE_PRICE:
            report.skipped["implausible price"] += 1
            continue

        state_raw = get("state").strip().upper()
        state = normalize_state(state_raw)
        if state is None:
            if state_raw in CANADIAN_PROVINCES:
                report.non_us_rows[state_raw] += 1
            else:
                report.skipped["unknown state"] += 1
            continue

        city, city_fixed = repair_text(get("city"))
        if not city:
            report.skipped["missing city"] += 1
            continue
        name, name_fixed = repair_text(get("name"))
        address, address_fixed = repair_text(get("address"))
        report.text_repaired += city_fixed + name_fixed + address_fixed
        rack = get("rack_id").strip()

        observations[int(id_text)].append(
            {
                "name": name or f"Truck stop {id_text}",
                "address": address,
                "city": display_city(city),
                "state": state,
                "rack_id": int(rack) if rack.isdigit() else None,
                "price": price,
            }
        )
        report.rows_accepted += 1

    records = [_merge(opis_id, rows, report) for opis_id, rows in observations.items()]
    _flag_outliers(records, report)
    return records, report


def _merge(opis_id: int, rows: list[dict], report: IngestReport) -> StationRecord:
    prices = sorted(row["price"] for row in rows)
    if len(rows) > 1:
        report.duplicate_ids += 1
        spread = prices[-1] - prices[0]
        if spread:
            report.duplicate_ids_with_price_conflict += 1
            report.max_duplicate_price_spread = max(report.max_duplicate_price_spread, spread)
        if len({row["name"] for row in rows}) > 1:
            report.names_reconciled += 1

    # Most common value wins; ties go to the first row seen.
    def mode(key: str):
        return Counter(row[key] for row in rows).most_common(1)[0][0]

    return StationRecord(
        opis_id=opis_id,
        name=mode("name"),
        address=mode("address"),
        city=mode("city"),
        state=mode("state"),
        rack_id=mode("rack_id"),
        price=Decimal(statistics.median(prices)).quantize(PRICE_QUANTUM, ROUND_HALF_UP),
        price_min=prices[0].quantize(PRICE_QUANTUM, ROUND_HALF_UP),
        price_max=prices[-1].quantize(PRICE_QUANTUM, ROUND_HALF_UP),
        observations=len(rows),
    )


def _flag_outliers(records: list[StationRecord], report: IngestReport) -> None:
    if len(records) < 8:
        return
    quartiles = statistics.quantiles([r.price for r in records], n=4)
    ceiling = quartiles[2] + 3 * (quartiles[2] - quartiles[0])
    report.price_outliers = sorted(
        ((r.opis_id, r.name, r.price) for r in records if r.price > ceiling),
        key=lambda item: -item[2],
    )
