# scripts/attributes/update_urban_greenery.py
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
OVERPASS_API_URL = "https://overpass.kumi.systems/api/interpreter" # Using the more lenient server
PROGRESS_FILE = Path(__file__).parent / "urban_greenery_progress.log"
# --- We can now process a much larger batch of cities per API call ---
CITY_BATCH_SIZE = 250
API_SLEEP_INTERVAL = 5 # Seconds to wait between large API calls

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

def log_processed_batch(city_ids):
    with open(PROGRESS_FILE, 'a') as f:
        for city_id in city_ids:
            f.write(f"{city_id}\n")

async def fetch_and_save_scores(session: AsyncSession):
    print("--- Fetching and saving raw urban greenery scores ---")
    
    processed_ids = load_processed_cities()
    print(f"Found {len(processed_ids)} already processed cities. Resuming...")

    stmt = select(City).where(City.geoname_id.notin_(processed_ids))
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    print(f"Found {len(cities_to_process)} new cities to process.")

    if not cities_to_process:
        print("All cities have been processed.")
        return

    attribute_name = CityAttributeName.URBAN_GREENERY
    
    async with httpx.AsyncClient(timeout=180.0) as client: # Increase timeout for larger queries
        for i in range(0, len(cities_to_process), CITY_BATCH_SIZE):
            batch = cities_to_process[i:i + CITY_BATCH_SIZE]
            
            # --- Dynamically build one large query for the entire batch ---
            query_parts = []
            for city in batch:
                # Assign a unique variable name for each city's results
                query_parts.append(f"""
                (
                  node[leisure=park](around:10000,{city.latitude},{city.longitude});
                  way[leisure=park](around:10000,{city.latitude},{city.longitude});
                )->.set_{city.geoname_id};
                make count val=set_{city.geoname_id}.count(), geoname_id="{city.geoname_id}";
                out;
                """)
            
            full_query = f"[out:json];({';'.join(query_parts)});"
            # -----------------------------------------------------------
            
            print(f"Processing batch {i//CITY_BATCH_SIZE + 1} of {len(cities_to_process)//CITY_BATCH_SIZE + 1} ({len(batch)} cities)...")
            
            try:
                response = await client.post(OVERPASS_API_URL, data=full_query)
                response.raise_for_status()
                data = response.json()

                # --- Parse the combined results ---
                scores = {elem['tags']['geoname_id']: int(elem['tags']['total']) for elem in data.get('elements', [])}
                
                # --- Upsert the results for the batch ---
                batch_city_ids = [c.id for c in batch]
                existing_attrs_stmt = select(CityAttribute).where(
                    CityAttribute.attribute_name == attribute_name,
                    CityAttribute.city_id.in_(batch_city_ids)
                )
                existing_attrs_result = await session.execute(existing_attrs_stmt)
                existing_attrs_map = {attr.city_id: attr for attr in existing_attrs_result.scalars().all()}

                for city in batch:
                    raw_score = scores.get(city.geoname_id, 0) # Default to 0 if not in results
                    
                    if city.id in existing_attrs_map:
                        attr = existing_attrs_map[city.id]
                        attr.raw_value = raw_score
                    else:
                        attr = CityAttribute(
                            city_id=city.id, attribute_name=attribute_name,
                            raw_value=raw_score, normalized_score=0
                        )
                    session.add(attr)
                
                await session.commit()
                log_processed_batch([c.geoname_id for c in batch])
                print(f"Batch successfully processed and committed.")

            except httpx.HTTPStatusError as e:
                print(f"HTTP ERROR for batch: {e.response.status_code} - {e.response.text}")
                print("Skipping this batch and continuing...")
            except Exception as e:
                print(f"An unexpected error occurred for batch: {e}")
                print("Skipping this batch and continuing...")

            print(f"Waiting {API_SLEEP_INTERVAL} seconds...")
            await asyncio.sleep(API_SLEEP_INTERVAL)

async def normalize_all_scores(session: AsyncSession):
    # This function remains the same as before
    print("\n--- Normalizing all scores ---")
    # ...

async def main():
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session)

if __name__ == "__main__":
    asyncio.run(main())