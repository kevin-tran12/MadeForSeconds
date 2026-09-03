"""Reader profile: who am I, what may I ask, how do I cook, and erase what
you keep on me."""

from typing import Literal

import anyio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import UserIdentity, require_user
from ..firestore import get_db
from ..log_redaction import keyed_hash
from ..rate_limit import rate_limit
from ..services import entitlements, users

router = APIRouter(prefix="/api")


class CookingExperienceBody(BaseModel):
    level: Literal["beginner", "home_cook", "confident", "professional"]
    # Accepts a little more than is stored; users.clean_notes normalises and
    # caps it at MAX_EXPERIENCE_NOTES so the reader can paste freely.
    notes: str = Field(default="", max_length=1000)


@router.get("/me", dependencies=[Depends(rate_limit("me", 60, 60))])
async def me(user: UserIdentity = Depends(require_user)) -> dict:
    """The signed-in reader's profile plus their current Sous Chef allowance.

    Only ever returns the caller's own record — there is no lookup by email.
    """
    db = get_db()

    def _load():
        touched = users.touch_user(db, user.uid)
        ent = entitlements.peek_entitlement(db, user.email, user.uid)
        return touched, ent

    # Two Firestore round-trips off the event loop: SSE answers can pin the
    # single instance's loop for seconds at a time, so profile reads must not.
    touched, ent = await anyio.to_thread.run_sync(_load)
    return {
        "email": user.email,
        "is_admin": user.is_admin,
        "supporter": ent.supporter,
        "returning": touched["returning"],
        "answers_total": touched["answers_total"],
        "cooking_experience": touched["cooking_experience"],
        "assistant": ent.to_dict(),
    }


@router.put("/me/experience", dependencies=[Depends(rate_limit("me_experience", 20, 3600))])
async def update_experience(
    body: CookingExperienceBody, user: UserIdentity = Depends(require_user)
) -> dict:
    """Save the reader's cooking experience — the Sous Chef pitches its answers
    to it, and it is remembered on the account until changed or erased."""
    db = get_db()
    result = await anyio.to_thread.run_sync(
        users.set_cooking_experience, db, user.uid, body.level, body.notes
    )
    return {"cooking_experience": result}


@router.delete("/me/data", dependencies=[Depends(rate_limit("me_delete", 5, 3600))])
async def delete_my_data(user: UserIdentity = Depends(require_user)) -> dict:
    """Delete-my-data: the users record, feedback, and supporter uid links."""
    db = get_db()
    result = await anyio.to_thread.run_sync(
        users.delete_user_data, db, user.uid, keyed_hash(user.email)
    )
    return {"deleted": True, **result}
