class RefkitError(Exception):
    """An error the user can fix (bad input, missing file, unreachable service). Reported without a traceback."""


class FetchError(RefkitError):
    """A download failed after all retries."""


class NotFound(FetchError):
    """The server answered 404/410: the record does not exist."""
