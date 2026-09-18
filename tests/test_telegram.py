import json
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from app.cli import partitions
from app.core import telegram


def test_telegram_sends_expected_payload(monkeypatch) -> None:
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        assert timeout == 10
        return BytesIO(b'{"ok": true, "result": {"message_id": 1}}')

    monkeypatch.setattr(telegram, "urlopen", open_request)
    telegram.send_telegram_message("test-token", "-123", "Partition alert")
    assert requests[0].full_url == "https://api.telegram.org/bottest-token/sendMessage"
    assert json.loads(requests[0].data) == {"chat_id": "-123", "text": "Partition alert"}


@pytest.mark.parametrize("body", [b'{"ok": false}', b'not-json', b'[]'])
def test_telegram_rejects_unconfirmed_response(monkeypatch, body) -> None:
    monkeypatch.setattr(telegram, "urlopen", lambda *args, **kwargs: BytesIO(body))
    with pytest.raises(RuntimeError, match="Telegram delivery failed"):
        telegram.send_telegram_message("test-token", "123", "alert")


@pytest.mark.parametrize("error", [
    HTTPError("https://api.telegram.org/botSECRET/sendMessage", 401, "SECRET", {}, None),
    URLError("SECRET"),
])
def test_telegram_errors_do_not_expose_token(monkeypatch, error) -> None:
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(telegram, "urlopen", fail)
    with pytest.raises(RuntimeError) as caught:
        telegram.send_telegram_message("SECRET", "123", "alert")
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__


async def test_notify_uses_telegram_for_recovery(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(partitions, "settings", SimpleNamespace(
        telegram_bot_token=SecretStr("test-token"),
        telegram_chat_id="123",
        partition_alert_webhook_url=None,
    ))
    monkeypatch.setattr(partitions, "send_telegram_message", lambda *args: sent.append(args))
    await partitions._notify("Partition check OK")
    assert sent == [("test-token", "123", "Partition check OK")]


async def test_notify_propagates_failure_for_retry(monkeypatch) -> None:
    monkeypatch.setattr(partitions, "settings", SimpleNamespace(
        telegram_bot_token=SecretStr("test-token"),
        telegram_chat_id="123",
        partition_alert_webhook_url=None,
    ))

    def fail(*args):
        raise RuntimeError("Telegram delivery failed")

    monkeypatch.setattr(partitions, "send_telegram_message", fail)
    with pytest.raises(RuntimeError, match="Telegram delivery failed"):
        await partitions._notify("alert")


async def test_notify_rejects_partial_configuration(monkeypatch) -> None:
    monkeypatch.setattr(partitions, "settings", SimpleNamespace(
        telegram_bot_token=SecretStr("test-token"), telegram_chat_id="",
    ))
    with pytest.raises(RuntimeError, match="Set both"):
        await partitions._notify("alert")
