"""Pydantic models representing domain objects for Holy Energy interactions."""

from datetime import datetime

from pydantic import BaseModel, SecretStr


class Credentials(BaseModel):
    """User credentials and session cookie loaded from environment variables."""

    email: str
    password: SecretStr
    shopify_cookie: SecretStr
    timeout: int = 30

    model_config = {"frozen": True}


class ConnectionResult(BaseModel):
    """Outcome of a weekly connection attempt."""

    success: bool
    timestamp: datetime
    message: str

    model_config = {"frozen": True}
