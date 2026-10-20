"""Domain exceptions translated into HTTP responses by the app's exception handlers."""

from typing import ClassVar

from fastapi import status


class ForgeError(Exception):
    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    error: ClassVar[str] = "bad_request"
    default_detail: ClassVar[str] = "Bad request"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class BadRequest(ForgeError):
    pass


class Unauthorized(ForgeError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error = "unauthorized"
    default_detail = "Not authenticated"
    headers = {"WWW-Authenticate": "Bearer"}


class PermissionDenied(ForgeError):
    status_code = status.HTTP_403_FORBIDDEN
    error = "forbidden"
    default_detail = "Insufficient permissions"


class NotFound(ForgeError):
    status_code = status.HTTP_404_NOT_FOUND
    error = "not_found"
    default_detail = "Resource not found"


class Conflict(ForgeError):
    status_code = status.HTTP_409_CONFLICT
    error = "conflict"
    default_detail = "Resource conflict"


class BusinessRuleViolation(ForgeError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error = "business_rule_violation"
    default_detail = "Request violates a business rule"


class TooManyRequests(ForgeError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error = "rate_limited"
    default_detail = "Too many requests, slow down"
