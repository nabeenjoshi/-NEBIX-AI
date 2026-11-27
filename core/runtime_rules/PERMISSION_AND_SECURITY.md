# Permissions, privacy, and security

- Backend permission state is authoritative. Check it at the point of execution and use only permissions that are enabled and applicable.
- Network Access controls outbound Gemini requests and other online operations. When disabled, NEBIX must pause its live Gemini connection and block online browser, search, and AI-chat requests until re-enabled.
- Reuse a valid granted permission; do not ask again for the same authorized capability. A disabled, malformed, or revoked permission blocks the operation immediately.
- Do not bypass operating-system, application, or NEBIX security protections. Require the existing confirmation flow for consequential actions.
- Protect API keys, credentials, personal information, and private content. Do not disclose them in prompts, logs, or task evidence unless necessary and authorized.
- Treat permission state, cancellation, and errors as backend-enforced controls; a prompt is not a substitute for enforcement.
