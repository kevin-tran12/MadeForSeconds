"""TOTP 2FA setup and verification endpoints for the expenses section."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import require_admin
from ..totp import (
    clear_totp_config,
    create_session_token,
    generate_qr_data_uri,
    generate_secret,
    get_totp_config,
    save_totp_config,
    verify_code,
)

router = APIRouter(
    prefix="/api/admin/totp", dependencies=[Depends(require_admin)]
)


class ConfirmSetupRequest(BaseModel):
    secret: str
    code: str


class VerifyRequest(BaseModel):
    code: str


@router.get("/status")
async def totp_status():
    """Check if TOTP has been configured."""
    config = get_totp_config()
    return {"enabled": bool(config and config.get("enabled"))}


@router.post("/setup")
async def totp_setup(request: Request):
    """Generate a new TOTP secret and QR code. Does not persist until confirmed."""
    config = get_totp_config()
    if config and config.get("enabled"):
        raise HTTPException(status_code=400, detail="TOTP is already configured. Reset before reconfiguring.")

    admin_email = getattr(request.state, "admin_email", "admin@madeforseconds.com")
    secret = generate_secret()
    qr_code = generate_qr_data_uri(secret, admin_email)

    return {"secret": secret, "qr_code": qr_code}


@router.post("/confirm-setup")
async def totp_confirm_setup(body: ConfirmSetupRequest, request: Request):
    """Verify a code against the pending secret and finalize setup."""
    if not verify_code(body.secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    save_totp_config(body.secret)

    admin_email = getattr(request.state, "admin_email", "admin@madeforseconds.com")
    token = create_session_token(admin_email)

    return {"enabled": True, "token": token}


@router.post("/verify")
async def totp_verify(body: VerifyRequest, request: Request):
    """Verify a TOTP code and return a session token."""
    config = get_totp_config()
    if not config or not config.get("enabled"):
        raise HTTPException(status_code=400, detail="TOTP is not configured")

    if not verify_code(config["secret"], body.code):
        raise HTTPException(status_code=400, detail="Invalid code")

    admin_email = getattr(request.state, "admin_email", "admin@madeforseconds.com")
    token = create_session_token(admin_email)

    return {"token": token}


@router.post("/reset")
async def totp_reset(body: VerifyRequest):
    """Clear TOTP configuration. Requires a valid code as confirmation."""
    config = get_totp_config()
    if not config or not config.get("enabled"):
        raise HTTPException(status_code=400, detail="TOTP is not configured")

    if not verify_code(config["secret"], body.code):
        raise HTTPException(status_code=400, detail="Invalid code")

    clear_totp_config()
    return {"reset": True}
