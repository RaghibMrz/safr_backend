# src/safr_backend/security.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer # For requiring bearer token
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import TokenData
from . import crud, models
from .database import get_db

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hashes a plain password."""
    return pwd_context.hash(password)

# --- JWT Token Handling ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

if not SECRET_KEY:
    raise EnvironmentError("SECRET_KEY environment variable not set. Please define it in your .env file.")

# OAuth2PasswordBearer tells FastAPI where to look for the token (in the Authorization header)
# tokenUrl="token" points to your /token login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token") # Relative to the app root

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a new JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(
    token: str = Depends(oauth2_scheme), # Injects the token from Authorization header
    db: AsyncSession = Depends(get_db)   # Injects DB session
):
    """
    Dependency to get the current authenticated user.
    Verifies the token, then fetches the user from the database.
    To be used in path operations that require authentication.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = await crud.get_user_by_username(db, username=token_data.username)
    if user is None:
        raise credentials_exception # User may have been deleted after token was issued
    return user

async def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    """
    Optional: If you add an `is_active` field to your User model,
    this dependency can check it. For now, it just returns the current_user.
    """
    # if not current_user.is_active: # Example if you add an is_active flag
    #     raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

