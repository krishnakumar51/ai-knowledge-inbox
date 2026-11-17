import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        value = datetime.fromtimestamp(record.created, UTC).astimezone(ZoneInfo("Asia/Kolkata"))
        return value.strftime(datefmt) if datefmt else value.isoformat(timespec="milliseconds")


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ISTFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level.upper(), logging.INFO), handlers=[handler], force=True
    )
