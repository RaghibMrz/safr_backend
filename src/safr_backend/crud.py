# src/safr_backend/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload # For eager loading related City
from typing import List, Optional

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


# --- City CRUD ---

async def get_city(db: AsyncSession, city_id: int) -> models.City | None:
    """
    Retrieves a specific city by its ID.

    Args:
        db: The asynchronous database session.
        city_id: The ID of the city to retrieve.

    Returns:
        The City model instance if found, otherwise None.
    """
    result = await db.execute(select(models.City).filter(models.City.id == city_id))
    return result.scalars().first()

async def get_cities(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[models.City]:
    """
    Retrieves a list of cities with pagination.

    Args:
        db: The asynchronous database session.
        skip: The number of records to skip (for pagination).
        limit: The maximum number of records to return.

    Returns:
        A list of City model instances.
    """
    result = await db.execute(select(models.City).offset(skip).limit(limit))
    return result.scalars().all()

# --- UserCityRanking CRUD ---

async def get_user_city_ranking(
    db: AsyncSession, user_id: int, city_id: int
) -> Optional[models.UserCityRanking]:
    """
    Retrieves a specific ranking for a user and city.
    """
    result = await db.execute(
        select(models.UserCityRanking)
        .filter(models.UserCityRanking.user_id == user_id)
        .filter(models.UserCityRanking.city_id == city_id)
        .options(selectinload(models.UserCityRanking.city)) # Eager load city details
    )
    return result.scalars().first()

async def upsert_user_city_ranking(
    db: AsyncSession, user_id: int, city_id: int, ranking_data: schemas.UserCityRankingCreate
) -> models.UserCityRanking:
    """
    Creates a new city ranking for a user or updates an existing one.
    The objective_score is not handled here and will remain None or its previous value.
    """
    # Check if the city exists
    city = await get_city(db, city_id=city_id)
    if not city:
        # This case should ideally be prevented by frontend or API validation
        # but good to have a check.
        raise ValueError(f"City with id {city_id} not found.")

    existing_ranking = await get_user_city_ranking(db, user_id=user_id, city_id=city_id)

    if existing_ranking:
        # Update existing ranking
        existing_ranking.personal_score = ranking_data.personal_score
        # existing_ranking.objective_score remains untouched or None
        # The updated_at field in models.UserCityRanking will be auto-updated by the DB
        db.add(existing_ranking)
        await db.commit()
        await db.refresh(existing_ranking)
        # Ensure city is loaded for the response after refresh
        await db.refresh(existing_ranking, attribute_names=['city'])
        return existing_ranking
    else:
        # Create new ranking
        db_ranking = models.UserCityRanking(
            user_id=user_id,
            city_id=city_id,
            personal_score=ranking_data.personal_score,
            objective_score=None # Explicitly set to None for new rankings
        )
        db.add(db_ranking)
        await db.commit()
        await db.refresh(db_ranking)
        # Ensure city is loaded for the response after refresh
        # This is important because the 'city' relationship is needed for UserCityRankingDisplay
        # and might not be loaded automatically after a simple refresh of db_ranking.
        # A more robust way is to re-fetch or ensure the session loads it.
        # For simplicity, we can reload the relationship.
        await db.refresh(db_ranking, attribute_names=['city'])
        if db_ranking.city is None: # If city wasn't loaded by refresh, manually assign it
            db_ranking.city = city
        return db_ranking

async def get_user_rankings_with_details(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100, sort_desc: bool = True
) -> List[models.UserCityRanking]:
    """
    Retrieves a list of city rankings for a specific user, ordered by personal_score.
    Includes city details.
    """
    order_by_clause = (
        models.UserCityRanking.personal_score.desc()
        if sort_desc
        else models.UserCityRanking.personal_score.asc()
    )

    result = await db.execute(
        select(models.UserCityRanking)
        .filter(models.UserCityRanking.user_id == user_id)
        .options(selectinload(models.UserCityRanking.city)) # Eager load city details
        .order_by(order_by_clause)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def search_cities_by_name(
    db: AsyncSession,
    search_term: str,
    country_name: Optional[str] = None,
    limit: int = 10
) -> List[models.City]:
    
    normalized_term = unidecode(search_term.lower())
    stmt = select(models.City)

    if search_term:
        stmt = stmt.where(models.City.name_normalized.like(f"%{normalized_term}%"))

    if country_name:
        stmt = stmt.where(models.City.country_name.ilike(f"%{country_name}%"))

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
