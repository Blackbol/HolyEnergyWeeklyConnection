"""Notification dispatcher supporting Discord, Telegram, and ntfy.sh."""

import logging
from typing import Any

import httpx

from holy_energy_weekly_connection.models import ConnectionResult, Credentials

logger = logging.getLogger(__name__)


def send_notification(
    credentials: Credentials,
    result: ConnectionResult | None = None,
    error: Exception | None = None,
) -> None:
    """Send notification to all configured channels (Discord, Telegram, ntfy)."""
    if not (
        credentials.discord_webhook or credentials.telegram_bot_token or credentials.ntfy_topic
    ):
        return

    if result:
        title = "⚡ Holy Energy — Connexion Hebdomadaire"
        if result.points_credited:
            status_text = f"🎉 **+{result.points_awarded} HOLY Coins crédités !**"
        else:
            status_text = "ℹ️ Points déjà crédités cette semaine."
        body = (
            f"{status_text}\n"
            f"💰 **Solde total :** {result.total_balance} points\n"
            f"👤 **Compte :** {result.customer_email or credentials.email or 'N/A'}\n"
            f"🕒 **Date :** {result.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        is_error = False
    elif error:
        title = "⚠️ Holy Energy — Erreur de connexion"
        body = (
            f"Une erreur est survenue lors de la connexion hebdomadaire :\n"
            f"**Erreur :** `{type(error).__name__}`: {error}\n"
            f"👤 **Compte :** {credentials.email or 'N/A'}\n"
            f"Veuillez vérifier vos identifiants ou renouveler votre cookie de session."
        )
        is_error = True
    else:
        return

    if credentials.discord_webhook:
        _send_discord(credentials.discord_webhook.get_secret_value(), title, body, is_error)

    if credentials.telegram_bot_token and credentials.telegram_chat_id:
        _send_telegram(
            credentials.telegram_bot_token.get_secret_value(),
            credentials.telegram_chat_id,
            f"*{title}*\n\n{body}",
        )

    if credentials.ntfy_topic:
        _send_ntfy(credentials.ntfy_server, credentials.ntfy_topic, title, body, is_error)


def _send_discord(webhook_url: str, title: str, description: str, is_error: bool) -> None:
    try:
        color = 0xE02424 if is_error else 0x10B981
        payload: dict[str, Any] = {
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                }
            ]
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.debug("Discord notification sent successfully.")
    except Exception as exc:
        logger.warning("Failed to send Discord notification: %s", exc)


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
        logger.debug("Telegram notification sent successfully.")
    except Exception as exc:
        logger.warning("Failed to send Telegram notification: %s", exc)


def _send_ntfy(server: str, topic: str, title: str, body: str, is_error: bool) -> None:
    try:
        url = f"{server.rstrip('/')}/{topic}"
        clean_title = "Holy Energy - Erreur" if is_error else "Holy Energy - Succes"
        headers = {
            "Title": clean_title,
            "Priority": "high" if is_error else "default",
            "Tags": "warning" if is_error else "tada,zap",
        }
        full_body = f"{title}\n\n{body}"
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, content=full_body.encode("utf-8"), headers=headers)
            resp.raise_for_status()
        logger.debug("ntfy notification sent successfully.")
    except Exception as exc:
        logger.warning("Failed to send ntfy notification: %s", exc)
