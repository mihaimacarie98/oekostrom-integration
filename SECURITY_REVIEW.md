# Security Code Review (2026-04-15)

## Scope
- Reviewed Home Assistant custom integration code under `custom_components/oekostrom`.
- Focused on authentication flow, HTTP transport behavior, secret/token handling, input validation, and logging practices.

## Method
- Manual source review of API, config flow, coordinator, and sensor modules.
- Lightweight pattern checks for dangerous primitives (`eval`, `exec`, unsafe subprocess/file writes, shell usage).
- Sanity compile check for syntax integrity.

## Findings

### 1) Upstream-required MD5 password hashing (Accepted risk)
- **Severity:** Medium (contextual)
- **Location:** `custom_components/oekostrom/api.py`
- The integration hashes the password with MD5 before sending it to the upstream API. This appears required by the remote login contract, but MD5 is cryptographically weak and effectively works as a static password equivalent if replay is possible.
- **Impact:** If traffic were exposed through a compromised TLS endpoint or hostile client environment, the hash could be abused similarly to a password.
- **Recommendation:** Keep TLS-only transport and avoid any local logging/storage of derived hashes. If upstream ever supports stronger auth (challenge/response, OAuth, SRP, or bcrypt/argon2 server-side), migrate promptly.

### 2) Session token in query string to upstream proxy (Inherent protocol risk)
- **Severity:** Medium
- **Location:** `custom_components/oekostrom/api.py`
- Session/login token is passed as a URL query parameter (`token=...`) to the upstream proxy endpoint.
- **Impact:** Query strings are more likely to appear in reverse-proxy logs, analytics, or debugging systems than request bodies/headers.
- **Recommendation:** This is constrained by upstream API design. Maintain HTTPS, avoid intermediary logging, and avoid exposing full request URLs in local logs.

### 3) PII and response text exposure in debug/error logs (Fixed)
- **Severity:** Low
- **Location:** `custom_components/oekostrom/api.py`
- Prior behavior logged the account username in debug logs and included full proxy rejection text in raised exceptions.
- **Impact:** Could leak personally identifiable information and backend internals into logs.
- **Fix applied:**
  - Debug auth log no longer includes username.
  - Proxy rejection exception no longer appends raw backend response body.

## Positive Security Controls Observed
- Endpoint allowlist regex reduces risk of endpoint parameter abuse.
- Explicit request timeout is configured.
- Config flow properly distinguishes auth failures vs connectivity failures.
- Session state is isolated in dedicated `aiohttp` session with cookie jar and explicit close behavior.

## Pattern Check Results
- No usage found of `eval`, `exec`, `os.system`, `subprocess`, `pickle.loads`, or YAML unsafe loaders.

## Overall Assessment
- No critical vulnerabilities identified in the reviewed code.
- Main residual risks are inherited from upstream portal protocol choices (MD5 auth contract and token-in-query pattern).
- Local hardening updates for log hygiene were applied in this review.
