"""Domain exceptions translated by the API layer."""


class ReefVisionError(Exception):
    """Base exception for expected domain failures."""


class NotFoundError(ReefVisionError):
    """Requested entity does not exist."""


class ConflictError(ReefVisionError):
    """Requested operation conflicts with existing data."""


class ValidationError(ReefVisionError):
    """Requested operation violates a domain rule."""


class WorkflowExecutionCancelled(ReefVisionError):
    """A workflow child operation was cancelled by the user."""


class CatalogResourceError(ReefVisionError):
    """Bundled catalog resource could not be loaded or validated."""

    def __init__(self, message: str, *, details: dict[str, object]) -> None:
        super().__init__(message)
        self.details = details
