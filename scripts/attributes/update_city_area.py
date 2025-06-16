# scripts/attributes/update_city_area.py
# FINAL IMPROVED VERSION WITH BETTER ESTIMATES
import asyncio
import httpx
import os
import random
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from unidecode import unidecode
from typing import Optional, Dict, List, Tuple
import time
import numpy as np
from pyproj import Transformer
import warnings
warnings.filterwarnings('ignore')

from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OVERPASS_API_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]
PROGRESS_FILE = Path(__file__).parent / "city_area_progress.log"
ERROR_LOG_FILE = Path(__file__).parent / "city_area_errors.log"

# Database Setup
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL: 
    raise ValueError("DATABASE_URL not set.")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# Known city areas for calibration (in km²)
KNOWN_CITY_AREAS = {
    # Europe
    "paris": 105,
    "london": 1572,
    "berlin": 891,
    "madrid": 604,
    "rome": 1285,
    "amsterdam": 219,
    "vienna": 414,
    "brussels": 162,
    "budapest": 525,
    "warsaw": 517,
    "barcelona": 101,
    "munich": 310,
    "milan": 182,
    "prague": 496,
    "stockholm": 188,
    "athens": 412,
    "lisbon": 100,
    "dublin": 115,
    "helsinki": 715,
    "oslo": 454,
    
    # Asia
    "tokyo": 2194,  # Tokyo Metropolis
    "delhi": 1484,  # NCT Delhi
    "shanghai": 6340,
    "beijing": 16411,
    "mumbai": 603,  # Greater Mumbai
    "istanbul": 5343,
    "karachi": 3780,
    "dhaka": 306,  # Dhaka City Corp
    "bangkok": 1568,
    "seoul": 605,
    "singapore": 734,
    "jakarta": 664,
    "manila": 42,  # City proper
    "kolkata": 185,
    "chennai": 426,
    "bangalore": 741,
    "hyderabad": 650,
    "hong kong": 1106,
    "taipei": 272,
    "osaka": 223,
    
    # Americas
    "new york": 784,  # 5 boroughs
    "los angeles": 1302,
    "chicago": 606,
    "houston": 1700,
    "phoenix": 1340,
    "philadelphia": 347,
    "san antonio": 1355,
    "san diego": 964,
    "dallas": 997,
    "san jose": 469,
    "austin": 828,
    "san francisco": 121,
    "seattle": 369,
    "denver": 401,
    "boston": 232,
    "mexico city": 1495,
    "sao paulo": 1521,
    "buenos aires": 203,
    "rio de janeiro": 1200,
    "lima": 2672,
    "bogota": 1775,
    "santiago": 641,
    "caracas": 777,
    "toronto": 630,
    "montreal": 365,
    "vancouver": 115,
    
    # Africa
    "cairo": 3085,
    "lagos": 1171,  # Lagos City
    "kinshasa": 9965,  # Province
    "johannesburg": 1645,
    "cape town": 2446,
    "nairobi": 696,
    "addis ababa": 527,
    "dar es salaam": 1393,
    "alexandria": 2679,
    "casablanca": 384,
    "accra": 225,
    "algiers": 1190,
    
    # Oceania
    "sydney": 12368,  # Greater Sydney
    "melbourne": 9993,  # Greater Melbourne
    "brisbane": 15842,
    "perth": 6418,
    "auckland": 1086,
    "adelaide": 3258,
    "wellington": 290,
}

# --- Helper Functions ---
def load_processed_cities() -> set[str]:
    if not PROGRESS_FILE.exists(): 
        return set()
    with open(PROGRESS_FILE, 'r') as f:
        return {line.strip() for line in f if line.strip()}

def log_processed_city(geoname_id: str):
    with open(PROGRESS_FILE, 'a') as f:
        f.write(f"{geoname_id}\n")

def log_error(city_name: str, geoname_id: str, error: str):
    with open(ERROR_LOG_FILE, 'a') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {city_name} ({geoname_id}): {error}\n")

def get_city_key(city_name: str) -> str:
    """Get standardized city key for lookup."""
    # Remove common suffixes and clean
    name = city_name.lower()
    for suffix in [' city', '-si', ' metropolitan', ' district', ' province']:
        name = name.replace(suffix, '')
    name = name.split(',')[0].strip()
    name = name.split('(')[0].strip()
    return name

