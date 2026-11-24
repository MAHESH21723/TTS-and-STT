"""Exceptions whose messages are safe to show to end users."""


class SpeechError(Exception):
    """An expected failure with a user-presentable message.

    ``status`` is the HTTP status the web layer should answer with.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
