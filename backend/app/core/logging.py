"""Logging setup. Log identifiers and counts only - never message or memory content."""
import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


log = logging.getLogger("memora")
