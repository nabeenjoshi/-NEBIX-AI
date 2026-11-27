from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


class RuntimeTaskState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    INSPECTED = "INSPECTED"
    EXECUTED = "EXECUTED"
    TESTED = "TESTED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


_TRANSITIONS = {
    RuntimeTaskState.NOT_STARTED: {
        RuntimeTaskState.IN_PROGRESS,
        RuntimeTaskState.INSPECTED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.IN_PROGRESS: {
        RuntimeTaskState.INSPECTED,
        RuntimeTaskState.EXECUTED,
        RuntimeTaskState.TESTED,
        RuntimeTaskState.VERIFIED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.INSPECTED: {
        RuntimeTaskState.IN_PROGRESS,
        RuntimeTaskState.EXECUTED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.EXECUTED: {
        RuntimeTaskState.TESTED,
        RuntimeTaskState.VERIFIED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.TESTED: {
        RuntimeTaskState.VERIFIED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.VERIFIED: {
        RuntimeTaskState.COMPLETED,
        RuntimeTaskState.BLOCKED,
        RuntimeTaskState.FAILED,
    },
    RuntimeTaskState.BLOCKED: set(),
    RuntimeTaskState.FAILED: set(),
    RuntimeTaskState.COMPLETED: set(),
}


@dataclass
class ToolTaskEvidence:
    state: RuntimeTaskState = RuntimeTaskState.NOT_STARTED
    evidence: list[str] = field(default_factory=list)

    def transition(self, state: RuntimeTaskState, evidence: str) -> None:
        if state != self.state and state not in _TRANSITIONS[self.state]:
            raise RuntimeError(
                f"Invalid task transition: {self.state.value} -> {state.value}"
            )
        self.state = state
        if evidence:
            self.evidence.append(evidence)

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "evidence": list(self.evidence),
        }


_UNVERIFIED_COMPLETION_CLAIM = re.compile(
    r"\b(?:done|all set|completed successfully|successfully\s+(?:opened|launched|clicked|typed|saved|created|edited|moved|renamed|deleted|installed|updated|sent|published|submitted|changed)|"
    r"i(?:'ve| have)\s+(?:completed|finished|opened|launched|saved|created|edited|moved|renamed|deleted|installed|updated|sent|published|submitted|changed)|"
    r"(?:the|your)\s+.{1,60}\s+(?:is|was)\s+(?:done|complete|completed|sent|published|saved|deleted|installed))\b",
    re.IGNORECASE,
)


def guard_unverified_completion_claim(
    response: str,
    evidence: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> str:
    """Qualify affirmative action-completion claims without verification evidence."""
    text = str(response or "")
    if not text or not _UNVERIFIED_COMPLETION_CLAIM.search(text):
        return text
    relevant = [
        item for item in evidence
        if isinstance(item, dict) and item.get("requires_verification") is True
    ]
    if not relevant:
        return text
    if all(
        item.get("state") in {
            RuntimeTaskState.VERIFIED.value,
            RuntimeTaskState.COMPLETED.value,
        }
        for item in relevant
    ):
        return text
    if "not independently verified" in text.casefold():
        return text
    return (
        text.rstrip()
        + "\n\nNEBIX has not independently verified the requested outcome yet."
    )


def failure_state(result: object) -> RuntimeTaskState | None:
    """Recognize explicit backend failure/block results, not arbitrary output text."""
    text = str(result or "").strip()
    lowered = text.casefold()

    if (
        lowered.startswith("blocked:")
        or lowered.startswith("[confirmation_pending]")
        or lowered.startswith("permission denied")
        or lowered.startswith("screen observation requires")
        or lowered.startswith("computer control requires")
        or lowered.startswith("another action is already waiting")
        or lowered.startswith("an engineering task is already")
        or lowered.startswith("action cancelled")
        or lowered.startswith("action stop requested")
        or lowered.startswith("nebix is shutting down")
        or lowered.startswith("action '") and "' is not available" in lowered
        or lowered.startswith("plugin '") and " is not available" in lowered
        or " plugin is currently disabled" in lowered
    ):
        return RuntimeTaskState.BLOCKED

    if (
        lowered.startswith("tool '") and " failed:" in lowered
        or lowered.startswith("plugin '") and " failed:" in lowered
        or lowered.startswith("sir, the '") and " plugin failed:" in lowered
        or lowered.startswith("unknown tool:")
        or lowered.startswith("search failed")
        or lowered.startswith("project verification was cancelled")
        or lowered.startswith(("error:", "err:", "failed:", "could not ", "unable to ", "cannot "))
        or re.search(r"\b(?:failed|failure|could not|unable to|was not sent|wasn't sent|not completed)\b", lowered)
    ):
        return RuntimeTaskState.FAILED

    return None
