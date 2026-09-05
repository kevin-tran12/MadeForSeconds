"""OAuth token verification for the MCP resource server.

WorkOS AuthKit is the OAuth 2.1 authorization server: it handles login, consent,
PKCE, and dynamic client registration. This module is the *resource server* side
— it only validates the access tokens WorkOS issues. The MCP SDK calls
``WorkOSTokenVerifier.verify_token`` on every request via the SDK's bearer auth
middleware; returning ``None`` makes the SDK reject the request with a 401 + a compliant
``WWW-Authenticate`` challenge pointing at the protected-resource metadata.

Tokens are WorkOS-signed JWTs verified against the AuthKit JWKS (RS256 only —
``alg: none`` and symmetric algorithms are rejected). Beyond signature and
issuer, three checks bind the token to *this* resource and *this* owner — a
security review flagged their absence as P1: signature + issuer alone only
prove a token came from our AuthKit environment, not that it was issued for
this MCP resource or for the site owner specifically.

  1. Audience (``settings.mcp_audience``) — enforced by default
     (``settings.mcp_enforce_audience``). A token issued for a different
     resource in the same WorkOS environment is rejected.
  2. Owner identity — the token must resolve to an immutable subject
     (``settings.mcp_owner_subject``) or an admin email
     (``settings.admin_email_set``). No fallback: previously, a token with
     no email claim at all was accepted anyway ("relying on WorkOS sign-in
     restriction") — that gap is what let (1) matter less than it should.
  3. Scopes — enforced by the MCP SDK itself via ``AuthSettings.required_scopes``
     (see ``mcp_server.py``), not duplicated here.
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
        audience = settings.mcp_audience
        enforce_audience = settings.mcp_enforce_audience and bool(audience)

        try:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=settings.workos_issuer_url,
                audience=audience if enforce_audience else None,
                options={"verify_aud": enforce_audience, "require": ["exp", "iss"]},
            )
        except jwt.InvalidAudienceError:
            logger.warning(
                "MCP token rejected: audience does not match %r — token was issued for a "
                "different resource",
                audience,
            )
            return None
        except jwt.MissingRequiredClaimError as exc:
            if enforce_audience and exc.args and exc.args[0] == "aud":
                logger.error(
                    "MCP token rejected: no 'aud' claim present, but audience enforcement "
                    "is on (mcp_enforce_audience=true). If WorkOS AuthKit genuinely does not "
                    "emit an audience for this resource, configure one (a custom claim or "
                    "resource indicator) rather than disabling enforcement — see "
                    "docs/DEPLOYMENT.md § MCP token binding."
                )
                return None
            logger.warning("MCP token verification failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning("MCP token verification failed: %s", exc)
            return None

        # Owner identity: an immutable subject match, or an admin email. No
        # fallback-allow — a token satisfying neither is rejected outright.
        subject = claims.get("sub", "")
        email = claims.get("email", "")
        owner_subject = settings.mcp_owner_subject

        is_owner_subject = bool(owner_subject) and subject == owner_subject
        is_admin_email = bool(email) and email in settings.admin_email_set

        if not (is_owner_subject or is_admin_email):
            logger.warning(
                "MCP token rejected: no owner identity matched (sub=%r, email=%r)",
                subject,
                email,
            )
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("client_id") or claims.get("azp") or "workos",
            scopes=_scopes(claims),
            expires_at=claims.get("exp"),
        )