def get_calibrated_density(city: City) -> float:
    """Get density calibrated from known city areas."""
    city_key = get_city_key(city.name)
    
    # If we have exact data for this city, use it
    if city_key in KNOWN_CITY_AREAS:
        known_area = KNOWN_CITY_AREAS[city_key]
        if city.population and city.population > 0:
            return city.population / known_area
    
    # Otherwise, find similar cities in the region
    lat, lon = city.latitude, city.longitude
    
    # Get region
    if lat > 35 and -10 <= lon <= 40:  # Europe
        region_cities = ["london", "paris", "berlin", "madrid", "rome"]
        base_density = 3500
    elif lat > 20 and lon > 60:  # Asia
        if lon > 120:  # East Asia
            region_cities = ["tokyo", "seoul", "shanghai", "beijing", "osaka"]
            base_density = 8000
        elif lat < 25:  # Southeast Asia
            region_cities = ["bangkok", "jakarta", "manila", "singapore"]
            base_density = 10000
        else:  # South Asia
            region_cities = ["delhi", "mumbai", "dhaka", "karachi", "kolkata"]
            base_density = 15000
    elif 25 <= lat <= 50 and -130 <= lon <= -60:  # North America
        region_cities = ["new york", "los angeles", "chicago", "houston", "toronto"]
        base_density = 1500
    elif lat < -20 and lon > 110:  # Australia/Oceania
        region_cities = ["sydney", "melbourne", "brisbane", "perth", "auckland"]
        base_density = 500
    elif lat < 0 and -80 <= lon <= -35:  # South America
        region_cities = ["sao paulo", "buenos aires", "rio de janeiro", "lima", "bogota"]
        base_density = 8000
    elif -35 <= lat <= 35 and -20 <= lon <= 50:  # Africa
        region_cities = ["cairo", "lagos", "johannesburg", "nairobi", "kinshasa"]
        base_density = 4000
    else:
        return base_density if 'base_density' in locals() else 3000
    
    # Calculate average density from known cities in region
    densities = []
    for rc in region_cities:
        if rc in KNOWN_CITY_AREAS:
            # Use typical population for calibration
            pop_estimates = {
                "london": 9000000, "paris": 2200000, "berlin": 3700000,
                "tokyo": 14000000, "delhi": 33000000, "mumbai": 20000000,
                "new york": 8300000, "sydney": 5300000, "sao paulo": 12000000,
                "cairo": 10000000, "lagos": 15000000
            }
            if rc in pop_estimates:
                densities.append(pop_estimates[rc] / KNOWN_CITY_AREAS[rc])
    
    if densities:
        avg_density = np.median(densities)
        
        # Adjust by city size
        if city.population > 10_000_000:
            return avg_density * 1.2
        elif city.population > 5_000_000:
            return avg_density
        elif city.population > 1_000_000:
            return avg_density * 0.7
        else:
            return avg_density * 0.4
    
    return base_density

def estimate_area_improved(city: City) -> float:
    """Improved area estimation using calibrated data."""
    if not city.population or city.population < 1000:
        return 10.0
    
    # Check if we have exact data
    city_key = get_city_key(city.name)
    if city_key in KNOWN_CITY_AREAS:
        known_area = KNOWN_CITY_AREAS[city_key]
        # Allow some variance for population changes
        return known_area * (1 + 0.1 * np.log10(city.population / 1_000_000))
    
    # Get calibrated density
    density = get_calibrated_density(city)
    
    # Special adjustments
    city_name_lower = city.name.lower()
    
    # Metropolitan areas tend to be larger
    if any(word in city_name_lower for word in ['greater', 'metro', 'region']):
        density *= 0.3
    
    # City proper tends to be denser
    elif any(word in city_name_lower for word in ['city proper', 'urban', 'downtown']):
        density *= 2.0
    
    # Capital adjustments
    if hasattr(city, 'is_capital') and city.is_capital:
        if city.population < 1_000_000:
            density *= 0.5  # Small capitals often include rural areas
        else:
            density *= 0.8  # Large capitals have government districts
    
    # Port cities
    if any(word in city_name_lower for word in ['port', 'porto', 'harbor', 'harbour']):
        density *= 0.7
    
    estimated_area = city.population / density
    
    # Apply reasonable bounds based on population
    if city.population > 10_000_000:
        min_area = 300    # Even hyperdense cities need space
        max_area = 20000  # Largest admin areas
    elif city.population > 1_000_000:
        min_area = 50
        max_area = 5000
    elif city.population > 100_000:
        min_area = 10
        max_area = 1000
    else:
        min_area = 5
        max_area = 200
    
    return np.clip(estimated_area, min_area, max_area)

