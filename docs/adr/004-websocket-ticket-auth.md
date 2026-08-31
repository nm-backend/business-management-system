# ADR-004: WebSocket One-Time Ticket Authentication

## Status

Accepted

## Context

SkladPro.Nod uses Django Channels for real-time notifications (chat messages, work status updates, order changes). WebSocket connections require authentication, but the standard approach of passing a JWT access token in the query string has security issues:

1. **Proxy logging**: Reverse proxies (nginx, Cloudflare) and load balancers often log query strings. JWT tokens in URLs end up in access logs.
2. **Browser history**: Query parameters may be cached or visible in browser history.
3. **Token replay**: A logged JWT in a URL can be replayed by anyone with access to the logs.

## Decision

We use a **one-time ticket** system for WebSocket authentication:

### Flow

1. **Client requests a ticket** via HTTP POST to `/api/v1/accounts/ws-ticket/`:
   ```json
   POST /api/v1/accounts/ws-ticket/
   Authorization: Bearer <access_token>
   
   Response: { "ticket": "a1b2c3d4e5f6...", "expires_in": 30 }
   ```

2. **Client connects to WebSocket** with the ticket (NOT the JWT):
   ```
   ws://host/ws/notifications/?ticket=a1b2c3d4e5f6...
   ```

3. **Server validates the ticket** in `TicketAuthMiddleware`:
   - Look up ticket in Redis (TTL: 30 seconds)
   - If valid: delete from Redis (one-time use), authenticate the user
   - If invalid/expired: reject with 4401

4. **Ticket is single-use**: After validation, it's deleted from Redis. Even if logged, it cannot be replayed.

### Implementation

```python
# apps/accounts/ticket_auth.py
class TicketAuthMiddleware:
    async def __call__(self, scope, receive, send):
        ticket = parse_qs(scope['query_string'].decode()).get('ticket', [None])[0]
        if not ticket:
            await send_close(send, code=4401)
            return
        user_id = await self.channel_layer.group_get(f'ws_ticket:{ticket}')
        if not user_id:
            await send_close(send, code=4401)
            return
        await self.channel_layer.group_discard(f'ws_ticket:{ticket}', ...)
        scope['user'] = await get_user(user_id)
        return await self.app(scope, receive, send)
```

## Consequences

- **No JWT in URLs**: Tokens are never logged by proxies or browsers.
- **One-time use**: Even if intercepted, tickets cannot be replayed.
- **Short TTL**: 30-second expiry limits the window of exposure.
- **Redis dependency**: Tickets require Redis (already used for channel layer).
- **Extra HTTP round-trip**: Client must request ticket before connecting WebSocket. Acceptable trade-off for security.
