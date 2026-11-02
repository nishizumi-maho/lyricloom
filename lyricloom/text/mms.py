import re

_NOT_MMS = re.compile(r"[^a-z']")


def to_mms_tokens(reading: str) -> str:
    """Keeps only the characters in the MMS forced-alignment dictionary (a-z and ')."""
    return _NOT_MMS.sub("", reading.lower())
