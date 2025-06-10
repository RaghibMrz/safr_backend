# scripts/attributes/update_air_quality.py
import asyncio
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OPENAQ_API_URL = "https://api.openaq.org/v2/latest"
PROGRESS_FILE = Path(__file__).parent / "air_quality_progress.log"

# --- Constants for easy configuration ---
API_REQUEST_INTERVAL = 1

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def load_processed_cities():
    """Loads the set of already processed geoname_ids from the progress log."""
    if not PROGRESS_FILE.exists():
        return set()
    with open(PROGRESS_FILE, 'r') as f:
        return {line.strip() for line in f}

def log_processed_city(geoname_id: str):
    """Appends a geoname_id to the progress log."""
    with open(PROGRESS_FILE, 'a') as f:
        f.write(f"{geoname_id}\n")

async def fetch_and_save_scores(session: AsyncSession):
    """Fetches raw data from the API sequentially and saves progress."""
    print("--- Fetching and saving raw air quality scores (sequentially) ---")
    
    processed_ids = load_processed_cities()
    print(f"Found {len(processed_ids)} already processed cities. Resuming...")

    stmt = select(City).where(City.geoname_id.notin_(processed_ids))
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    total_cities = len(cities_to_process)
    print(f"Found {total_cities} new cities to process.")

    if not cities_to_process:
        return

    attribute_name = CityAttributeName.AIR_QUALITY
    
    async with httpx.AsyncClient() as client:
        for i, city in enumerate(cities_to_process):
            print(f"Processing city {i + 1} of {total_cities}: {city.name} ({city.geoname_id})")
            
            params = {
                "limit": 1, "page": 1, "offset": 0, "sort": "desc",
                "coordinates": f"{city.latitude},{city.longitude}",
                "radius": 25000,
                "order_by": "distance",
                "parameter": "pm25"
            }
            
            try:
                response = await client.get(OPENAQ_API_URL, params=params, timeout=30.0)
                response.raise_for_status()

                raw_score = None
                results = response.json().get("results", [])
                if results:
                    raw_score = results[0].get("value")
                    print(f"  SUCCESS: Found PM2.5 of {raw_score}")
                else:
                    print(f"  SUCCESS (No Data): No station found for {city.name}")

                # Upsert the score for this single city
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
            
            # Wait before processing the next city to respect the rate limit
            await asyncio.sleep(API_REQUEST_INTERVAL)

async def normalize_all_scores(session: AsyncSession):
    # This function remains the same and should be run once after all raw data is collected.
    print("\n--- Normalizing all air quality scores ---")
    # ... (implementation from previous version)

async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session)

if __name__ == "__main__":
    asyncio.run(main())