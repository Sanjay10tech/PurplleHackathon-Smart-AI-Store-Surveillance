"""Application-specific exceptions."""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, *, code: str = "internal_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            f"{resource} not found: {identifier}",
            code="not_found",
        )
        self.resource = resource
        self.identifier = identifier


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="conflict")


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="validation_error")
