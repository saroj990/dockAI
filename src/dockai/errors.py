"""Domain errors for dockai."""


class DockaiError(Exception):
    """Base error with a user-facing message."""


class DockerUnavailableError(DockaiError):
    """Docker Engine is not reachable or permission was denied."""

    def __init__(self, message: str, *, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


class ContainerNotFoundError(DockaiError):
    """No container matched the requested name or ID."""


class AmbiguousContainerError(DockaiError):
    """More than one container matched the request."""

    def __init__(self, message: str, matches: list[dict]) -> None:
        super().__init__(message)
        self.matches = matches


class ToolCallingUnsupportedError(DockaiError):
    """Ollama model did not return tool_calls when Docker tools were required."""
