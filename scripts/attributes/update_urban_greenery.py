# scripts/attributes/update_urban_greenery.py
import asyncio
import httpx
import os
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
OVERPASS_API_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]
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
API_CONCURRENT_REQUESTS = 10

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
    """Fetches raw data using polite concurrency and saves progress."""
    print("--- Fetching and saving raw urban greenery scores (with polite concurrency) ---")
    
    processed_ids = load_processed_cities()
    result = await session.execute(select(City.geoname_id))
    all_city_ids = {row[0] for row in result.all()}
    not_processed_ids = all_city_ids - processed_ids
    print(f"Found {len(not_processed_ids)} new cities to process.")

    stmt = select(City).where(City.geoname_id.in_(not_processed_ids))
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    total_cities = len(cities_to_process)
    print(f"Found {total_cities} new cities to process.")

    if not cities_to_process:
        return

    attribute_name = CityAttributeName.URBAN_GREENERY
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        for i in range(0, total_cities, API_CONCURRENT_REQUESTS):
            batch = cities_to_process[i:i + API_CONCURRENT_REQUESTS]
            print(f"Processing batch {i//API_CONCURRENT_REQUESTS + 1} of {total_cities//API_CONCURRENT_REQUESTS + 1} ({len(batch)} cities)...")

            tasks = []
            for city in batch:
                query = OVERPASS_QUERY_TEMPLATE.format(lat=city.latitude, lon=city.longitude)
                endpoint_url = OVERPASS_API_ENDPOINTS[2]
                tasks.append(client.post(endpoint_url, data=query))

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for city, response in zip(batch, responses):
                if isinstance(response, httpx.Response) and response.status_code == 200:
                    try:
                        data = response.json()
                        raw_score = int(data.get("elements", [{}])[0].get("tags", {}).get("total", 0))
                        print(f"  SUCCESS: Found {raw_score} green spaces for {city.name}")

                        # Upsert logic for this specific city
                        stmt_existing = select(CityAttribute).where(CityAttribute.city_id == city.id, CityAttribute.attribute_name == attribute_name)
                        result_existing = await session.execute(stmt_existing)
                        attr = result_existing.scalars().first()
                        
                        if attr:
                            attr.raw_value = raw_score
                        else:
                            attr = CityAttribute(city_id=city.id, attribute_name=attribute_name, raw_value=raw_score, normalized_score=0)
                        
                        session.add(attr)
                        await session.commit()
                        log_processed_city(city.geoname_id)

                    except Exception as e:
                        print(f"  FAILURE (Post-processing): Could not process response for {city.name}. Error: {e}")
                else:
                    print(f"  FAILURE (HTTP): Could not fetch data for {city.name}. Error: {response}")
            
            if (i + API_CONCURRENT_REQUESTS) < total_cities:
                print(f"Batch complete")


async def normalize_all_scores(session: AsyncSession):
    """
    Reads all raw scores, calculates a per-capita score, and applies min-max scaling
    after clipping extreme outliers at the 99th percentile.
    """
    print("\n--- Normalizing scores using per-capita and outlier clipping ---")
    
    attribute_name = CityAttributeName.URBAN_GREENERY
    
    stmt = (
        select(CityAttribute, City.population)
        .join(City, CityAttribute.city_id == City.id)
        .where(CityAttribute.attribute_name == attribute_name)
    )
    result = await session.execute(stmt)
    all_attributes_with_pop = result.all()

    per_capita_scores_map = {}
    valid_scores = []
    for attr, population in all_attributes_with_pop:
        if attr.raw_value and population and attr.raw_value > 0 and population > 0:
            score = attr.raw_value / population
            per_capita_scores_map[attr.id] = score
            valid_scores.append(score)

    if not valid_scores or len(valid_scores) < 2:
        print("Not enough valid data to normalize.")
        for attr, _ in all_attributes_with_pop:
            attr.normalized_score = -1.0
        await session.commit()
        return

    # Clip extreme outliers at the 99th percentile
    p99 = np.percentile(valid_scores, 99)
    print(f"Clipping scores at 99th percentile: {p99:.6f}")
    
    clipped_scores = [min(score, p99) for score in valid_scores]
    
    min_score = min(clipped_scores)
    max_score = max(clipped_scores) # This will now be equal to p99
    print(f"Normalizing based on clipped range: Min={min_score:.6f}, Max={max_score:.6f}")

    update_count = 0
    for attr, _ in all_attributes_with_pop:
        per_capita_score = per_capita_scores_map.get(attr.id)
        
        if per_capita_score is not None:
            clipped_score = min(per_capita_score, p99)
            if max_score > min_score:
                attr.normalized_score = (clipped_score - min_score) / (max_score - min_score)
            else:
                attr.normalized_score = 0.5
        else:
            attr.normalized_score = -1.0
        
        session.add(attr)
        update_count += 1
        
    await session.commit()
    print(f"Successfully updated {update_count} attributes with clipped normalized scores.")


async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session) 

if __name__ == "__main__":
    asyncio.run(main())