# ADR-004: WebSocket One-Time Ticket Authentication

## Status

Accepted. Обновлён 2026-09-09: предыдущая редакция описывала проектный
вариант (Redis, `POST /api/v1/accounts/ws-ticket/`, `ws/notifications/`) —
фактическая реализация другая, документ приведён в соответствие с кодом.

## Context

SkladPro.Nod uses Django Channels for real-time chat (`ws/chat/`).
WebSocket connections require authentication, but the standard approach of
passing a JWT access token in the query string has security issues:

1. **Proxy logging**: Reverse proxies (nginx, Cloudflare) and load balancers
   often log query strings. JWT tokens in URLs end up in access logs.
2. **Browser history**: Query parameters may be cached or visible in browser
   history.
3. **Token replay**: A logged JWT in a URL can be replayed by anyone with
   access to the logs.

## Decision

We use a **one-time ticket** system for WebSocket authentication, stored in
the database (not Redis):

### Flow

1. **Client requests a ticket** via HTTP GET to
   `/api/v1/messaging/ws-ticket/` (`apps/messaging/views.py::WsTicketView`):
   ```json
   GET /api/v1/messaging/ws-ticket/
   Authorization: Bearer <access_token>

   Response: { "ticket": "a1b2c3d4e5f6..." }
   ```
   Issuing (`apps/messaging/services.py::issue_ws_ticket`) creates a
   `WsTicket` row (user + company + expiry), prunes expired/used tickets and
   enforces a cap of 5 active tickets per user.

2. **Client connects to WebSocket** with the ticket (NOT the JWT):
   ```
   ws://host/ws/chat/?ticket=a1b2c3d4e5f6...
   ```
   Route: `apps/messaging/routing.py` → `ChatConsumer`.

3. **Server validates the ticket** in `TicketAuthMiddleware`
   (`apps/messaging/ws_auth.py`):
   - Look up the ticket in the `WsTicket` table under `select_for_update`
     (TTL: 60 seconds, `WS_TICKET_TTL_SECONDS` in `apps/messaging/services.py`).
   - If valid: mark `used=True` (one-time use), re-check that the user is
     active, not blocked and belongs to an active-subscription company;
     on failure close the connection.
   - If invalid/expired/used: reject the connection.

4. **Ticket is single-use**: after validation it is marked used in the DB.
   Even if logged, it cannot be replayed. Stale rows are cleaned on every
   issue and by periodic cleanup.

### Why DB instead of Redis (deviation from the original draft)

- The project runs without Redis in development (in-memory channel layer),
   but WebSocket auth must work there too.
- Ticket redemption needs atomic check-and-mark under concurrency; a DB row
   with `select_for_update` gives it without Lua scripts.
- Company/user state (`is_active`, `blocked_by_owner`, subscription) is
   re-validated from the DB at connect time anyway.

## Consequences

- **No JWT in URLs**: Tokens are never logged by proxies or browsers.
- **One-time use**: Even if intercepted, tickets cannot be replayed.
- **Short TTL**: 60-second expiry limits the window of exposure.
- **No extra infrastructure**: Works with and without Redis.
- **Extra HTTP round-trip**: Client must request a ticket before connecting
  WebSocket. Acceptable trade-off for security.
- **Tests**: `apps/messaging/tests_ws_ticket_k.py`,
  `tests_ws_ticket_cleanup_k.py`, `tests_ws_isolation_k.py`.
