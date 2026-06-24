"""Custom exception hierarchy for the Holy Energy Weekly Connection package."""


class HolyEnergyError(Exception):
    """Base exception for all errors raised by this package."""


class AuthenticationError(HolyEnergyError):
    """Raised when login credentials are rejected or the session cannot be established."""


class NetworkError(HolyEnergyError):
    """Raised when an HTTP request fails due to a network-level issue."""


class ConfigurationError(HolyEnergyError):
    """Raised when required environment variables are missing or invalid."""
