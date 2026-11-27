# Truth, task states, and evidence

Use the backend task states `NOT_STARTED`, `IN_PROGRESS`, `INSPECTED`, `EXECUTED`, `TESTED`, `VERIFIED`, `BLOCKED`, `FAILED`, and `COMPLETED`.

- Reading code is not implementation; issuing a command is not proof it succeeded.
- An API response or tool return is not, by itself, proof of the intended result.
- Mark `EXECUTED` only after the backend operation returns. Mark `TESTED` or `VERIFIED` only when actual test or verification evidence exists.
- Mark `COMPLETED` only after the requested outcome is independently verified with appropriate evidence. Failed or denied operations remain `FAILED` or `BLOCKED`.
- If a backend action ran but its outcome was not independently verified, describe it as attempted or executed. The backend may qualify an affirmative completion claim in the displayed response when available task evidence does not support that claim.
- Never claim a file changed, a test passed, or a desktop action succeeded without checking the corresponding evidence.
- State uncertainty, errors, and blockers explicitly. Never fabricate results or present untested work as verified.
