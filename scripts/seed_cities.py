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
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from unidecode import unidecode

# --- Configuration ---
GEONAMES_URL = "http://download.geonames.org/export/dump/allCountries.zip"
CITIES_FILE_IN_ZIP = "allCountries.txt"
BATCH_SIZE = 5000
MIN_POPULATION = 5000

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
    Downloads, extracts, validates, filters, de-duplicates, and finally re-filters city data.
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
                print("Applying initial lenient filter...")
                for row in csv_reader:
                    if len(row) >= 15:
                        feature_code = row[7]
                        if not feature_code.startswith('PPL'):
                            continue
                        country_code = row[8]
                        if not country_code or len(country_code) != 2:
                            continue
                        
                        population = int(row[14]) if row[14] else 0
                        is_capital = feature_code in ['PPLC', 'PPLA']
                        
                        # Lenient filter to ensure we get all necessary records for merging
                        if is_capital or population > MIN_POPULATION:
                            cities.append({
                                "geoname_id": row[0], "name": row[1],
                                "latitude": float(row[4]), "longitude": float(row[5]),
                                "country_code": country_code, "population": population,
                                "feature_code": feature_code
                            })

                print(f"Extracted {len(cities)} potential cities. Now de-duplicating and merging...")

                unique_cities = {}
                feature_code_priority = {'PPLC': 1, 'PPLA': 2, 'PPL': 3, 'PPLX': 4}

                for city in cities:
                    key = (city['name'], city['country_code'])
                    if key not in unique_cities:
                        unique_cities[key] = city
                    else:
                        existing_city = unique_cities[key]
                        new_city = city
                        new_priority = feature_code_priority.get(new_city['feature_code'], 99)
                        existing_priority = feature_code_priority.get(existing_city['feature_code'], 99)

                        if new_priority < existing_priority:
                            primary_city = new_city
                            secondary_city = existing_city
                        else:
                            primary_city = existing_city
                            secondary_city = new_city
                        
                        merged_city = primary_city
                        merged_city['population'] = max(primary_city['population'], secondary_city['population'])
                        unique_cities[key] = merged_city
                
                deduplicated_list = list(unique_cities.values())
                print(f"De-duplication complete. Found {len(deduplicated_list)} unique cities.")

                final_cities_list = [
                    city for city in deduplicated_list if city['population'] >= MIN_POPULATION
                ]
                print(f"Applying final population filter. Final city count: {len(final_cities_list)}")
                return final_cities_list

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []


async def seed_cities_to_db(db: AsyncSession, cities_data: list):
    # This function's logic is sound and does not need changes.
    if not cities_data:
        print("No city data to seed.")
        return

    country_map = {country.alpha_2: country.name for country in pycountry.countries}
    total_inserted = 0
    total_updated = 0

    for i in range(0, len(cities_data), BATCH_SIZE):
        batch = cities_data[i:i + BATCH_SIZE]
        print(f"Processing batch {i // BATCH_SIZE + 1}...")
        source_geoname_ids = [c['geoname_id'] for c in batch]
        stmt = select(City).where(City.geoname_id.in_(source_geoname_ids))
        result = await db.execute(stmt)
        existing_cities_map = {city.geoname_id: city for city in result.scalars().all()}
        
        for city_data in batch:
            geoname_id = city_data["geoname_id"]
            if geoname_id in existing_cities_map:
                city_to_update = existing_cities_map[geoname_id]
                city_to_update.name = city_data["name"]
                city_to_update.name_normalized = unidecode(city_data["name"].lower())
                city_to_update.country_code = city_data["country_code"]
                city_to_update.country_name = country_map.get(city_data["country_code"], "")
                city_to_update.latitude = city_data["latitude"]
                city_to_update.longitude = city_data["longitude"]
                city_to_update.population = city_data["population"]
                db.add(city_to_update)
                total_updated += 1
            else:
                new_city = City(
                    geoname_id=geoname_id, name=city_data["name"],
                    name_normalized=unidecode(city_data["name"].lower()),
                    country_code=city_data["country_code"],
                    country_name=country_map.get(city_data["country_code"], ""),
                    latitude=city_data["latitude"], longitude=city_data["longitude"],
                    population=city_data["population"]
                )
                db.add(new_city)
                total_inserted += 1
    
    if total_inserted > 0 or total_updated > 0:
        try:
            await db.commit()
            print(f"Successfully committed changes: {total_inserted} inserted, {total_updated} updated.")
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