async def get_city_area_fast(client: httpx.AsyncClient, city: City) -> Optional[float]:
    """Get city area with efficient Overpass query."""
    # Clean city name
    name_clean = unidecode(city.name).split(',')[0].split('(')[0].strip()
    
    # Single comprehensive query
    query = f'''
[out:json][timeout:30];
// Find administrative boundaries containing or near the city
(
  // Method 1: Direct name search at various admin levels
  relation["boundary"="administrative"]["admin_level"~"^[4-9]|10$"]["name"~"^{name_clean}",i](around:50000,{city.latitude},{city.longitude});
  // Method 2: Containing the coordinate point
  is_in({city.latitude},{city.longitude})->.a;
  relation["boundary"="administrative"]["admin_level"~"^[4-9]|10$"](pivot.a);
);
out tags bb;
'''
    
    try:
        endpoint = random.choice(OVERPASS_API_ENDPOINTS)
        response = await client.post(
            endpoint,
            data={'data': query},
            timeout=35.0
        )
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        elements = data.get('elements', [])
        
        if not elements:
            return None
        
        # Find best matching relation
        candidates = []
        name_lower = name_clean.lower()
        
        for elem in elements:
            if elem['type'] != 'relation':
                continue
                
            tags = elem.get('tags', {})
            admin_level = int(tags.get('admin_level', '99'))
            name = tags.get('name', '') or tags.get('name:en', '')
            
            if not name:
                continue
            
            # Calculate match score
            elem_name_lower = name.lower()
            
            # Perfect match
            if name_lower == elem_name_lower:
                score = 0 + admin_level * 0.01
            # Contains match
            elif name_lower in elem_name_lower or elem_name_lower in name_lower:
                score = 1 + admin_level * 0.01
            # Skip if no reasonable match
            else:
                continue
                
            # Get area from bounding box
            bounds = elem.get('bounds', {})
            if bounds:
                lat_span = bounds['maxlat'] - bounds['minlat']
                lon_span = bounds['maxlon'] - bounds['minlon']
                
                # Convert to km (approximate)
                lat_km = lat_span * 111.0
                lon_km = lon_span * 111.0 * np.cos(np.radians(city.latitude))
                
                # Bounding box area
                bbox_area = lat_km * lon_km
                
                # Admin boundaries typically use 50-80% of their bbox
                # Higher admin levels tend to be more irregular
                if admin_level <= 4:
                    fill_factor = 0.6
                elif admin_level <= 6:
                    fill_factor = 0.65
                elif admin_level <= 8:
                    fill_factor = 0.7
                else:
                    fill_factor = 0.75
                
                estimated_area = bbox_area * fill_factor
                
                candidates.append({
                    'name': name,
                    'level': admin_level,
                    'area': estimated_area,
                    'score': score
                })
        
        if not candidates:
            return None
        
        # Sort by score (best match first)
        candidates.sort(key=lambda x: x['score'])
        best = candidates[0]
        
        print(f"    Found: {best['name']} (L{best['level']}) ~{best['area']:.0f} km²")
        return best['area']
        
    except Exception as e:
        print(f"    Query error: {str(e)[:50]}")
        return None

def validate_area(overpass_area: Optional[float], pop_estimate: float, city: City) -> Tuple[float, str]:
    """Validate and choose the best area estimate with improved logic."""
    if overpass_area is None:
        return pop_estimate, "Population estimate"
    
    # Check if it's a known city
    city_key = get_city_key(city.name)
    if city_key in KNOWN_CITY_AREAS:
        known_area = KNOWN_CITY_AREAS[city_key]
        # If Overpass is within 50% of known value, trust it
        if 0.5 <= (overpass_area / known_area) <= 2.0:
            return overpass_area, "Overpass (validated)"
    
    # Calculate ratio
    ratio = overpass_area / pop_estimate if pop_estimate > 0 else float('inf')
    
    # More flexible bounds based on city characteristics
    if city.population > 10_000_000:
        # Megacities can have huge variations
        lower_bound, upper_bound = 0.1, 20.0
    elif city.population > 5_000_000:
        lower_bound, upper_bound = 0.15, 15.0
    elif city.population > 1_000_000:
        lower_bound, upper_bound = 0.2, 10.0
    else:
        lower_bound, upper_bound = 0.25, 8.0
    
    # Additional checks
    if lower_bound <= ratio <= upper_bound:
        # Sanity checks on absolute size
        if overpass_area < 1.0 and city.population > 50000:
            return pop_estimate, "Population estimate (area too small)"
        elif overpass_area > 50000:  # Larger than Belgium
            return pop_estimate, "Population estimate (area unrealistic)"
        else:
            return overpass_area, f"Overpass (ratio: {ratio:.1f})"
    else:
        # If Overpass seems wrong, use the better estimate
        if ratio < lower_bound:
            # Overpass area too small - might be district not city
            # Check if population estimate is more reasonable
            if pop_estimate > overpass_area * 2:
                return pop_estimate, f"Population estimate (Overpass too small: {overpass_area:.0f} km²)"
        return pop_estimate, f"Population estimate (ratio {ratio:.1f} out of range)"

