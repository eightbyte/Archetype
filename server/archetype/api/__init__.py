"""The HTTP surface: the ``/api`` router, its wire shapes, and the error envelope (P1-5)."""

from .errors import ApiError, ErrorBody, ErrorResponse, install_error_handlers
from .routes import router

__all__ = [
    "ApiError",
    "ErrorBody",
    "ErrorResponse",
    "install_error_handlers",
    "router",
]
