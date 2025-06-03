from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta

from .. import crud, schemas, security
from ..database import get_db

router = APIRouter(
    tags=["Authentication"],
)

@router.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Logs in a user and returns an access token.

    Expects form data with "username" and "password".
    """
    user = await crud.authenticate_user(
        db, username=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ACCESS_TOKEN_EXPIRE_MINUTES is handled in security.create_access_token
    # If you wanted to override it here for some reason, you could calculate a timedelta
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    access_token = security.create_access_token(
        data={"sub": user.username} # "sub" is a standard JWT claim for the subject (user)
        # expires_delta=access_token_expires # Only if overriding default expiry
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Placeholder for other auth-related endpoints if needed in the future
# e.g., /password-recovery, /reset-password, etc.
