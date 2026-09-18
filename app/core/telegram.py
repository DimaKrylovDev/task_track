"""Telegram delivery with sanitized errors (the request URL contains a secret)."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def send_telegram_message(token: str, chat_id: str, message: str) -> None:
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Telegram delivery failed: HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Telegram delivery failed: network error or timeout") from None
    except (ValueError, TypeError):
        raise RuntimeError("Telegram delivery failed: invalid API response") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram delivery failed: API did not confirm success")
