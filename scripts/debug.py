import asyncio
import csv
import io
import os
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker

# --- Configuration ---
GEONAMES_URL = "http://download.geonames.org/export/dump/allCountries.zip"
CITIES_FILE_IN_ZIP = "allCountries.txt"

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# --- Model Import ---
from safr_backend.models import City

async def get_all_db_geoname_ids(db: AsyncSession):
    """Fetches all geoname_ids currently in your database."""
    result = await db.execute(select(City.geoname_id).where(City.geoname_id.isnot(None)))
    return set(result.scalars().all())

async def download_and_get_source_data():
    """Downloads the source file and returns a list of all rows."""
    print("Downloading source data...")
    response = requests.get(GEONAMES_URL, stream=True)
    response.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    with zf.open(CITIES_FILE_IN_ZIP) as city_file:
        city_data_text = city_file.read().decode('utf-8')
        csv_reader = csv.reader(io.StringIO(city_data_text), delimiter='\t')
        return list(csv_reader)

def apply_filter(all_data):
    """Applies the same filter as the real seeder script."""
    filtered_ids = set()
    for row in all_data:
        if len(row) >= 15:
            feature_code = row[7]
            population = int(row[14]) if row[14] else 0
            is_capital = feature_code in ['PPLC', 'PPLA']
            is_significant_city = feature_code == 'PPL' and population > 5000
            if is_capital or is_significant_city:
                filtered_ids.add(row[0])
    return filtered_ids

async def main():
    """Main debug function."""
    async with AsyncSessionLocal() as session:
        print("Fetching all geoname_ids from your local database...")
        db_ids = await get_all_db_geoname_ids(session)
        print(db_ids)
        print(f"Found {len(db_ids)} cities in your database.")

    all_source_data = await download_and_get_source_data()
    all_source_ids = {row[0] for row in all_source_data if len(row) > 0}
    print(f"Found {len(all_source_ids)} total entries in the source file.")
    
    filtered_source_ids = apply_filter(all_source_data)
    print(filtered_source_ids)
    print(f"Found {len(filtered_source_ids)} entries after applying the significance filter.")

    print("-" * 50)
    
    # --- The Debugging Logic ---
    unmatched_ids = db_ids - filtered_source_ids
    
    if not unmatched_ids:
        print("Good news! All IDs in your database were found in the filtered source data.")
        print("The issue might lie elsewhere. Try the single ID lookup below.")
    else:
        print(f"Found {len(unmatched_ids)} IDs in your DB that are NOT in the filtered source data.")
        print("This is likely the cause of the problem.")
        sample_unmatched_id = list(unmatched_ids)[0]
        print(f"Here is a sample unmatched ID: {sample_unmatched_id}")
        
        # Now let's find the raw data for this sample ID in the unfiltered source
        found_in_raw = False
        for row in all_source_data:
            if len(row) > 0 and row[0] == sample_unmatched_id:
                print("\n--- Raw Data for Sample Unmatched ID ---")
                print(f"Geoname ID:    {row[0]}")
                print(f"Name:          {row[1]}")
                print(f"Feature Code:  {row[7]}")
                print(f"Country Code:  {row[8]}")
                print(f"Population:    {row[14]}")
                print("This city was likely excluded by the population or feature code filter.")
                found_in_raw = True
                break
        if not found_in_raw:
             print(f"\nSample ID {sample_unmatched_id} was not found in the raw source file at all.")


    print("-" * 50)
    # --- Manual Lookup ---
    while True:
        lookup_id = input("Enter a geoname_id to look up its raw data (or 'exit'): ").strip()
        if lookup_id.lower() == 'exit':
            break
        found = False
        for row in all_source_data:
            if len(row) > 0 and row[0] == lookup_id:
                print(f"\n--- Raw Data for {lookup_id} ---")
                print(f"Geoname ID:    {row[0]}, Name: {row[1]}, Feature Code: {row[7]}, Population: {row[14]}")
                found = True
                break
        if not found:
            print("ID not found in the source file.")


if __name__ == "__main__":
    asyncio.run(main())