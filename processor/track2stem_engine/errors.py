class UserFacingError(Exception):
    """A failure whose message is written for users and is safe to return to clients.

    Other exceptions may carry paths or library internals, so adapters should log them and
    return a generic message instead.
    """

    def __init__(self, message):
        super().__init__(message)
        self.public_message = message


class InvalidInputError(UserFacingError, ValueError):
    """Settings, sources or audio that the user can correct."""


class SourceUnavailableError(UserFacingError, RuntimeError):
    """A source that could not be imported, with guidance for the user."""
