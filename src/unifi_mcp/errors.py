from enum import StrEnum


class ErrorCategory(StrEnum):
    CONNECTION_ERROR = "CONNECTION_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    PRODUCT_UNAVAILABLE = "PRODUCT_UNAVAILABLE"
    FIRMWARE_UNSUPPORTED = "FIRMWARE_UNSUPPORTED"
    UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"


_STATUS_MAP: dict[int, ErrorCategory] = {
    400: ErrorCategory.VALIDATION_ERROR,
    401: ErrorCategory.AUTH_ERROR,
    403: ErrorCategory.AUTH_ERROR,
    404: ErrorCategory.NOT_FOUND,
    409: ErrorCategory.CONFLICT,
}


def status_to_category(status_code: int) -> ErrorCategory | None:
    """Map HTTP status code to an error category. Returns None for unmapped codes."""
    return _STATUS_MAP.get(status_code)


class UnifiError(Exception):
    """Structured error for UniFi API failures."""

    def __init__(self, category: ErrorCategory, message: str, endpoint: str | None = None):
        self.category = category
        self.message = message
        self.endpoint = endpoint
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"[{self.category}] {self.message}"

    def to_dict(self) -> dict:
        result = {
            "error": True,
            "category": str(self.category),
            "message": self.message,
        }
        if self.endpoint:
            result["endpoint"] = self.endpoint
        return result
