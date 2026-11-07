"""Errors raised by the dependency-light ReefPose core."""


class ReefPoseError(Exception):
    """Base class for ReefPose runtime failures."""


class ReefPoseValidationError(ReefPoseError, ValueError):
    """Raised when a ReefPose artifact or request violates its contract."""


class ReefPoseCancelledError(ReefPoseError):
    """Raised after a cooperative training cancellation request."""

