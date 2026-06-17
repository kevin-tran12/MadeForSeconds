"""OAuth token verification for the MCP resource server.

WorkOS AuthKit is the OAuth 2.1 authorization server: it handles login, consent,
PKCE, and dynamic client registration. This module is the *resource server* side
— it only validates the access tokens WorkOS issues. The MCP SDK calls
``WorkOSTokenVerifier.verify_token`` on every request (via ``BearerAuthBackend``);
returning ``None`` makes the SDK reject the request with a 401 + a compliant
``WWW-Authenticate`` challenge pointing at the protected-resource metadata.

Tokens are WorkOS-signed JWTs verified against the AuthKit JWKS (RS256 only —
``alg: none`` and symmetric algorithms are rejected). Access is gated to the
configured admin emails as defense-in-depth on top of WorkOS-side sign-in
restrictions.
"""

import logging

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import settings

logger = logging.getLogger(__name__)

# Reuse a single JWKS client so signing keys are fetched once and cached.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.workos_jwks_url)
    return _jwks_client


def _scopes(claims: dict) -> list[str]:
    scope = claims.get("scope") or claims.get("scp") or ""
    if isinstance(scope, list):
        return scope
    return [s for s in scope.split(" ") if s]


class WorkOSTokenVerifier(TokenVerifier):
    """Validates WorkOS-issued access tokens for the MCP endpoint."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=settings.workos_issuer_url,
                # WorkOS access-token audiences vary by config; issuer + signature
                # already bind the token to our AuthKit env, and the admin-email
                # gate below restricts who is accepted.
                options={"verify_aud": False, "require": ["exp", "iss"]},
            )
        except Exception as exc:
            logger.warning("MCP token verification failed: %s", exc)
            return None

        # Admin gate: when the token carries an email claim, it must be an admin.
        # If WorkOS is not configured to emit email, fall back to its own
        # sign-in restriction (the env should be locked to the admin user).
        email = claims.get("email", "")
        if email:
            if email not in settings.admin_email_set:
                logger.warning("MCP token rejected: %s is not an admin", email)
                return None
        else:
            logger.warning(
                "MCP token has no email claim; relying on WorkOS sign-in restriction. "
                "Enable an email claim in AuthKit to enforce the admin gate here."
            )

        return AccessToken(
            token=token,
            client_id=claims.get("client_id") or claims.get("azp") or "workos",
            scopes=_scopes(claims),
            expires_at=claims.get("exp"),
        )
