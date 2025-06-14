# src/safr_backend/routers/cities.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from .. import crud, schemas
from ..database import get_db

router = APIRouter(
    prefix="/cities",  # All routes in this router will start with /cities
    tags=["Cities"],    # Tag for API documentation
    responses={404: {"description": "Not found"}}, # Default response for this router
)

@router.get("/", response_model=List[schemas.CityDisplay])
async def read_cities(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a list of cities.
    Users can paginate through the list using `skip` and `limit` query parameters.
    """
    cities = await crud.get_cities(db, skip=skip, limit=limit)
    return cities

@router.get("/{city_id}", response_model=schemas.CityDisplay)
async def read_city(
    city_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve details for a specific city by its ID.
    """
    db_city = await crud.get_city(db, city_id=city_id)
    if db_city is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found")
    return db_city


@router.get("/search/", response_model=List[schemas.CityDisplay])
async def search_cities(
    query: str,
    country: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    cities = await crud.search_cities_by_name(
        db, search_term=query, country_name=country, limit=limit
    )
    return cities
