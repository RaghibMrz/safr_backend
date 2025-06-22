# scripts/attributes/update_urban_greenery.py
import asyncio
import httpx
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import case, update, func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import numpy as np
from shapely.geometry import Polygon
from pyproj import Geod

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- DEBUG FLAG ---
# Set to True to print detailed debug information.
DEBUG = False

# --- Configuration ---
OVERPASS_API_ENDPOINTS = [
    # "https://overpass.kumi.systems/api/interpreter",
    # "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]
OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:180];
(
  way[leisure~"^(park|garden|nature_reserve|recreation_ground|village_green)$"](around:25000,{lat},{lon});
  relation[leisure~"^(park|garden|nature_reserve|recreation_ground|village_green)$"](around:25000,{lat},{lon});
  way[landuse~"^(forest|meadow)$"](around:25000,{lat},{lon});
  relation[landuse~"^(forest|meadow)$"](around:25000,{lat},{lon});
  way[natural~"^(wood|grassland)$"](around:25000,{lat},{lon});
  relation[natural~"^(wood|grassland)$"](around:25000,{lat},{lon});
);
>;
out body;
"""

PROGRESS_FILE = Path(__file__).parent / "urban_greenery_area_progress.log"
API_CONCURRENT_REQUESTS = 5

# --- Database Setup ---
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set.")
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def load_processed_cities():
    if not PROGRESS_FILE.exists():
        return set()
    with open(PROGRESS_FILE, 'r') as f:
        return {(line.strip()) for line in f if line.strip().isdigit()}

def log_processed_cities(geoname_ids: list[int]):
    with open(PROGRESS_FILE, 'a') as f:
        for geoname_id in geoname_ids:
            f.write(f"{geoname_id}\n")

def calculate_total_area_km2(overpass_data: dict) -> float:
    elements = overpass_data.get('elements', [])
    if DEBUG: print(f"  [DEBUG] `calculate_total_area_km2` received {len(elements)} elements.")
    if not elements:
        return 0.0

    nodes = {el['id']: (el['lon'], el['lat']) for el in elements if el['type'] == 'node'}
    ways = [el for el in elements if el['type'] == 'way']
    if DEBUG: print(f"  [DEBUG] Found {len(nodes)} nodes and {len(ways)} ways.")

    total_area_m2 = 0.0
    geod = Geod(ellps="WGS84")

    for el in ways:
        if 'nodes' in el and len(el['nodes']) > 2:
            node_ids = el['nodes']
            coords = [nodes.get(node_id) for node_id in node_ids]
            if not all(coords):
                continue
            try:
                poly = Polygon(coords)
                area, _ = geod.geometry_area_perimeter(poly)
                total_area_m2 += abs(area)
            except Exception:
                continue
    
    if DEBUG: print(f"  [DEBUG] Total calculated area: {total_area_m2:.2f} m².")
    return total_area_m2 / 1_000_000

async def fetch_and_save_scores(session: AsyncSession):
    """Fetches greenery geometry, calculates total area, and saves progress."""
    print("--- Fetching greenery geometry and calculating area scores ---")
    processed_ids = load_processed_cities()
    print(f"Loaded {len(processed_ids)} already processed cities.")

    stmt = select(City).where(City.geoname_id.not_in(processed_ids)).order_by(City.population.desc().nulls_last())
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    total_cities = len(cities_to_process)    
    if not cities_to_process:
        print("No new cities to process.")
        return
        
    print(f"Found {total_cities} new cities to process.")
    
    attribute_name = CityAttributeName.URBAN_GREENERY_AREA
    
    async with httpx.AsyncClient(timeout=240.0) as client:
        for i in range(0, total_cities, API_CONCURRENT_REQUESTS):
            batch = cities_to_process[i:i + API_CONCURRENT_REQUESTS]
            batch_num = i // API_CONCURRENT_REQUESTS + 1
            total_batches = (total_cities + API_CONCURRENT_REQUESTS - 1) // API_CONCURRENT_REQUESTS
            print(f"Processing batch {batch_num} of {total_batches} ({len(batch)} cities)...")

            endpoint_url = OVERPASS_API_ENDPOINTS[batch_num % len(OVERPASS_API_ENDPOINTS)]
            tasks = [
                client.post(endpoint_url, data={'data': OVERPASS_QUERY_TEMPLATE.format(lat=c.latitude, lon=c.longitude)})
                for c in batch
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            cities_to_log = []
            for city, response in zip(batch, responses):
                if isinstance(response, httpx.Response) and response.status_code == 200:
                    try:
                        data = response.json()
                        raw_score_km2 = calculate_total_area_km2(data)
                        print(f"  SUCCESS: Found {raw_score_km2:.2f} km² of greenery for {city.name}")
                        
                        attr = CityAttribute(
                            city_id=city.id, 
                            attribute_name=attribute_name, 
                            raw_value=raw_score_km2,
                            normalized_score=0.0
                        )
                        await session.merge(attr)
                        cities_to_log.append(city.geoname_id)

                    except Exception as e:
                        print(f"  FAILURE (Post-processing): {city.name} | Error: {e}")
                elif isinstance(response, httpx.Response) and response.status_code == 429:
                     print(f"  FAILURE (Rate Limited): Received 429 for {city.name}. The script will slow down. This batch may be retried on next run.")
                else:
                    status = response.status_code if isinstance(response, httpx.Response) else str(response.__class__.__name__)
                    print(f"  FAILURE (HTTP): {city.name} | Status: {status}")
            
            if cities_to_log:
                await session.commit()
                print(f"  Successfully committed {len(cities_to_log)} cities in batch.")

            if DEBUG and batch_num >= 1:
                print("\n[DEBUG] Script finished after one batch.")
                break

async def normalize_all_scores(session: AsyncSession):
    """Normalizes urban greenery area scores per unit city area using log transformation and min-max normalization."""
    print("--- Normalizing urban greenery area scores per city area using log transform ---")
    attribute_name = CityAttributeName.URBAN_GREENERY_AREA

    # Calculate greenery density and then apply log transformation
    # We need to compute min and max of these log-transformed densities first.
    # We directly select the log_density expression for aggregation.
    density_expression = CityAttribute.raw_value / City.area
    log_density_expression = func.ln(density_expression + 1)

    min_max_log_query = select(
        func.min(log_density_expression),
        func.max(log_density_expression)
    ).join(City).where(
        CityAttribute.attribute_name == attribute_name,
        City.area.isnot(None),
        City.area > 0
    )

    result = await session.execute(min_max_log_query)
    min_log_val, max_log_val = result.first()

    if min_log_val is None or max_log_val is None:
        print("No valid urban greenery or city area data found to normalize.")
        return

    if DEBUG:
        print(f"  [DEBUG] Min log density: {min_log_val:.4f}")
        print(f"  [DEBUG] Max log density: {max_log_val:.4f}")

    # Build the UPDATE statement
    # We update CityAttribute by joining implicitly with City to access City.area
    # The normalization formula is applied directly in the SQL values clause.
    if max_log_val == min_log_val:
        # All log densities are the same, set normalized score to 0.5
        update_stmt = update(CityAttribute).where(
            CityAttribute.attribute_name == attribute_name,
            CityAttribute.city_id == City.id, # Explicitly join CityAttribute with City in where clause
            City.area.isnot(None),
            City.area > 0
        ).values(
            normalized_score=0.5
        )
    else:
        # Calculate the log-transformed density for each row being updated
        # Apply min-max normalization: (X - X_min) / (X_max - X_min)
        update_stmt = update(CityAttribute).where(
            CityAttribute.attribute_name == attribute_name,
            CityAttribute.city_id == City.id, # Explicitly join CityAttribute with City in where clause
            City.area.isnot(None),
            City.area > 0
        ).values(
            normalized_score=case(
                (log_density_expression.is_(None), 0.0), # Handle cases where log_density might be null/invalid
                else_=(log_density_expression - min_log_val) / (max_log_val - min_log_val)
            )
        )

    # Execute the update statement
    await session.execute(update_stmt)
    await session.commit()
    print("Successfully normalized urban greenery scores.")


async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        # await fetch_and_save_scores(session)
        # If not debugging, run normalization after fetching is complete.
        if not DEBUG:
            await normalize_all_scores(session)

if __name__ == "__main__":
    asyncio.run(main())