class AIConfigurationError(Exception):
    """Raised when AI module configuration is invalid."""


class ProviderNotFoundError(Exception):
    """Raised when a requested model provider is not registered."""


class ToolNotFoundError(Exception):
    """Raised when a requested tool is not registered."""
