# scripts/attributes/update_urban_greenery.py
import asyncio
import httpx
import os
import random
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OVERPASS_API_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter"
]
# This is the query for a SINGLE city's greenery count.
OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:60];
(
  way[leisure~"^(park|garden|nature_reserve|recreation_ground|village_green)$"](around:10000,{lat},{lon});
  relation[leisure~"^(park|garden|nature_reserve|recreation_ground|village_green)$"](around:10000,{lat},{lon});
  way[landuse~"^(forest|meadow)$"](around:10000,{lat},{lon});
  relation[landuse~"^(forest|meadow)$"](around:10000,{lat},{lon});
  way[natural~"^(wood|grassland)$"](around:10000,{lat},{lon});
  relation[natural~"^(wood|grassland)$"](around:10000,{lat},{lon});
);
out count;
"""
PROGRESS_FILE = Path(__file__).parent / "urban_greenery_progress.log"
API_REQUEST_INTERVAL = 1.1

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def load_processed_cities():
    if not PROGRESS_FILE.exists():
        return set()
    with open(PROGRESS_FILE, 'r') as f:
        return {line.strip() for line in f}

def log_processed_city(geoname_id: str):
    with open(PROGRESS_FILE, 'a') as f:
        f.write(f"{geoname_id}\n")

async def fetch_and_save_scores(session: AsyncSession):
    print("--- Fetching and saving raw urban greenery scores (sequentially) ---")
    
    processed_ids = load_processed_cities()
    print(f"Found {len(processed_ids)} already processed cities. Resuming...")

    stmt = select(City).where(City.geoname_id.notin_(processed_ids))
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    total_cities = len(cities_to_process)
    print(f"Found {total_cities} new cities to process.")

    if not cities_to_process:
        return

    attribute_name = CityAttributeName.URBAN_GREENERY
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        for i, city in enumerate(cities_to_process):
            print(f"Processing city {i + 1} of {total_cities}: {city.name} ({city.geoname_id})")
            
            query = OVERPASS_QUERY_TEMPLATE.format(lat=city.latitude, lon=city.longitude)
            
            try:
                endpoint_url = random.choice(OVERPASS_API_ENDPOINTS)
                response = await client.post(endpoint_url, data=query)
                response.raise_for_status()
                data = response.json()

                raw_score = int(data.get("elements", [{}])[0].get("tags", {}).get("total", 0))
                print(f"  SUCCESS: Found {raw_score} green spaces for {city.name}")

                stmt_existing = select(CityAttribute).where(CityAttribute.city_id == city.id, CityAttribute.attribute_name == attribute_name)
                result_existing = await session.execute(stmt_existing)
                attr = result_existing.scalars().first()
                
                if attr:
                    attr.raw_value = raw_score
                else:
                    attr = CityAttribute(
                        city_id=city.id, attribute_name=attribute_name,
                        raw_value=raw_score, normalized_score=0
                    )
                session.add(attr)
                await session.commit()
                log_processed_city(city.geoname_id)

            except Exception as e:
                print(f"  FAILURE: Could not process {city.name}. Error: {e}")
            
            # Wait before processing the next city to be polite to the public API
            await asyncio.sleep(API_REQUEST_INTERVAL)

async def normalize_all_scores(session: AsyncSession):
    """Reads all raw scores from the DB, normalizes them, and saves the final score."""
    print("\n--- Pass 2: Normalizing all scores ---")
    
    attribute_name = CityAttributeName.URBAN_GREENERY
    
    stmt = select(CityAttribute.raw_value).where(
        CityAttribute.attribute_name == attribute_name,
        CityAttribute.raw_value.isnot(None)
    )
    result = await session.execute(stmt)
    raw_scores = result.scalars().all()

    if not raw_scores or len(raw_scores) < 2:
        print("Not enough raw scores found to normalize. At least 2 are required.")
        return

    min_score = min(raw_scores)
    max_score = max(raw_scores)
    print(f"Normalizing based on Min={min_score}, Max={max_score}")

    if max_score == min_score:
        print("All raw scores are the same. Setting normalized score to 0.5 for all.")
    
    all_attributes_stmt = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
    all_attributes_result = await session.execute(all_attributes_stmt)
    
    update_count = 0
    for attr in all_attributes_result.scalars().all():
        if attr.raw_value is not None:
            if max_score > min_score:
                attr.normalized_score = (attr.raw_value - min_score) / (max_score - min_score)
            else:
                attr.normalized_score = 0.5
            session.add(attr)
            update_count += 1
        
    await session.commit()
    print(f"Successfully updated {update_count} attributes with normalized scores.")


async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session) 

if __name__ == "__main__":
    asyncio.run(main())