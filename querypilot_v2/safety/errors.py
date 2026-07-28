class UnsafeQueryError(Exception):
    """Raised by any safety layer. Message is always a clean, user-facing
    sentence — never a stack trace — since the API returns str(exc) directly."""
