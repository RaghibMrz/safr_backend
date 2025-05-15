# src/safr_backend/routers/rankings.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, schemas, models, security
from ..database import get_db

router = APIRouter(
    prefix="/rankings", # All routes in this router will start with /rankings
    tags=["Rankings"],  # Tag for API documentation
    responses={404: {"description": "Not found"}},
)

@router.put(
    "/cities/{city_id}",
    response_model=schemas.UserCityRankingDisplay,
    summary="Create or update a user's ranking for a city"
)
async def set_user_city_ranking(
    city_id: int,
    ranking_input: schemas.UserCityRankingCreate, # Contains personal_score
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Allows an authenticated user to create a new ranking for a city or update
    an existing one with their personal score.

    - **city_id**: The ID of the city to rank.
    - **personal_score**: The user's subjective score for the city (0-100).
    """
    # First, verify the city exists to provide a clear 404 if not.
    # The CRUD function also checks, but this gives a more standard API response.
    city = await crud.get_city(db, city_id=city_id)
    if not city:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"City with id {city_id} not found."
        )

    try:
        ranking = await crud.upsert_user_city_ranking(
            db=db,
            user_id=current_user.id,
            city_id=city_id,
            ranking_data=ranking_input
        )
        return ranking
    except ValueError as e: # Catch specific errors from CRUD if necessary
        # This handles the ValueError from crud.upsert_user_city_ranking if city is not found,
        # though we already checked above. It's here for robustness.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/me",
    response_model=List[schemas.UserCityRankingDisplay],
    summary="Get the current user's ranked cities"
)
async def get_my_ranked_cities(
    skip: int = 0,
    limit: int = 100,
    sort_desc: bool = True, # True for highest score first, False for lowest first
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Retrieves a list of all cities ranked by the currently authenticated user,
    ordered by their personal score.
    """
    rankings = await crud.get_user_rankings_with_details(
        db=db, user_id=current_user.id, skip=skip, limit=limit, sort_desc=sort_desc
    )
    return rankings

@router.delete(
    "/cities/{city_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user's ranking for a city"
)
async def delete_user_city_ranking(
    city_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(security.get_current_active_user)
):
    """
    Allows an authenticated user to delete their ranking for a specific city.
    """
    ranking_to_delete = await crud.get_user_city_ranking(db, user_id=current_user.id, city_id=city_id)
    
    if not ranking_to_delete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No ranking found for city id {city_id} for the current user."
        )
    
    await db.delete(ranking_to_delete)
    await db.commit()
    return None # HTTP 204 No Content response

