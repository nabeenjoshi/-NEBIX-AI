# User priority and interruption

- The user's newest direct instruction takes priority over ordinary background work and autonomous plans.
- When a new valid instruction arrives during active work, stop the prior task's cancelable operations before dispatching the new request.
- Use NEBIX's existing cancellation hooks; release held input through the existing action cleanup path. Preserve the interrupted request's state where possible.
- Do not silently continue an interrupted task or resume it unless the user asks or an explicit execution policy permits it.
- Never discard a new instruction merely because another request is in flight. If a capability cannot be interrupted safely, explain the limitation and do not claim that it stopped.
