# scripts/attributes/update_city_area.py
import asyncio
import httpx
import os
import random
import json
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from unidecode import unidecode
from typing import Optional, Dict, List, Tuple, Union
import time
import numpy as np
from shapely.geometry import shape, Point, Polygon, MultiPolygon, mapping
from shapely.ops import transform, unary_union
from shapely.validation import make_valid
import pyproj
from functools import partial
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OVERPASS_API_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter"
]
PROGRESS_FILE = Path(__file__).parent / "city_area_progress.log"
ERROR_LOG_FILE = Path(__file__).parent / "city_area_errors.log"

# Database Setup
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL: 
    raise ValueError("DATABASE_URL not set.")

engine: Engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# --- Helper Functions ---
def load_processed_cities() -> set[str]:
    """Loads the set of already processed geoname_ids from the progress log."""
    if not PROGRESS_FILE.exists(): 
        return set()
    with open(PROGRESS_FILE, 'r') as f:
        return {line.strip() for line in f if line.strip()}

def log_processed_city(geoname_id: str):
    """Appends a geoname_id to the progress log."""
    with open(PROGRESS_FILE, 'a') as f:
        f.write(f"{geoname_id}\n")

def log_error(city_name: str, geoname_id: str, error: str):
    """Logs errors to a separate error file for debugging."""
    with open(ERROR_LOG_FILE, 'a') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {city_name} ({geoname_id}): {error}\n")

def get_region_and_density(latitude: float, longitude: float) -> Tuple[str, Dict[str, float]]:
    """
    Determines the region and provides density ranges based on coordinates.
    Returns (region_name, density_dict)
    """
    # More nuanced regional classification
    if latitude > 35 and -10 <= longitude <= 40:  # Europe
        return "Europe", {"high": 10000, "medium": 5000, "low": 2500, "very_low": 1000}
    elif latitude > 20 and longitude > 60:  # Asia
        if longitude > 120:  # East Asia (Japan, Korea, Eastern China)
            return "East Asia", {"high": 15000, "medium": 8000, "low": 4000, "very_low": 2000}
        else:  # South/Southeast Asia
            return "South Asia", {"high": 12000, "medium": 6000, "low": 3000, "very_low": 1500}
    elif 25 <= latitude <= 50 and -130 <= longitude <= -60:  # North America
        return "North America", {"high": 5000, "medium": 2500, "low": 1200, "very_low": 600}
    elif latitude < -20 and longitude > 110:  # Australia/Oceania
        return "Oceania", {"high": 4000, "medium": 2000, "low": 800, "very_low": 400}
    elif latitude < 0 and -80 <= longitude <= -35:  # South America
        return "South America", {"high": 12000, "medium": 6000, "low": 3000, "very_low": 1500}
    elif -35 <= latitude <= 35 and -20 <= longitude <= 50:  # Africa
        return "Africa", {"high": 8000, "medium": 4000, "low": 2000, "very_low": 1000}
    else:
        return "Other", {"high": 6000, "medium": 3000, "low": 1500, "very_low": 750}

def estimate_area_from_population_advanced(city: City) -> float:
    """
    Advanced population-based area estimation with regional and city-size adjustments.
    Returns area in square kilometers.
    """
    if not city.population or city.population < 1000:
        return 10.0  # Default for very small places
    
    population = city.population
    region, density_ranges = get_region_and_density(city.latitude, city.longitude)
    
    # Determine density tier based on population
    if population > 5_000_000:
        density = density_ranges["high"]
    elif population > 1_000_000:
        density = density_ranges["medium"]
    elif population > 100_000:
        density = density_ranges["low"]
    else:
        density = density_ranges["very_low"]
    
    # Special adjustments for known patterns
    city_name_lower = city.name.lower()
    
    # Capital cities tend to be less dense (more government buildings, parks)
    if hasattr(city, 'is_capital') and city.is_capital:
        density *= 0.7
    
    # Port cities often have industrial areas
    if any(word in city_name_lower for word in ['port', 'porto', 'harbor', 'harbour']):
        density *= 0.8
    
    # New World cities tend to be less dense
    if region in ["North America", "Oceania"] and population < 5_000_000:
        density *= 0.6
    
    # Asian megacities are extremely dense
    if region in ["East Asia", "South Asia"] and population > 5_000_000:
        density *= 1.3
    
    # African cities often have lower administrative densities
    if region == "Africa" and population > 1_000_000:
        density *= 0.8
    
    estimated_area = population / density
    
    # Apply bounds based on population
    # No city should be smaller than ~5 km² or larger than ~5000 km²
    min_area = max(5.0, population / 50000)  # Even super dense can't exceed 50k/km²
    max_area = min(5000.0, population / 200)  # Even sprawling cities have >200/km²
    
    estimated_area = np.clip(estimated_area, min_area, max_area)
    
    print(f"  Population estimate: {population:,} people in {region} → {estimated_area:.1f} km² (density: {density:.0f}/km²)")
    return estimated_area

