"""Parsers for the inconsistent field formats found in the third-party feed."""
import re
from datetime import datetime, timezone

# The feed mixes three order_date representations:
#   1. ISO-8601 with Z suffix        "2026-06-03T20:11:00Z"
#   2. day-first slash dates         "31/10/2025"  (49 of 98 samples have day > 12,
#      so the feed is unambiguously DD/MM/YYYY, not MM/DD/YYYY)
#   3. Unix epoch seconds as string  "1768191660"
_DMY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# Sanity bounds for epoch timestamps: 2000-01-01 .. 2100-01-01. Anything outside
# is more likely a corrupted value than a real order date.
_EPOCH_MIN = 946_684_800
_EPOCH_MAX = 4_102_444_800


def parse_order_date(raw: object) -> tuple[datetime, str]:
    """Parse a feed order_date into an aware UTC datetime.

    Returns (datetime, format_label) where format_label is one of
    "iso8601" | "dmy" | "epoch". Raises ValueError for anything unrecognised.
    """
    if isinstance(raw, bool):
        raise ValueError(f"order_date must be a date, got boolean {raw!r}")

    if isinstance(raw, (int, float)):
        if not _EPOCH_MIN <= float(raw) <= _EPOCH_MAX:
            raise ValueError(f"epoch timestamp {raw!r} outside plausible range")
        return datetime.fromtimestamp(float(raw), tz=timezone.utc), "epoch"

    if isinstance(raw, str):
        value = raw.strip()
        if value.isdigit():
            return parse_order_date(int(value))

        m = _DMY_RE.match(value)
        if m:
            day, month, year = (int(g) for g in m.groups())
            try:
                return datetime(year, month, day, tzinfo=timezone.utc), "dmy"
            except ValueError as exc:
                raise ValueError(f"invalid DD/MM/YYYY date {value!r}: {exc}") from exc

        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"unrecognised order_date format {value!r}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), "iso8601"

    raise ValueError(f"unrecognised order_date type {type(raw).__name__}: {raw!r}")
