"""Pydantic models representing domain objects for Holy Energy interactions."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Credentials(BaseModel):
    """Configuration and credentials for Holy Energy connection."""

    shopify_cookie: SecretStr = Field(
        ...,
        description="The _shopify_essential session cookie from fr.holy.com",
    )
    email: str = Field(
        default="",
        description="User email (optional helper for verification and logs)",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="HTTP request timeout in seconds",
    )
    cookie_file: Path = Field(
        default=Path("data/cookie.txt"),
        description="Path to persisted rolling cookie file",
    )
    discord_webhook: SecretStr | None = Field(
        default=None,
        description="Optional Discord webhook URL for notifications",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description="Optional Telegram Bot token for notifications",
    )
    telegram_chat_id: str | None = Field(
        default=None,
        description="Optional Telegram chat ID for notifications",
    )
    ntfy_topic: str | None = Field(
        default=None,
        description="Optional ntfy topic name for mobile notifications",
    )
    ntfy_server: str = Field(
        default="https://ntfy.sh",
        description="ntfy server URL",
    )

    model_config = ConfigDict(frozen=True)


class CustomerInfo(BaseModel):
    """Customer authentication tokens extracted from Holy Energy store."""

    customer_id: str
    email: str
    auth_date: str
    mac: str
    shop_token: str

    model_config = ConfigDict(frozen=True)


class ConnectionResult(BaseModel):
    """Outcome of a weekly connection attempt."""

    success: bool
    timestamp: datetime
    points_credited: bool
    points_awarded: int = 0
    total_balance: int = 0
    message: str = ""
    customer_id: str | None = None
    customer_email: str | None = None

    model_config = ConfigDict(frozen=True)
