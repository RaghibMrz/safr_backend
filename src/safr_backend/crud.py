# src/safr_backend/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select 

from . import models
from . import schemas
from .security import get_password_hash, verify_password

# --- User CRUD ---

async def get_user_by_email(db: AsyncSession, email: str) -> models.User | None:
    """
    Retrieves a user from the database by their email address.

    Args:
        db: The asynchronous database session.
        email: The email address of the user to retrieve.

    Returns:
        The User model instance if found, otherwise None.
    """
    result = await db.execute(select(models.User).filter(models.User.email == email))
    return result.scalars().first()

async def get_user_by_username(db: AsyncSession, username: str) -> models.User | None:
    """
    Retrieves a user from the database by their username.

    Args:
        db: The asynchronous database session.
        username: The username of the user to retrieve.

    Returns:
        The User model instance if found, otherwise None.
    """
    result = await db.execute(select(models.User).filter(models.User.username == username))
    return result.scalars().first()

async def create_user(db: AsyncSession, user: schemas.UserCreate) -> models.User:
    """
    Creates a new user in the database.

    Args:
        db: The asynchronous database session.
        user: The user creation data (from Pydantic schema).

    Returns:
        The newly created User model instance.
    """
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user) # Refresh to get DB-generated values like id, created_at
    return db_user

async def authenticate_user(db: AsyncSession, username: str, password: str) -> models.User | None:
    """
    Authenticates a user by checking username and password.

    Args:
        db: The asynchronous database session.
        username: The username to authenticate.
        password: The plain text password to verify.

    Returns:
        The User model instance if authentication is successful, otherwise None.
    """
    db_user = await get_user_by_username(db, username=username)
    if not db_user:
        return None # User not found
    if not verify_password(password, db_user.hashed_password):
        return None # Incorrect password
    return db_user


# Placeholder for future CRUD functions:

# --- City CRUD ---
# async def create_city(db: AsyncSession, city: schemas.CityCreate) -> models.City:
#     # ... implementation ...
#     pass

# async def get_city_by_name_and_country(db: AsyncSession, name: str, country: str) -> models.City | None:
#     # ... implementation ...
#     pass

# async def get_cities(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[models.City]:
#     # ... implementation ...
#     pass


# --- UserCityRanking CRUD ---
# async def create_user_city_ranking(db: AsyncSession, user_id: int, ranking: schemas.UserCityRankingCreate) -> models.UserCityRanking:
#     # Here you would also calculate or fetch data for objective_score if needed
#     # objective_score = calculate_objective_score(user_id, ranking.city_id, db)
#     # db_ranking = models.UserCityRanking(
#     #     user_id=user_id,
#     #     city_id=ranking.city_id,
#     #     personal_score=ranking.personal_score,
#     #     objective_score=objective_score # Example
#     # )
#     # ... implementation ...
#     pass

# async def get_user_rankings(db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100) -> list[models.UserCityRanking]:
#     # ... implementation ...
#     pass
