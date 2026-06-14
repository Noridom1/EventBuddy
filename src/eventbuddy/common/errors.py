class EventBuddyError(Exception):
    """Base class for domain errors."""


class NotAuthorizedError(EventBuddyError):
    """Caller lacks permission for this event/action."""


class NotFoundError(EventBuddyError):
    """Requested entity does not exist."""


class LLMError(EventBuddyError):
    """An LLM call failed (chat/summarize/vision). Callers degrade gracefully."""
