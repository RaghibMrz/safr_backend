# scripts/seed_cities.py
import asyncio
import csv
import io
import os
import zipfile
from pathlib import Path

import pycountry
import requests
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from unidecode import unidecode

# --- Configuration ---
GEONAMES_URL = "http://download.geonames.org/export/dump/allCountries.zip"
CITIES_FILE_IN_ZIP = "allCountries.txt"
BATCH_SIZE = 5000

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# --- SQLAlchemy Models ---
from safr_backend.models import City, Base


async def download_and_extract_data():
    """
    Downloads, extracts, filters, and de-duplicates city data from GeoNames.
    """
    print(f"Downloading city data from {GEONAMES_URL}...")
    try:
        response = requests.get(GEONAMES_URL, stream=True)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            if CITIES_FILE_IN_ZIP not in zf.namelist():
                raise FileNotFoundError(f"{CITIES_FILE_IN_ZIP} not found in the zip file.")
            with zf.open(CITIES_FILE_IN_ZIP) as city_file:
                city_data_text = city_file.read().decode('utf-8')
                csv_reader = csv.reader(io.StringIO(city_data_text), delimiter='\t')
                
                cities = []
                print("Filtering for significant cities...")
                for row in csv_reader:
                    if len(row) >= 15:
                        feature_code = row[7]
                        population = int(row[14]) if row[14] else 0
                        is_capital = feature_code in ['PPLC', 'PPLA']
                        # is_significant_city = feature_code in ['PPL', 'PPLX'] and population > 25000
                        
                        if is_capital or population > 10000:
                            cities.append({
                                "geoname_id": row[0], "name": row[1],
                                "latitude": float(row[4]), "longitude": float(row[5]),
                                "country_code": row[8], "population": population,
                                "feature_code": feature_code # Include feature_code for de-duplication
                            })

                print(f"Extracted and filtered {len(cities)} cities. Now de-duplicating...")

                # --- NEW DE-DUPLICATION LOGIC ---
                unique_cities = {}
                feature_code_priority = {'PPLC': 1, 'PPLA': 2, 'PPL': 3, 'PPLX': 4}

                for city in cities:
                    # Create a unique key for each city based on name and country
                    key = (city['name'], city['country_code'])
                    
                    if key not in unique_cities:
                        # If we haven't seen this city before, add it.
                        unique_cities[key] = city
                    else:
                        # If we have seen it, decide if this new one is better.
                        existing_city = unique_cities[key]
                        
                        # Compare based on feature code priority first
                        existing_priority = feature_code_priority.get(existing_city['feature_code'], 99)
                        new_priority = feature_code_priority.get(city['feature_code'], 99)

                        if new_priority < existing_priority:
                            # A better feature code (e.g., PPLC beats PPL)
                            unique_cities[key] = city
                        elif new_priority == existing_priority and city['population'] > existing_city['population']:
                            # Same feature code, but higher population
                            unique_cities[key] = city
                
                deduplicated_list = list(unique_cities.values())
                print(f"De-duplication complete. Final city count: {len(deduplicated_list)}")
                return deduplicated_list

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []


async def seed_cities_to_db(db: AsyncSession, cities_data: list):
    """Gracefully updates existing cities and inserts new ones in batches."""
    if not cities_data:
        print("No city data to seed.")
        return

    country_map = {country.alpha_2: country.name for country in pycountry.countries}
    total_inserted = 0
    total_updated = 0

    # --- Process the entire list in smaller batches ---
    for i in range(0, len(cities_data), BATCH_SIZE):
        batch = cities_data[i:i + BATCH_SIZE]
        print(f"Processing batch {i // BATCH_SIZE + 1}...")

        source_geoname_ids = [c['geoname_id'] for c in batch]
        stmt = select(City).where(City.geoname_id.in_(source_geoname_ids))
        result = await db.execute(stmt)
        existing_cities_map = {city.geoname_id: city for city in result.scalars().all()}
        
        update_count = 0
        insert_count = 0

        for city_data in batch:
            geoname_id = city_data["geoname_id"]
            city_name = city_data["name"]
            country_code = city_data["country_code"]
            
            if geoname_id in existing_cities_map:
                city_to_update = existing_cities_map[geoname_id]
                city_to_update.name = city_name
                city_to_update.name_normalized = unidecode(city_name.lower())
                city_to_update.country_code = country_code
                city_to_update.country_name = country_map.get(country_code, "")
                city_to_update.latitude = city_data["latitude"]
                city_to_update.longitude = city_data["longitude"]
                db.add(city_to_update)
                update_count += 1
            else:
                new_city = City(
                    geoname_id=geoname_id, name=city_name,
                    name_normalized=unidecode(city_name.lower()),
                    country_code=country_code, country_name=country_map.get(country_code, ""),
                    latitude=city_data["latitude"], longitude=city_data["longitude"],
                )
                db.add(new_city)
                insert_count += 1
        
        total_inserted += insert_count
        total_updated += update_count
    
    if total_inserted > 0 or total_updated > 0:
        try:
            await db.commit()
            print(f"Successfully committed changes for all batches: {total_inserted} cities inserted, {total_updated} cities updated.")
        except Exception as e:
            await db.rollback()
            print(f"Error during final commit: {e}")
    else:
        print("No changes to commit.")


async def main():
    """Main function to orchestrate the seeding process."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("Database tables checked/created.")

    cities_data = await download_and_extract_data()
    if cities_data:
        async with AsyncSessionLocal() as session:
            await seed_cities_to_db(session, cities_data)

if __name__ == "__main__":
    print("Starting city seeding process...")
    asyncio.run(main())
    print("City seeding process finished.")