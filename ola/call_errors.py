"""Errors of the call layer (CALL-001..005).

MINIMAL version written by the transport/executor session so both sessions can build on a
common base; the library/planner session owns this file from now on and may extend or
reshape it. The step executor depends only on ``StepFailedError(call, step_index, cause)``
with ``.code == "CALL-004"``.
"""

from typing import Optional


class CallError(Exception):
    """Base class. ``code`` is the stable ``CALL-xxx`` identifier."""

    code = "CALL-000"

    def __init__(
        self,
        message: str,
        call: Optional[str] = None,
        step_index: Optional[int] = None,
        cause: Optional[BaseException] = None,
    ):
        self.call = call
        self.step_index = step_index
        self.cause = cause
        self.message = message
        super().__init__(f"[{self.code}] {message}")


class CallNotSupportedError(CallError):
    """CALL-001: the call is not defined for this model."""

    code = "CALL-001"


class ValueNotHandledError(CallError):
    """CALL-002: the value is not handled by this model (missing map entry)."""

    code = "CALL-002"


class InvalidArgumentError(CallError):
    """CALL-003: invalid argument (type, enum, range, capability limit)."""

    code = "CALL-003"


class StepFailedError(CallError):
    """CALL-004: a step of the call failed (transport error, bad answer)."""

    code = "CALL-004"

    def __init__(self, call: str, step_index: int, cause: BaseException):
        detail = f"{type(cause).__name__}: {cause}"
        super().__init__(
            f"call '{call}' failed at step {step_index}: {detail}",
            call=call,
            step_index=step_index,
            cause=cause,
        )


class ResponseNotRecognisedError(CallError):
    """CALL-005: the answer could not be interpreted."""

    code = "CALL-005"
