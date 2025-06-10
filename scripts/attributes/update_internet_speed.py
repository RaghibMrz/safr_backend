# scripts/attributes/update_internet_speed.py
import asyncio
import os
from pathlib import Path
import zipfile

import httpx
import pandas as pd
import geopandas as gpd
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
import numpy as np
from dotenv import load_dotenv

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OOKLA_DATA_URL = "https://ookla-open-data.s3.us-west-2.amazonaws.com/shapefiles/performance/type=fixed/year=2025/quarter=2/2025-04-01_performance_fixed_tiles.zip"
DATA_DIR = Path(__file__).parent / "data"
FALLBACK_RADIUS_METERS = 50000

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def download_shapefile():
    """Downloads and unzips the Ookla shapefile, dynamically finding the .shp file."""
    DATA_DIR.mkdir(exist_ok=True)
    zip_path = DATA_DIR / "ookla_data.zip"
    
    shapefiles_in_dir = list(DATA_DIR.glob("*.shp"))
    if shapefiles_in_dir:
        print(f"Shapefile found: {shapefiles_in_dir[0]}. Skipping download.")
        return shapefiles_in_dir[0]

    print(f"Downloading Ookla data from {OOKLA_DATA_URL}...")
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.get(OOKLA_DATA_URL)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)

    print("Unzipping data...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(DATA_DIR)
    
    os.remove(zip_path)
    print("Download and extraction complete.")
    
    shapefiles_in_dir = list(DATA_DIR.glob("*.shp"))
    if not shapefiles_in_dir:
        raise FileNotFoundError(f"No .shp file found in the extracted data in {DATA_DIR}")
    
    return shapefiles_in_dir[0]

async def fetch_and_save_scores(session: AsyncSession):
    """Pass 1: Ingests Ookla data and saves raw internet speed scores for all cities."""
    print("--- PASS 1: Fetching and saving raw internet speed scores ---")
    
    shapefile_path = await download_shapefile()
    if not shapefile_path:
        return

    print("Loading Ookla tile data into memory...")
    ookla_gdf = gpd.read_file(shapefile_path)
    print(f"Loaded {len(ookla_gdf)} data tiles.")

    stmt = select(City)
    result = await session.execute(stmt)
    cities = result.scalars().all()
    if not cities:
        print("No cities found in the database.")
        return
    
    print(f"Preparing {len(cities)} cities for processing...")
    city_df = pd.DataFrame([{"id": c.id, "name": c.name, "latitude": c.latitude, "longitude": c.longitude} for c in cities])
    city_gdf = gpd.GeoDataFrame(
        city_df, geometry=gpd.points_from_xy(city_df.longitude, city_df.latitude)
    )
    city_gdf.set_crs("EPSG:4326", inplace=True)

    print("Re-projecting coordinates for accurate distance calculations...")
    projected_crs = "EPSG:3395"
    ookla_gdf = ookla_gdf.to_crs(projected_crs)
    city_gdf = city_gdf.to_crs(projected_crs)

    print("Performing spatial join to match cities directly within a data tile...")
    cities_with_speed = gpd.sjoin(city_gdf, ookla_gdf, how="inner", predicate="within")
    print(f"Successfully matched {len(cities_with_speed)} cities directly.")

    matched_ids = set(cities_with_speed['id'])
    unmatched_cities_gdf = city_gdf[~city_gdf['id'].isin(matched_ids)].copy()
    print(f"Identified {len(unmatched_cities_gdf)} unmatched cities. Applying nearest neighbor fallback...")

    fallback_join = gpd.sjoin_nearest(
        unmatched_cities_gdf,
        ookla_gdf,
        how="left",
        max_distance=FALLBACK_RADIUS_METERS
    )
    fallback_join.drop_duplicates(subset=['id'], inplace=True)
    
    fallback_scores = {}
    for _, row in fallback_join.iterrows():
        if pd.notna(row['index_right']):
            fallback_scores[row['id']] = row['avg_d_kbps']
    
    print(f"Calculated fallback scores for {len(fallback_scores)} unmatched cities.")

    attribute_name = CityAttributeName.INTERNET_SPEED
    stmt_existing = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
    result_existing = await session.execute(stmt_existing)
    existing_attrs_map = {attr.city_id: attr for attr in result_existing.scalars().all()}
    
    records_to_upsert = []
    
    for _, row in cities_with_speed.iterrows():
        records_to_upsert.append({"city_id": row['id'], "raw_value": row['avg_d_kbps'] / 1000.0})

    for city_id, avg_speed in fallback_scores.items():
        records_to_upsert.append({"city_id": city_id, "raw_value": avg_speed / 1000.0})

    cities_with_any_score = matched_ids.union(fallback_scores.keys())
    truly_unmatched_ids = set(city_df['id']) - cities_with_any_score
    for city_id in truly_unmatched_ids:
            records_to_upsert.append({"city_id": city_id, "raw_value": 0.0})
    
    print(f"Will assign a score of 0 to the remaining {len(truly_unmatched_ids)} cities.")

    for record in records_to_upsert:
        city_id = record['city_id']
        raw_score = record['raw_value']
        
        if city_id in existing_attrs_map:
            attr = existing_attrs_map[city_id]
            attr.raw_value = raw_score
        else:
            attr = CityAttribute(
                city_id=city_id, attribute_name=attribute_name,
                raw_value=raw_score, normalized_score=0
            )
        session.add(attr)
    
    await session.commit()
    print(f"Database update complete for {len(records_to_upsert)} cities.")

async def normalize_all_scores(session: AsyncSession):
    """Pass 2: Reads all raw scores, applies log-normalization, and saves the final score."""
    print("\n--- PASS 2: Normalizing all internet speed scores using Logarithmic Transformation ---")
    
    attribute_name = CityAttributeName.INTERNET_SPEED
    
    # --- MODIFIED: Select only scores > 0 to establish the normalization range ---
    stmt = select(CityAttribute.raw_value).where(
        CityAttribute.attribute_name == attribute_name,
        CityAttribute.raw_value > 0
    )
    result = await session.execute(stmt)
    raw_scores = result.scalars().all()

    if not raw_scores or len(raw_scores) < 2:
        print("Not enough non-zero scores found to normalize. Setting all scores to 0.")
        # Set all internet_speed attributes to a normalized score of 0 if not enough data
        all_attributes_stmt = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
        all_attributes_result = await session.execute(all_attributes_stmt)
        for attr in all_attributes_result.scalars().all():
            attr.normalized_score = 0.0
        await session.commit()
        return

    # Use np.log1p which calculates log(1 + x) to handle scores gracefully.
    log_scores = [np.log1p(score) for score in raw_scores]
    
    min_log_score = min(log_scores)
    max_log_score = max(log_scores)
    print(f"Log-transformed score range: Min={min_log_score:.2f}, Max={max_log_score:.2f}")

    if max_log_score == min_log_score:
        print("All non-zero raw values are effectively the same. Setting their score to 0.5.")
    
    # --- MODIFIED: Loop through all attributes to update them ---
    all_attributes_stmt = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
    all_attributes_result = await session.execute(all_attributes_stmt)
    
    update_count = 0
    for attr in all_attributes_result.scalars().all():
        # Check if the city has a valid raw score > 0
        if attr.raw_value is not None and attr.raw_value > 0:
            log_value = np.log1p(attr.raw_value)
            if max_log_score > min_log_score:
                # Apply Min-Max scaling to the LOG of the scores
                attr.normalized_score = (log_value - min_log_score) / (max_log_score - min_log_score)
            else:
                # If all non-zero values are the same, they are perfectly average.
                attr.normalized_score = 0.5
        else:
            # Assign a normalized score of 0 for cities with no data (raw_value is 0 or None)
            attr.normalized_score = 0.0
        session.add(attr)
        update_count += 1
        
    await session.commit()
    print(f"Successfully updated {update_count} attributes with log-normalized scores.")


async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session)

if __name__ == "__main__":
    asyncio.run(main())