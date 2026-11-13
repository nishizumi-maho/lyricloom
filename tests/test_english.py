"""LyricLoom's interface is English whatever the Windows display language or regional format."""
import ast
import re
from pathlib import Path

import pytest

from lyricloom import config, setup
from lyricloom.errtext import error_text, message_text, os_error_text
from lyricloom.lyrics.sources import websearch

PACKAGE = Path(__file__).resolve().parent.parent / "lyricloom"


class Runner:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, argv, timeout_s, *, input_bytes=b"", cancel=None):
        self.calls.append(list(argv))
        return self.handler(list(argv))


# --------------------------------------------------------------------------- OS error text


def test_a_localized_windows_error_is_shown_in_english():
    # What Python builds on a Portuguese Windows for a missing program.
    exc = FileNotFoundError(2, "O sistema não pode encontrar o arquivo especificado", "uv.exe", 2)
    text = os_error_text(exc)
    assert text == "[WinError 2] No such file or directory: 'uv.exe'"
    assert "sistema" not in error_text(exc)
    assert error_text(exc).startswith("FileNotFoundError: [WinError 2]")


def test_a_sharing_violation_names_the_real_problem():
    exc = PermissionError(13, "O arquivo já está sendo usado por outro processo", "a.lrc", 32)
    assert os_error_text(exc) == "[WinError 32] The file is being used by another process: 'a.lrc'"


def test_an_unknown_windows_code_never_falls_back_to_the_localized_text():
    exc = OSError(22, "A operação solicitada requer elevação", None, 99999)
    text = os_error_text(exc)
    assert text == "[WinError 99999] Windows could not complete the operation"


def test_both_file_names_of_a_rename_are_kept():
    exc = OSError(13, "Acesso negado", "a.part", 5, "a.lrc")
    assert os_error_text(exc) == "[WinError 5] Access is denied: 'a.part' -> 'a.lrc'"


def test_c_runtime_errors_and_our_own_messages_are_left_alone():
    assert os_error_text(OSError(2, "No such file or directory", "x")) == \
        "[Errno 2] No such file or directory: 'x'"
    assert os_error_text(OSError("the WSL probe is missing")) == "the WSL probe is missing"
    assert message_text(ValueError("bad value")) == "bad value"
    assert error_text(RuntimeError()) == "RuntimeError"


# --------------------------------------------------------------------------- WSL detection


def test_wsl_without_distros_is_detected_on_a_portuguese_windows(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: rf"C:\Windows\System32\{name}")
    message = ("O Subsistema do Windows para Linux não tem distribuições instaladas.\r\n"
               ).encode("utf-16-le")

    def handler(argv):
        if argv == ["wsl.exe", "-l", "-v"]:
            return setup.CommandResult(1, message)
        if argv == ["wsl.exe", "--version"]:
            return setup.CommandResult(0, "Versão do WSL: 2.3.26.0\r\n".encode("utf-16-le"))
        raise AssertionError(argv)

    state = setup._probe_wsl(Runner(handler))
    assert state.installed is True and state.version2 is False and state.error is None


def test_a_missing_wsl_reports_an_english_sentence_with_the_exit_code(monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(setup.shutil, "which", lambda name: rf"C:\Windows\System32\{name}")

    def handler(argv):
        return setup.CommandResult(1, b"", "recurso não instalado".encode("utf-8"))

    state = setup._probe_wsl(Runner(handler))
    assert state.installed is False
    assert state.error.startswith("wsl.exe -l -v failed (exit code 1): ")


# --------------------------------------------------------------------------- web search


@pytest.mark.parametrize("lang, word", [("ja", "歌詞"), ("pt", "letra lyrics"), ("en", "lyrics"),
                                        ("other", "lyrics"), ("ko", "lyrics"), ("", "lyrics")])
def test_the_search_word_follows_the_song_language(lang, word):
    assert websearch.search_word(lang) == word


# --------------------------------------------------------------------------- locale


def test_the_app_formats_numbers_and_dates_in_english():
    from PySide6.QtCore import QDate, QLocale
    from PySide6.QtWidgets import QApplication

    from lyricloom.app.main import apply_english_locale

    app = QApplication.instance() or QApplication([])   # noqa: F841 - Qt needs one
    previous = QLocale()
    try:
        QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil))
        assert QLocale().toString(1.5, "f", 1) == "1,5"
        apply_english_locale()
        assert QLocale().name() == "en_US"
        assert QLocale().toString(1.5, "f", 1) == "1.5"
        assert "November" in QLocale().toString(QDate(2026, 11, 12), "MMMM")
    finally:
        QLocale.setDefault(previous)


# --------------------------------------------------------------------------- source guard

# Words that exist in Portuguese and not in English.  A literal containing one is either a leak
# or one of the documented exceptions below (language data, never interface text).
_PORTUGUESE = re.compile(
    r"\b(não|você|também|está|estão|são|então|uma|isso|esse|essa|arquivo|arquivos|pastas|"
    r"música|músicas|letra|letras|faixa|faixas|erro|aviso|obrigado|legenda|legendas|"
    r"configurações|salvar|abrir|fechar|cancelar|baixar|baixando|aguarde|concluído|falhou|"
    r"nenhum|nenhuma|selecione|escolha|tente|novamente|versão|atualização|pronto|português)\b",
    re.IGNORECASE)

_ALLOWED = {
    # A language name a tag may carry.
    ("probe.py", "português"),
    # Credits Whisper invents at the end of Portuguese audio; they are matched, never shown.
    ("runner.py", "legenda"), ("runner.py", "legendas"), ("runner.py", "obrigado"),
    ("stages/transcribe.py", "legenda"),
    # Credit-line headers found inside lyric pages.
    ("lyrics/clean.py", "letra"), ("lyrics/clean.py", "música"),
    # The query word for Portuguese songs, and the name of a lyrics site.
    ("lyrics/sources/websearch.py", "letra"),
    ("lyrics/score.py", "letras"), ("lyrics/search.py", "letras"),
}


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_portuguese_text_in_the_source():
    leaks = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative.startswith("vendor/"):
            continue
        for line, text in _string_literals(path):
            for match in _PORTUGUESE.finditer(text):
                if (relative, match.group(0).lower()) not in _ALLOWED:
                    leaks.append(f"{relative}:{line}: {match.group(0)!r} in {text[:60]!r}")
    assert not leaks, "Portuguese text in the source:\n" + "\n".join(leaks)