def repair_polygon(geom: Union[Polygon, MultiPolygon]) -> Optional[Union[Polygon, MultiPolygon]]:
    """
    Attempts to repair an invalid polygon using various strategies.
    """
    if geom.is_valid:
        return geom
    
    try:
        # Strategy 1: Buffer by 0
        fixed = geom.buffer(0)
        if fixed.is_valid and not fixed.is_empty:
            return fixed
    except:
        pass
    
    try:
        # Strategy 2: Use make_valid (requires Shapely 1.8+)
        fixed = make_valid(geom)
        if fixed.is_valid and not fixed.is_empty:
            return fixed
    except:
        pass
    
    try:
        # Strategy 3: Convex hull (last resort - will lose detail)
        fixed = geom.convex_hull
        if fixed.is_valid and not fixed.is_empty:
            print("    Warning: Using convex hull - area may be overestimated")
            return fixed
    except:
        pass
    
    return None

def calculate_area_from_polygon(polygon: Union[Polygon, MultiPolygon], lat: float) -> Optional[float]:
    """Calculate area in km² using appropriate equal-area projection."""
    try:
        # Handle MultiPolygon
        if isinstance(polygon, MultiPolygon):
            total_area = 0
            for poly in polygon.geoms:
                area = calculate_area_from_polygon(poly, lat)
                if area:
                    total_area += area
            return total_area if total_area > 0 else None
        
        # Use Albers Equal Area projection centered on the location
        proj_string = (f"+proj=aea +lat_1={lat-5} +lat_2={lat+5} +lat_0={lat} "
                      f"+lon_0={polygon.centroid.x} +datum=WGS84 +units=m +no_defs")
        
        transformer = pyproj.Transformer.from_crs('EPSG:4326', proj_string, always_xy=True)
        polygon_projected = transform(transformer.transform, polygon)
        
        area_m2 = abs(polygon_projected.area)
        area_km2 = area_m2 / 1_000_000
        
        # Sanity check
        if area_km2 < 0.1 or area_km2 > 50000:
            print(f"    Warning: Calculated area {area_km2:.1f} km² seems unrealistic")
            return None
            
        return area_km2
    except Exception as e:
        print(f"    Area calculation error: {str(e)}")
        return None

def extract_polygon_from_overpass(element: dict) -> Optional[Union[Polygon, MultiPolygon]]:
    """Extract polygon from Overpass API response element with improved handling."""
    try:
        if element.get('type') == 'relation' and element.get('members'):
            # Collect coordinates by role
            outer_coords = []
            inner_coords_list = []
            
            for member in element['members']:
                if not member.get('geometry'):
                    continue
                    
                coords = [(p['lon'], p['lat']) for p in member['geometry']]
                if len(coords) < 4:  # Need at least 4 points for a valid ring
                    continue
                
                # Ensure the ring is closed
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                
                role = member.get('role', 'outer')
                if role == 'inner':
                    inner_coords_list.append(coords)
                else:  # 'outer' or empty role
                    outer_coords.extend(coords[:-1])  # Remove duplicate closing point
            
            if outer_coords:
                # Ensure outer ring is closed
                if len(outer_coords) > 0 and outer_coords[0] != outer_coords[-1]:
                    outer_coords.append(outer_coords[0])
                
                if len(outer_coords) >= 4:
                    try:
                        # Create polygon with holes if inner rings exist
                        if inner_coords_list:
                            poly = Polygon(outer_coords, holes=inner_coords_list)
                        else:
                            poly = Polygon(outer_coords)
                        
                        # Repair if needed
                        if not poly.is_valid:
                            poly = repair_polygon(poly)
                        
                        return poly
                    except Exception as e:
                        print(f"    Polygon creation error: {str(e)}")
                        # Try without holes
                        try:
                            poly = Polygon(outer_coords)
                            if not poly.is_valid:
                                poly = repair_polygon(poly)
                            return poly
                        except:
                            pass
                            
        elif element.get('type') == 'way' and element.get('geometry'):
            coords = [(p['lon'], p['lat']) for p in element['geometry']]
            if len(coords) >= 3:
                # Ensure closed
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                    
                try:
                    poly = Polygon(coords)
                    if not poly.is_valid:
                        poly = repair_polygon(poly)
                    return poly
                except Exception as e:
                    print(f"    Way polygon error: {str(e)}")
                        
    except Exception as e:
        print(f"    Polygon extraction error: {str(e)}")
    
    return None

