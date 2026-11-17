from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings


def application_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().app_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("APP_TIMEZONE must be a valid IANA timezone") from exc


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return value.astimezone(UTC)


def as_user_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Stored timestamps must be timezone-aware")
    return value.astimezone(application_timezone())


def parse_import_timestamp(value: str | datetime, *, naive_is_local: bool = True) -> datetime:
    """Parse ISO timestamps; naive historical data is interpreted in the app timezone."""
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Timestamp must not be empty")
        if normalized.endswith(("Z", "z")):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("Timestamp must be valid ISO 8601") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("Timestamp must be an ISO 8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if not naive_is_local:
            raise ValueError("Timestamp must include a timezone offset")
        parsed = parsed.replace(tzinfo=application_timezone())
    return parsed.astimezone(UTC)
