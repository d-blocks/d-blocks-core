import re
from datetime import datetime, timedelta

from dblocks_core import exc


def parse_duration_since_now(duration: str) -> datetime:
    _delta = parse_duration(duration)
    _now = datetime.now()
    since_dt = (_now - _delta).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return since_dt


def parse_duration(duration: str) -> timedelta:
    duration = duration.strip()
    reg = r"(?:([e\+\-\.\d]+)\s*([a-z]+)[\s\,]*)"

    units = [
        ("y|years?", 31536000),
        ("months?", 2628000),
        ("w|weeks?", 604800),
        ("d|days?", 86400),
        ("h|hours?", 3600),
        ("min(?:ute)?s?", 60),
        ("s|sec(?:ond)?s?", 1),  # spellchecker: disable-line
        ("ms|milliseconds?", 0.001),
        ("us|microseconds?", 0.000001),
    ]

    if not re.fullmatch(reg + "+", duration, flags=re.I):
        raise exc.DParsingError(f"can not parse: {duration}")

    seconds = 0

    for value, unit in re.findall(reg, duration, flags=re.I):
        try:
            value = float(value)
        except ValueError as e:
            raise exc.DParsingError(
                "Invalid float value while parsing duration: '%s'" % value
            ) from e

        try:
            unit = next(u for r, u in units if re.fullmatch(r, unit, flags=re.I))
        except StopIteration:
            raise exc.DParsingError(
                "Invalid unit value while parsing duration: '%s'" % unit
            ) from None

        seconds += value * unit

    return timedelta(seconds=seconds)
