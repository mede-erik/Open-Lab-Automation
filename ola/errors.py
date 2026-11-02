"""Transport exceptions. Shared with the native (Rust) module when it is available,
so callers can catch the same classes whichever implementation is in use."""

try:  # pragma: no cover - depends on whether the native module is built
    from ola_native import TransportClosed, TransportError, TransportTimeout
except ImportError:

    class TransportError(Exception):
        """Generic transport failure. Message starts with the [TRN-xxx] code."""

    class TransportTimeout(TransportError):
        """[TRN-003] No (complete) answer within the timeout."""

    class TransportClosed(TransportError):
        """[TRN-004] Connection closed, locally or by the peer."""


__all__ = ["TransportError", "TransportTimeout", "TransportClosed"]