async def process_batch(cities: List[City], session: AsyncSession, client: httpx.AsyncClient):
    """Process a batch of cities efficiently."""
    attribute_name = CityAttributeName.CITY_AREA
    
    for city in cities:
        print(f"\n{city.name} (Pop: {city.population:,})", end='', flush=True)
        
        try:
            # Get estimates
            start_time = time.time()
            overpass_area = await get_city_area_fast(client, city)
            query_time = time.time() - start_time
            
            pop_estimate = estimate_area_improved(city)
            
            # Validate and choose
            final_area, method = validate_area(overpass_area, pop_estimate, city)
            
            # Show what we're using
            if "Overpass" in method:
                print(f" → {final_area:.0f} km² ({method}, {query_time:.1f}s)")
            else:
                if overpass_area:
                    print(f" → {final_area:.0f} km² ({method})")
                else:
                    print(f" → {final_area:.0f} km² (Est)")
            
            # Save to database
            stmt = select(CityAttribute).where(
                CityAttribute.city_id == city.id,
                CityAttribute.attribute_name == attribute_name
            )
            attr = (await session.execute(stmt)).scalars().first()
            
            notes = {
                "method": method,
                "overpass_area": overpass_area,
                "population_estimate": pop_estimate,
                "final_area": final_area,
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            if attr:
                attr.raw_value = final_area
                attr.normalized_score = final_area
                attr.notes = notes
            else:
                attr = CityAttribute(
                    city_id=city.id,
                    attribute_name=attribute_name,
                    raw_value=final_area,
                    normalized_score=final_area,
                    notes=notes
                )
                session.add(attr)
            
            await session.commit()
            log_processed_city(city.geoname_id)
            
        except Exception as e:
            print(f" → ERROR: {str(e)[:50]}")
            log_error(city.name, city.geoname_id, str(e))
            log_processed_city(city.geoname_id)
        
        # Rate limiting
        await asyncio.sleep(0.5)

async def main():
    """Main processing function."""
    processed_ids = load_processed_cities()
    print(f"Resuming... {len(processed_ids)} already processed.")
    
    async with AsyncSessionLocal() as session:
        # Get unprocessed cities
        stmt = (
            select(City)
            .where(City.geoname_id.notin_(processed_ids))
            .order_by(City.population.desc().nulls_last())
        )
        
        result = await session.execute(stmt)
        cities_to_process = result.scalars().all()
        
        total_cities = len(cities_to_process)
        print(f"Processing {total_cities} cities...\n")
        
        if not cities_to_process:
            return
        
        # Process in batches
        batch_size = 20
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=40.0) as client:
            for i in range(0, total_cities, batch_size):
                batch = cities_to_process[i:i + batch_size]
                batch_start = time.time()
                
                print(f"\n--- Batch {i//batch_size + 1} ({i+1}-{min(i+batch_size, total_cities)} of {total_cities}) ---")
                
                await process_batch(batch, session, client)
                
                # Stats
                batch_time = time.time() - batch_start
                total_time = time.time() - start_time
                avg_time = total_time / (i + len(batch))
                remaining = (total_cities - i - len(batch)) * avg_time
                
                print(f"\nBatch: {batch_time:.1f}s, Avg: {avg_time:.1f}s/city, ETA: {remaining/60:.1f} min")
                
                # Pause between batches
                if i + batch_size < total_cities:
                    await asyncio.sleep(2.0)
        
        print(f"\n\nComplete! Processed {total_cities} cities in {(time.time() - start_time)/60:.1f} minutes")

if __name__ == "__main__":
    asyncio.run(main())