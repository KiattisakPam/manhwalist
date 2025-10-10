from fastapi import APIRouter, Depends
from schemas import User
from config import settings
import auth

router = APIRouter(
    prefix="/settings",
    tags=["Settings"],
    dependencies=[Depends(auth.get_current_employer_user)]
)

@router.get("/invitation-code")
async def get_invitation_code():
    """
    Returns the current invitation code. Requires employer authentication.
    """
    return {"invitation_code": settings.INVITATION_CODE}

