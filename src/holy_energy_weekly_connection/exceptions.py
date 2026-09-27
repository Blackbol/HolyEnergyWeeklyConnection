"""Custom exception hierarchy for the Holy Energy Weekly Connection package."""


class HolyEnergyError(Exception):
    """Base exception for all errors raised by this package."""


class AuthenticationError(HolyEnergyError):
    """Raised when session cookie has expired, is invalid, or customer is not authenticated."""


class NetworkError(HolyEnergyError):
    """Raised when an HTTP or network request fails."""


class ConfigurationError(HolyEnergyError):
    """Raised when required environment variables or configurations are missing or invalid."""


class LoyaltyLionError(HolyEnergyError):
    """Raised when the LoyaltyLion API returns an unexpected error or format."""
