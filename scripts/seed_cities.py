# scripts/seed_cities.py
import asyncio
import csv
import io
import os
import zipfile
from pathlib import Path

import requests # For downloading the file
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select # For SQLAlchemy 1.4+ style select
# from sqlalchemy import select # For SQLAlchemy 2.0+ style select


# --- Configuration ---
GEONAMES_URL = "http://download.geonames.org/export/dump/cities15000.zip"
CITIES_FILE_IN_ZIP = "cities15000.txt"
NUMBER_OF_CITIES_TO_SEED = 15000

# --- Database Setup ---
# Load environment variables from .env file in the project root
# This script is in a 'scripts' subdirectory, so .env is one level up.
# Adjust path if your script is located elsewhere relative to .env
dotenv_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set. Please create a .env file in the project root.")

# Convert async URL to sync for this script if it's simpler, or use async setup
# For simplicity in a one-off script, a synchronous engine can be easier if not doing other async tasks.
# However, to reuse our existing async models and session, let's stick to async.
# Ensure your DATABASE_URL in .env is the async one (e.g., "postgresql+asyncpg://...")

engine = create_async_engine(DATABASE_URL, echo=False) # echo=True for SQL logging
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# --- SQLAlchemy Models ---
# Minimal redefinition or import from your main app.
# For a standalone script, it's often cleaner to redefine or have a shared models location.
# Let's assume we can import them if the script is run in an environment where `src` is accessible.
# This requires running the script with PYTHONPATH set or using `poetry run python scripts/seed_cities.py`
# from src.safr_backend.models import City, Base # Assuming models.py is in src/safr_backend/
# For this standalone example, let's define a minimal City model structure
# that matches your actual models.City.
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float

Base = declarative_base()

class City(Base):
    __tablename__ = "cities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    country = Column(String, nullable=False, index=True) # Country code (e.g., US, GB)
    geoname_id = Column(String, unique=True, index=True, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    def __repr__(self):
        return f"<City(name='{self.name}', country='{self.country}')>"


async def download_and_extract_data():
    """Downloads and extracts city data from GeoNames."""
    print(f"Downloading city data from {GEONAMES_URL}...")
    try:
        response = requests.get(GEONAMES_URL, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            if CITIES_FILE_IN_ZIP not in zf.namelist():
                raise FileNotFoundError(
                    f"{CITIES_FILE_IN_ZIP} not found in the downloaded zip file."
                )
            with zf.open(CITIES_FILE_IN_ZIP) as city_file:
                # Read the file content and decode it as UTF-8
                city_data_bytes = city_file.read()
                city_data_text = city_data_bytes.decode('utf-8')
                # Use csv.reader to parse the tab-delimited file
                # Wrap the text data in an io.StringIO object
                csv_reader = csv.reader(io.StringIO(city_data_text), delimiter='\t')
                cities = []
                for row in csv_reader:
                    if len(row) >= 15: # Ensure row has enough columns
                        cities.append({
                            "geoname_id": row[0],
                            "name": row[1],       # name
                            "latitude": float(row[4]),
                            "longitude": float(row[5]),
                            "country_code": row[8], # country code
                            # Population is at index 14, useful for sorting/filtering
                            "population": int(row[14]) if row[14] else 0,
                        })
                print(f"Successfully extracted {len(cities)} cities from the archive.")
                return cities
    except requests.RequestException as e:
        print(f"Error downloading data: {e}")
        return []
    except zipfile.BadZipFile:
        print("Error: Downloaded file is not a valid zip archive or is corrupted.")
        return []
    except Exception as e:
        print(f"An unexpected error occurred during download/extraction: {e}")
        return []


async def seed_cities_to_db(db: AsyncSession, cities_data: list):
    """Seeds city data into the database."""
    if not cities_data:
        print("No city data to seed.")
        return

    # Optional: Sort cities by population and take the top N
    # This makes the "NUMBER_OF_CITIES_TO_SEED" more meaningful as "top N popular"
    sorted_cities = sorted(cities_data, key=lambda x: x.get("population", 0), reverse=True)
    cities_to_seed = sorted_cities[:NUMBER_OF_CITIES_TO_SEED]
    
    print(f"Preparing to seed {len(cities_to_seed)} cities...")

    # Check for existing geoname_ids to avoid duplicates if script is run multiple times
    existing_geoname_ids_result = await db.execute(select(City.geoname_id))
    existing_geoname_ids = set(existing_geoname_ids_result.scalars().all())
    print(f"Found {len(existing_geoname_ids)} existing geoname_ids in the database.")

    new_cities_count = 0
    for city_data in cities_to_seed:
        if city_data["geoname_id"] in existing_geoname_ids:
            # print(f"Skipping city {city_data['name']} ({city_data['geoname_id']}) as it already exists.")
            continue

        city = City(
            name=city_data["name"],
            country=city_data["country_code"],
            latitude=city_data["latitude"],
            longitude=city_data["longitude"],
            geoname_id=city_data["geoname_id"]
        )
        db.add(city)
        new_cities_count += 1
        existing_geoname_ids.add(city_data["geoname_id"]) # Add to set to handle duplicates within the batch

    if new_cities_count > 0:
        try:
            await db.commit()
            print(f"Successfully seeded {new_cities_count} new cities into the database.")
        except Exception as e:
            await db.rollback()
            print(f"Error seeding cities: {e}")
    else:
        print("No new cities to seed (all top cities might already exist).")


async def main():
    """Main function to orchestrate the seeding process."""
    # Create tables if they don't exist (useful for first run)
    # In a real app, Alembic migrations handle this.
    # This is just for the script's self-containment if run against an empty DB.
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # Optional: drop if you want to clear before seeding
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

