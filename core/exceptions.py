"""Domain-level exceptions with stable machine readable codes."""

from __future__ import annotations


class consulError(Exception):
    """Base class for all application errors."""

    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class ConfigurationError(consulError):
    code = "configuration_error"


class LLMUnavailableError(consulError):
    """Raised when the LLM is not configured or the provider is unreachable."""

    code = "llm_unavailable"


class LLMResponseError(consulError):
    """Raised when the LLM returns something that cannot be validated."""

    code = "llm_response_invalid"


class DocumentExtractionError(consulError):
    code = "document_extraction_failed"


class UnsupportedFileTypeError(DocumentExtractionError):
    code = "unsupported_file_type"


class FileTooLargeError(DocumentExtractionError):
    code = "file_too_large"


class UnsafeURLError(consulError):
    code = "unsafe_url"


class ConnectorError(consulError):
    code = "connector_error"


class ConnectorNotConfiguredError(ConnectorError):
    code = "connector_not_configured"


class RateLimitedError(ConnectorError):
    code = "rate_limited"


class ProfileNotFoundError(consulError):
    code = "profile_not_found"


class JobNotFoundError(consulError):
    code = "job_not_found"


class ValidationFailedError(consulError):
    code = "validation_failed"


class DuplicateApplicationError(consulError):
    """Raised when an application already exists for a job."""

    code = "duplicate_application"


class InvalidStatusError(consulError):
    code = "invalid_status"
