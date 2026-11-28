"""Domain exceptions translated by the API layer."""


class ReefVisionError(Exception):
    """Base exception for expected domain failures."""


class NotFoundError(ReefVisionError):
    """Requested entity does not exist."""


class ConflictError(ReefVisionError):
    """Requested operation conflicts with existing data."""


class ValidationError(ReefVisionError):
    """Requested operation violates a domain rule."""


class CheckpointApprovalRequired(ValidationError):
    """A legacy checkpoint needs file-specific approval before loading."""

    def __init__(self, filename: str, sha256: str) -> None:
        super().__init__(f"Review the source of {filename} before loading this legacy checkpoint.")
        self.filename = filename
        self.sha256 = sha256


class StorageCapacityError(ReefVisionError):
    """The database or managed storage ran out of space during a request."""


class WorkflowExecutionCancelled(ReefVisionError):
    """A workflow child operation was cancelled by the user."""


class CatalogResourceError(ReefVisionError):
    """Bundled catalog resource could not be loaded or validated."""

    def __init__(self, message: str, *, details: dict[str, object]) -> None:
        super().__init__(message)
        self.details = details
