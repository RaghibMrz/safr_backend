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
# Use the more comprehensive 'allCountries' file for better coverage
GEONAMES_URL = "http://download.geonames.org/export/dump/allCountries.zip"
CITIES_FILE_IN_ZIP = "allCountries.txt"

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
    """Downloads and extracts city data from GeoNames, filtering for significance."""
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
                print("Filtering for significant cities (capitals and major populated places)...")
                for row in csv_reader:
                    if len(row) >= 15:
                        feature_code = row[7]
                        population = int(row[14]) if row[14] else 0

                        # --- New, more inclusive filtering logic ---
                        is_capital = feature_code in ['PPLC', 'PPLA']
                        is_significant_city = feature_code == 'PPL' and population > 25000

                        if is_capital or is_significant_city:
                            cities.append({
                                "geoname_id": row[0],
                                "name": row[1],
                                "latitude": float(row[4]),
                                "longitude": float(row[5]),
                                "country_code": row[8],
                                "population": population,
                            })
                print(f"Successfully extracted and filtered {len(cities)} significant cities.")
                return cities
    except requests.RequestException as e:
        print(f"Error downloading data: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []


async def seed_cities_to_db(db: AsyncSession, cities_data: list):
    """
    Gracefully updates existing cities and inserts new ones.
    This 'upsert' logic ensures no data is lost.
    """
    if not cities_data:
        print("No city data to seed.")
        return

    print(f"Preparing to upsert (update or insert) {len(cities_data)} cities...")

    # Create a mapping of country codes to full names
    country_map = {country.alpha_2: country.name for country in pycountry.countries}

    # --- New Upsert Logic ---
    # 1. Get all geoname_ids from the source file
    source_geoname_ids = [c['geoname_id'] for c in cities_data]

    # 2. Find which of these cities already exist in the DB in one query
    stmt = select(City).where(City.geoname_id.in_(source_geoname_ids))
    result = await db.execute(stmt)
    # Create a dictionary for quick lookups: {geoname_id: city_object}
    existing_cities_map = {city.geoname_id: city for city in result.scalars().all()}
    print(f"Found {len(existing_cities_map)} matching cities in the database to update.")

    update_count = 0
    insert_count = 0

    # 3. Iterate through the source data and decide whether to update or insert
    for city_data in cities_data:
        geoname_id = city_data["geoname_id"]
        city_name = city_data["name"]
        country_code = city_data["country_code"]

        # Check if the city exists in our map
        if geoname_id in existing_cities_map:
            # --- UPDATE ---
            city_to_update = existing_cities_map[geoname_id]
            city_to_update.name = city_name
            city_to_update.name_normalized = unidecode(city_name.lower())
            city_to_update.country_code = country_code
            city_to_update.country_name = country_map.get(country_code, "")
            city_to_update.latitude = city_data["latitude"]
            city_to_update.longitude = city_data["longitude"]
            db.add(city_to_update) # Add to session to mark for update
            update_count += 1
        else:
            # --- INSERT ---
            new_city = City(
                geoname_id=geoname_id,
                name=city_name,
                name_normalized=unidecode(city_name.lower()),
                country_code=country_code,
                country_name=country_map.get(country_code, ""),
                latitude=city_data["latitude"],
                longitude=city_data["longitude"],
            )
            db.add(new_city)
            insert_count += 1
    
    if update_count > 0 or insert_count > 0:
        try:
            await db.commit()
            print(f"Successfully committed changes: {insert_count} cities inserted, {update_count} cities updated.")
        except Exception as e:
            await db.rollback()
            print(f"Error seeding cities: {e}")
    else:
        print("No changes to commit.")


async def main():
    """Main function to orchestrate the seeding process."""
    # This assumes Alembic is used for table creation in production.
    # This is a safeguard for running the script in a fresh dev environment.
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