async def get_area_from_overpass_improved(client: httpx.AsyncClient, city: City) -> Optional[float]:
    """
    Improved Overpass query with better error handling and multiple strategies.
    """
    # Priority order for city proper boundaries
    admin_levels = ['8', '9', '7', '6', '10', '5', '4']
    
    # Try different name variations
    name_variations = [
        city.name,
        unidecode(city.name),
        city.name.split(',')[0].strip(),  # Remove any suffixes
        city.name.split('(')[0].strip(),   # Remove parenthetical info
        city.name.replace("'", ""),        # Remove apostrophes
        city.name.replace("-", " "),       # Replace hyphens with spaces
    ]
    
    # Remove duplicates while preserving order
    name_variations = list(dict.fromkeys(name_variations))
    
    for admin_level in admin_levels:
        for name_variant in name_variations[:2]:  # Only try first 2 variations to save time
            print(f"  Trying admin_level={admin_level}, name='{name_variant}'...")
            
            # Simplified query to reduce complexity
            query = f"""
            [out:json][timeout:60];
            (
              // Direct boundary search
              relation["boundary"="administrative"]["admin_level"="{admin_level}"]
                      ["name"~"^{name_variant}$",i]
                      (around:50000,{city.latitude},{city.longitude});
              
              // Fallback to looser name matching
              relation["boundary"="administrative"]["admin_level"="{admin_level}"]
                      ["name"~"{name_variant}",i]
                      ({city.latitude-0.5},{city.longitude-0.5},{city.latitude+0.5},{city.longitude+0.5});
            );
            out body;
            >;
            out skel qt;
            """
            
            try:
                # Rotate through endpoints
                endpoint = random.choice(OVERPASS_API_ENDPOINTS)
                response = await client.post(
                    endpoint,
                    data={'data': query},
                    timeout=90.0  # Increased timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('elements'):
                        # Build a map of nodes
                        nodes = {}
                        ways = {}
                        relations = []
                        
                        for elem in data['elements']:
                            if elem['type'] == 'node':
                                nodes[elem['id']] = (elem['lon'], elem['lat'])
                            elif elem['type'] == 'way':
                                ways[elem['id']] = elem
                            elif elem['type'] == 'relation':
                                relations.append(elem)
                        
                        # Process relations
                        for relation in relations:
                            tags = relation.get('tags', {})
                            found_name = tags.get('name', 'Unknown')
                            
                            # Check if this is likely the right boundary
                            if name_variant.lower() not in found_name.lower():
                                continue
                            
                            print(f"    Found: '{found_name}'")
                            
                            # Try to build geometry from members
                            try:
                                outer_rings = []
                                inner_rings = []
                                
                                for member in relation.get('members', []):
                                    if member['type'] != 'way':
                                        continue
                                    
                                    way_id = member['ref']
                                    if way_id not in ways:
                                        continue
                                    
                                    way = ways[way_id]
                                    way_nodes = way.get('nodes', [])
                                    
                                    # Build coordinate list
                                    coords = []
                                    for node_id in way_nodes:
                                        if node_id in nodes:
                                            coords.append(nodes[node_id])
                                    
                                    if len(coords) >= 3:
                                        if member.get('role') == 'inner':
                                            inner_rings.append(coords)
                                        else:
                                            outer_rings.append(coords)
                                
                                if outer_rings:
                                    # Merge outer rings
                                    all_coords = []
                                    for ring in outer_rings:
                                        all_coords.extend(ring)
                                    
                                    if len(all_coords) >= 3:
                                        poly = Polygon(all_coords)
                                        if not poly.is_valid:
                                            poly = repair_polygon(poly)
                                        
                                        if poly and poly.is_valid:
                                            area = calculate_area_from_polygon(poly, city.latitude)
                                            if area and area > 0:
                                                print(f"    → Area: {area:.1f} km²")
                                                return area
                                
                            except Exception as e:
                                print(f"    Geometry building error: {str(e)}")
                
                # Rate limiting
                await asyncio.sleep(1.5)
                
            except httpx.TimeoutException:
                print(f"    Timeout on {endpoint}")
                await asyncio.sleep(3.0)
            except Exception as e:
                print(f"    Error: {str(e)}")
                await asyncio.sleep(2.0)
    
    return None

def apply_heuristic_validation(
    overpass_area: Optional[float],
    population_estimate: float,
    city: City
) -> Tuple[float, str]:
    """
    Apply smart heuristics to validate and choose the best area estimate.
    Returns (final_area, method_used)
    """
    if overpass_area is None:
        return population_estimate, "Population estimate (no boundary found)"
    
    # Calculate ratio
    ratio = overpass_area / population_estimate if population_estimate > 0 else float('inf')
    
    # Define acceptance criteria based on city size
    if city.population > 5_000_000:
        # Large cities: more tolerance for variation
        lower_bound, upper_bound = 0.2, 8.0
    elif city.population > 1_000_000:
        # Medium cities
        lower_bound, upper_bound = 0.25, 6.0
    elif city.population > 100_000:
        # Small cities
        lower_bound, upper_bound = 0.3, 5.0
    else:
        # Towns: tighter bounds
        lower_bound, upper_bound = 0.4, 4.0
    
    # Special cases
    if hasattr(city, 'is_capital') and city.is_capital and ratio > upper_bound:
        # Capitals often have larger administrative areas
        upper_bound *= 1.5
    
    # Validation
    if lower_bound <= ratio <= upper_bound:
        # Additional sanity checks
        if overpass_area < 1.0:
            return population_estimate, "Population estimate (area too small)"
        elif overpass_area > 10000.0 and city.population < 1_000_000:
            return population_estimate, "Population estimate (area too large for population)"
        else:
            return overpass_area, f"Overpass verified (ratio: {ratio:.2f})"
    else:
        # Log why it was rejected
        if ratio < lower_bound:
            reason = "too small"
        else:
            reason = "too large"
        return population_estimate, f"Population estimate (Overpass {reason}, ratio: {ratio:.2f})"

async def process_city_batch(cities: List[City], session: AsyncSession, client: httpx.AsyncClient):
    """Process a batch of cities with rate limiting."""
    attribute_name = CityAttributeName.CITY_AREA
    
    for city in cities:
        print(f"\n{'='*60}")
        print(f"Processing: {city.name} (ID: {city.geoname_id}, Pop: {city.population:,})")
        
        try:
            # 1. Get Overpass area
            overpass_area = await get_area_from_overpass_improved(client, city)
            
            # 2. Get population estimate
            pop_estimate = estimate_area_from_population_advanced(city)
            
            # 3. Apply heuristic validation
            final_area, method = apply_heuristic_validation(overpass_area, pop_estimate, city)
            
            print(f"\nResult: {final_area:.1f} km² ({method})")
            
            # 4. Save to database
            stmt = select(CityAttribute).where(
                CityAttribute.city_id == city.id,
                CityAttribute.attribute_name == attribute_name
            )
            attr = (await session.execute(stmt)).scalars().first()
            
            if attr:
                attr.raw_value = final_area
                attr.normalized_score = final_area
                attr.notes = {
                    "method": method,
                    "overpass_area": overpass_area,
                    "population_estimate": pop_estimate,
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                }
            else:
                attr = CityAttribute(
                    city_id=city.id,
                    attribute_name=attribute_name,
                    raw_value=final_area,
                    normalized_score=final_area,
                    notes={
                        "method": method,
                        "overpass_area": overpass_area,
                        "population_estimate": pop_estimate,
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                    }
                )
                session.add(attr)
            
            await session.commit()
            log_processed_city(city.geoname_id)
            
        except Exception as e:
            error_msg = f"Failed to process: {str(e)}"
            print(f"\nERROR: {error_msg}")
            log_error(city.name, city.geoname_id, error_msg)
            
            # Still log as processed to avoid retrying bad cities
            log_processed_city(city.geoname_id)

async def main():
    """Main function to process all cities."""
    processed_ids = load_processed_cities()
    print(f"Found {len(processed_ids)} already processed cities.")
    
    async with AsyncSessionLocal() as session:
        # Get unprocessed cities, prioritizing by population
        stmt = (
            select(City)
            .where(City.geoname_id.notin_(processed_ids))
            .order_by(City.population.desc().nulls_last())
        )
        
        result = await session.execute(stmt)
        cities_to_process = result.scalars().all()
        
        total_cities = len(cities_to_process)
        print(f"Found {total_cities} cities to process.")
        
        if not cities_to_process:
            print("No cities to process. Exiting.")
            return
        
        # Process in batches to manage memory and allow interruption
        batch_size = 10
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            for i in range(0, total_cities, batch_size):
                batch = cities_to_process[i:i + batch_size]
                print(f"\n{'#'*60}")
                print(f"Processing batch {i//batch_size + 1}/{(total_cities + batch_size - 1)//batch_size}")
                print(f"Cities {i + 1}-{min(i + batch_size, total_cities)} of {total_cities}")
                print(f"{'#'*60}")
                
                await process_city_batch(batch, session, client)
                
                # Longer pause between batches
                if i + batch_size < total_cities:
                    print(f"\nPausing between batches...")
                    await asyncio.sleep(5.0)
        
        print(f"\n{'='*60}")
        print(f"Processing complete! Processed {total_cities} cities.")
        print(f"Check {ERROR_LOG_FILE} for any errors.")

if __name__ == "__main__":
    asyncio.run(main())