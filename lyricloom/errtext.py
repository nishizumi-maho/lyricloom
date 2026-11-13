"""English text for the errors LyricLoom shows.

Windows fills ``OSError.strerror`` for a ``WinError`` with ``FormatMessageW``, which answers in the
display language of the system: a Portuguese or Japanese Windows would put that language in the
middle of LyricLoom's English interface.  The C runtime's ``os.strerror`` is always English, and
Python maps every Windows error it knows to an ``errno``, so the text is rebuilt from the codes.
The Windows code stays in the message, because that is what a user can search for.
"""
from __future__ import annotations

import errno
import os

# Windows errors whose errno is too vague to help (Python maps the unknown ones to EINVAL, and
# several different sharing/permission problems to EACCES).
_WINERROR_TEXT = {
    3: "The path was not found",
    5: "Access is denied",
    32: "The file is being used by another process",
    33: "Another process has locked a part of the file",
    80: "The file already exists",
    112: "There is not enough space on the disk",
    123: "The file name, folder name or volume label is not valid",
    145: "The folder is not empty",
    183: "The file already exists",
    193: "The file is not a valid Windows program",
    206: "The file name or extension is too long",
    225: "Windows blocked the file because it contains a virus or unwanted software",
    267: "The folder name is not valid",
    740: "The operation needs administrator rights",
    1223: "The operation was cancelled",
    1314: "The account does not have the required privilege",
    1920: "The file cannot be accessed by the system",
}


def _code_text(number: int | None, winerror: int | None) -> str:
    if winerror is not None:
        known = _WINERROR_TEXT.get(winerror)
        if known:
            return known
        if number not in (None, errno.EINVAL):
            return os.strerror(number)
        return "Windows could not complete the operation"
    return os.strerror(number) if number is not None else ""


def os_error_text(exc: OSError) -> str:
    """The message of ``exc`` in English, whatever the Windows display language.

    Only an error that carries a Windows code is rewritten: its ``strerror`` came from Windows and
    may be localized.  Every other ``OSError`` already has C-runtime (English) text or a message
    written by this program, and is returned unchanged.
    """
    winerror = getattr(exc, "winerror", None)
    if winerror is None:
        return str(exc)
    text = f"[WinError {winerror}] {_code_text(exc.errno, winerror)}"
    names = [repr(str(name)) for name in (exc.filename, exc.filename2) if name is not None]
    if names:
        text += ": " + " -> ".join(names)
    return text


def message_text(exc: BaseException) -> str:
    """The message of any exception, with an ``OSError`` rendered in English."""
    return (os_error_text(exc) if isinstance(exc, OSError) else str(exc)).strip()


def error_text(exc: BaseException) -> str:
    """``Type: message`` for the user, with an ``OSError`` rendered in English."""
    message = message_text(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
