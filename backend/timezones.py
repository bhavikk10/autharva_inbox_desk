"""Validated IANA zones; Windows names are mapped by tzlocal, never fixed offsets."""
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_timezone(name):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('Choose a valid IANA timezone, such as Asia/Kolkata or America/New_York.') from None
    return name


def system_timezone():
    explicit=os.getenv('APP_TIMEZONE','').strip()
    if explicit:return validate_timezone(explicit)
    from tzlocal import get_localzone_name
    return validate_timezone(get_localzone_name())
