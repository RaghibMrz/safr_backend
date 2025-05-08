# src/safr_backend/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas, models, security
from ..database import get_db

router = APIRouter(
    prefix="/users", # All routes in this router will start with /users
    tags=["Users"],   # Tag for API documentation
    responses={404: {"description": "Not found"}}, # Default response for this router
)

@router.post("/", response_model=schemas.UserDisplay, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    user: schemas.UserCreate, # Request body will be validated against UserCreate schema
    db: AsyncSession = Depends(get_db) # Dependency injection for DB session
):
    """
    Create a new user.

    - **username**: Unique username for the user.
    - **email**: Unique email for the user.
    - **password**: User's password.
    """
    db_user_by_email = await crud.get_user_by_email(db, email=user.email)
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    db_user_by_username = await crud.get_user_by_username(db, username=user.username)
    if db_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    created_user = await crud.create_user(db=db, user=user)
    return created_user

@router.get("/me", response_model=schemas.UserDisplay)
async def read_users_me(
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Get current logged-in user's details.
    Requires authentication.
    """
    # The current_user object is an instance of models.User,
    # already fetched and validated by the get_current_active_user dependency.
    # FastAPI will automatically convert it to the schemas.UserDisplay response_model.
    return current_user

# You can add more user-related endpoints here later, for example:
# @router.get("/{user_id}", response_model=schemas.UserDisplay)
# async def read_user(user_id: int, db: AsyncSession = Depends(get_db)):
#     db_user = await crud.get_user_by_id(db, user_id=user_id) # Assuming you create get_user_by_id
#     if db_user is None:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
#     return db_user

# @router.get("/", response_model=list[schemas.UserDisplay])
# async def read_users(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
#     users = await crud.get_users(db, skip=skip, limit=limit) # Assuming you create get_users
#     return users
