"""Unit tests for shutdown logging and signal handling in main.

Covers branches in _handle_sig and _setup_signal_handlers to reach 100% coverage.
"""

import signal

import pytest

from app import main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in main.Settings.model_fields:  # type: ignore[attr-defined]
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setitem(main.Settings.model_config, "env_file", None)


def test_handle_signal_logs_with_signal_name(caplog: pytest.LogCaptureFixture) -> None:
    main._setup_signal_handlers()
    handler = signal.getsignal(signal.SIGTERM)
    with caplog.at_level("INFO"):
        handler(signal.SIGTERM, None)
    assert "shutdown signal received" in caplog.text


def test_handle_signal_logs_unknown_when_signals_name_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    main._setup_signal_handlers()

    class BadSignals:
        def __getitem__(self, _signum: int) -> object:
            class X:
                @property
                def name(self) -> str:
                    raise ValueError("boom")

            return X()

    monkeypatch.setattr(signal, "Signals", BadSignals)

    handler = signal.getsignal(signal.SIGTERM)
    with caplog.at_level("INFO"):
        handler(signal.SIGTERM, None)
    assert "UNKNOWN" in caplog.text
    assert "shutdown signal received" in caplog.text


def test_handle_signal_logs_unknown_when_signals_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    main._setup_signal_handlers()
    monkeypatch.delattr(signal, "Signals", raising=False)

    handler = signal.getsignal(signal.SIGTERM)
    with caplog.at_level("INFO"):
        handler(signal.SIGTERM, None)
    assert "UNKNOWN" in caplog.text
    assert "shutdown signal received" in caplog.text


def test_setup_signal_handlers_ignores_sigterm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_signal(sig: int, _handler) -> None:
        if sig == signal.SIGTERM:
            raise ValueError("sigterm not allowed")
        return

    monkeypatch.setattr(signal, "signal", fake_signal)
    main._setup_signal_handlers()


def test_setup_signal_handlers_ignores_sigint_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_signal(sig: int, _handler) -> None:
        if sig == signal.SIGTERM:
            return
        if sig == signal.SIGINT:
            raise AttributeError("sigint not allowed")
        return

    monkeypatch.setattr(signal, "signal", fake_signal)
    main._setup_signal_handlers()
