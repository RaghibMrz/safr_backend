# scripts/attributes/update_air_quality.py
import asyncio
import httpx
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
import numpy as np

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OPENWEATHER_HISTORY_API_URL = "http://api.openweathermap.org/data/2.5/air_pollution/history"
PROGRESS_FILE = Path(__file__).parent / "air_quality_progress.log"

# --- Constants for easy configuration ---
API_REQUEST_INTERVAL = 1.1 # Seconds to wait between each API call
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
if not OPENWEATHER_API_KEY:
    raise ValueError("OPENWEATHER_API_KEY not set in your .env file.")

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
    """Fetches historical data, calculates an annual average, and saves it."""
    print("--- Fetching and saving raw air quality scores (from OpenWeatherMap History) ---")
    
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
    
    # --- Calculate start and end timestamps for the last year ---
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())
    # -----------------------------------------------------------

    async with httpx.AsyncClient() as client:
        for i, city in enumerate(cities_to_process):
            print(f"Processing city {i + 1} of {total_cities}: {city.name} ({city.geoname_id})")
            
            params = {
                "lat": city.latitude,
                "lon": city.longitude,
                "start": start_timestamp,
                "end": end_timestamp,
                "appid": OPENWEATHER_API_KEY
            }
            
            try:
                response = await client.get(OPENWEATHER_HISTORY_API_URL, params=params, timeout=30.0)
                response.raise_for_status()

                raw_score = None
                historical_data = response.json().get("list", [])
                
                if historical_data:
                    # --- Calculate the average PM2.5 from the historical data ---
                    pm25_values = [item['components']['pm2_5'] for item in historical_data]
                    if pm25_values:
                        raw_score = np.mean(pm25_values)
                        print(f"  SUCCESS: Calculated average PM2.5 of {raw_score:.2f} from {len(pm25_values)} records.")
                    else:
                        print(f"  SUCCESS (No Data): Historical data found, but no PM2.5 measurements.")
                    # -------------------------------------------------------------
                else:
                    print(f"  SUCCESS (No Data): No historical data found for {city.name}")

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
            
            await asyncio.sleep(API_REQUEST_INTERVAL)

async def normalize_all_scores(session: AsyncSession):
    """
    Reads all raw scores from the DB for this attribute, normalizes them, 
    and saves the final score. This should be run separately after all raw data is collected.
    """
    print("\n--- Normalizing all air quality scores ---")
    attribute_name = CityAttributeName.AIR_QUALITY
    
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
    print(f"Normalizing based on Min PM2.5={min_score}, Max PM2.5={max_score}")

    if max_score == min_score:
        print("All raw scores are the same. Setting normalized score to 0.5 for all.")
    
    all_attributes_stmt = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
    all_attributes_result = await session.execute(all_attributes_stmt)
    
    update_count = 0
    for attr in all_attributes_result.scalars().all():
        if attr.raw_value is not None:
            # A lower raw score (less pollution) is better, so we invert the normalization.
            if max_score > min_score:
                attr.normalized_score = 1 - ((attr.raw_value - min_score) / (max_score - min_score))
            else:
                attr.normalized_score = 0.5 # If all values are the same, they are perfectly average.
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