# scripts/attributes/update_cost_of_living.py
"""
Cost of Living attribute calculator using OSM data + country GDP.
GDP data: IMF/World Bank 2023 actuals + 2024 estimates
Last updated: January 2025
"""
import asyncio
import httpx
import os
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
import json

# --- App-specific Imports ---
from safr_backend.models import City, CityAttribute
from safr_backend.constants import CityAttributeName

# --- Configuration ---
OVERPASS_API_URL = "https://overpass.private.coffee/api/interpreter"
PROGRESS_FILE = Path(__file__).parent / "cost_of_living_progress.log"

# Simplified query that captures ALL restaurants and hotels
# We'll analyze them in the scoring function
COST_INDICATORS_QUERY = """
[out:json][timeout:90];
(
  // ALL restaurants (we'll analyze tags later)
  nwr["amenity"="restaurant"](around:5000,{lat},{lon});
  
  // ALL cafes
  nwr["amenity"="cafe"](around:5000,{lat},{lon});
  
  // Fast food
  nwr["amenity"="fast_food"](around:5000,{lat},{lon});
  
  // ALL hotels (we'll check stars later)
  nwr["tourism"="hotel"](around:5000,{lat},{lon});
  
  // Budget accommodation
  nwr["tourism"~"^(hostel|motel|guest_house|apartment)$"](around:5000,{lat},{lon});
  
  // Shopping venues
  nwr["shop"~"^(supermarket|mall|department_store|boutique|jewelry|clothes)$"](around:5000,{lat},{lon});
  nwr["shop"~"^(convenience|kiosk|discount|second_hand|variety_store)$"](around:5000,{lat},{lon});
  
  // Markets - important in developing countries
  nwr["amenity"="marketplace"](around:5000,{lat},{lon});
  nwr["shop"="greengrocer"](around:5000,{lat},{lon});
  
  // Entertainment
  nwr["amenity"~"^(bar|pub|nightclub|cinema|theatre)$"](around:5000,{lat},{lon});
  nwr["leisure"~"^(fitness_centre|sports_centre|swimming_pool)$"](around:5000,{lat},{lon});
  
  // Banks and ATMs
  nwr["amenity"~"^(bank|atm)$"](around:5000,{lat},{lon});
);
out tags;
"""

# GDP data - hardcoded to avoid API dependency
# Source: IMF/World Bank 2023 actuals + 2024 estimates (most recent available)
# Note: 2024 data is still being finalized by major institutions
# The increases from 2023 reflect both economic growth and inflation
COUNTRY_GDP_PER_CAPITA = {
    # Major economies (2024 estimates)
    'US': 85373, 'CN': 13136, 'JP': 34554, 'DE': 54291, 'IN': 2731, 'GB': 51075,
    'FR': 47359, 'IT': 39580, 'BR': 11352, 'CA': 55326, 'KR': 34165, 'ES': 34896,
    'AU': 66592, 'MX': 14130, 'ID': 5271, 'NL': 64576, 'SA': 33147, 'TR': 13383,
    'CH': 102866, 'PL': 21898, 'BE': 56142, 'SE': 56625, 'IE': 112248, 'AR': 13709,
    'NO': 90532, 'AE': 51201, 'IL': 57488, 'AT': 58013, 'NG': 1699, 'EG': 3684,
    'DK': 71402, 'SG': 91733, 'MY': 12119, 'PH': 4081, 'ZA': 6485, 'CO': 7157,
    'BD': 2784, 'VN': 4623, 'CL': 17825, 'FI': 55127, 'RO': 19398, 'CZ': 33476,
    'PT': 29396, 'IQ': 5937, 'PE': 8252, 'GR': 24342, 'NZ': 50851, 'QA': 81400,
    'DZ': 5590, 'HU': 23104, 'KZ': 13773, 'KW': 34244, 'UA': 5037, 'MA': 4078,
    'EC': 6886, 'SK': 25423, 'ET': 1339, 'DO': 11278, 'KE': 2170, 'OM': 22639,
    'GT': 6029, 'BG': 15897, 'VE': 3800, 'AO': 2465, 'LU': 135605, 'CR': 17692,
    'PA': 19713, 'UY': 23339, 'HR': 22669, 'TZ': 1246, 'BY': 8074, 'LT': 29287,
    'SI': 34407, 'GH': 2447, 'RS': 12394, 'MM': 1264, 'JO': 4666, 'CI': 2687,
    'UG': 1065, 'CM': 1810, 'AZ': 7315, 'LV': 23482, 'BO': 3859, 'AF': 380,
    'NP': 1456, 'SV': 5677, 'PY': 6589, 'HN': 3389, 'EE': 31539, 'KH': 2571,
    'TT': 18537, 'BA': 8952, 'LA': 2167, 'CY': 34919, 'IS': 84594, 'SN': 1797,
    'ZW': 2085, 'GA': 8017, 'AL': 8755, 'GE': 8746, 'MK': 8924, 'MW': 635,
    'BW': 8164, 'MZ': 650, 'ML': 917, 'JM': 7033, 'NA': 4358, 'AM': 8638,
    'MG': 533, 'NI': 2765, 'MR': 2228, 'MN': 6248, 'MD': 5667, 'BJ': 1481,
    'NE': 676, 'RW': 1050, 'KG': 2073, 'TD': 717, 'TJ': 1221, 'BF': 925,
    'GN': 1614, 'HT': 1748, 'SO': 500, 'ME': 12507, 'TG': 1033, 'SL': 792,
    'LR': 803, 'CF': 518, 'ER': 400, 'BI': 239, 'TL': 1581, 'GM': 931,
    'GW': 990, 'LS': 957, 'ZM': 1395, 'GQ': 6907, 'MV': 13117, 'BN': 34469,
    'BH': 30367, 'CV': 5065, 'SZ': 3772, 'FJ': 6153, 'DJ': 3300, 'ST': 3052,
    'KM': 1640, 'SB': 2158, 'WS': 4510, 'TO': 4700, 'VU': 3636, 'FM': 4300,
    'KI': 2200, 'PW': 16600, 'MH': 6900, 'NR': 12500, 'TV': 6600, 'MT': 43610,
    # Special territories and small states
    'HK': 54756, 'MO': 65000, 'PR': 39000, 'NC': 36000, 'PF': 21000, 'BB': 24500,
    'BS': 36950, 'BZ': 7720, 'GY': 21000, 'SR': 5700, 'AD': 48500, 'LI': 187000,
    'MC': 248000, 'SM': 62000, 'VA': 35000, 'CW': 24000, 'AW': 33000, 'KY': 95000,
    'BM': 120000, 'TC': 30000, 'VG': 35000, 'GI': 70000, 'IM': 95000, 'JE': 60000,
    'GG': 65000, 'FO': 70000, 'GL': 60000, 'AI': 25000, 'FK': 80000, 'MS': 15000,
    # Some countries with limited data - using estimates
    'KP': 650, 'CU': 10000, 'IR': 4700, 'LY': 6500, 'SY': 1000, 'YE': 700,
    'SS': 300, 'PS': 3500, 'XK': 5500, 'TW': 35000, 'EH': 3000
}

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


def log_processed_city(geoname_id: str):
    with open(PROGRESS_FILE, 'a') as f:
        f.write(f"{geoname_id}\n")


def calculate_city_cost_score(osm_data, country_gdp):
    """
    Calculate a sophisticated cost score based on OSM data patterns.
    Returns: raw_score (0-100 where 0=cheapest, 100=most expensive)
    """
    # Initialize counters
    restaurants = {'high': 0, 'mid': 0, 'low': 0}
    hotels = {'luxury': 0, 'standard': 0, 'budget': 0}
    shops = {'high': 0, 'standard': 0, 'budget': 0}
    markets = 0
    cafes = 0
    bars = 0
    banks = 0
    
    # Lists of keywords that indicate expensive venues
    expensive_cuisines = ['french', 'italian', 'japanese', 'sushi', 'seafood', 'steak', 
                         'fusion', 'mediterranean', 'european', 'international', 'fine_dining']
    expensive_keywords = ['luxury', 'premium', 'exclusive', 'boutique', 'designer', 
                         'gourmet', 'artisan', 'organic', 'vegan', 'wine']
    budget_chains = ['mcdonald', 'burger king', 'kfc', 'subway', 'pizza hut', 
                    'domino', 'dunkin', 'tim horton', 'taco bell', 'wendy']
    premium_chains = ['starbucks', 'costa', 'pret', 'whole foods', 'waitrose']
    
    for element in osm_data:
        tags = element.get('tags', {})
        name = tags.get('name', '').lower()
        brand = tags.get('brand', '').lower()
        
        # Analyze restaurants
        if tags.get('amenity') == 'restaurant':
            cuisine = tags.get('cuisine', '').lower()
            
            # Check for expensive indicators
            if tags.get('michelin:stars'):
                restaurants['high'] += 3  # Michelin stars are very expensive
            elif any(c in cuisine for c in expensive_cuisines):
                restaurants['high'] += 1
            elif any(k in name or k in brand for k in expensive_keywords):
                restaurants['high'] += 1
            elif any(chain in name or chain in brand for chain in budget_chains):
                restaurants['low'] += 1  # Chain restaurants in developing countries
            elif tags.get('cuisine'):  # Has cuisine tag = usually better restaurant
                restaurants['mid'] += 1
            else:
                restaurants['low'] += 1  # Generic restaurant
        
        # Fast food is always budget
        elif tags.get('amenity') == 'fast_food':
            # Check if it's a known chain
            if any(chain in name or chain in brand for chain in budget_chains):
                restaurants['low'] += 1
            else:
                restaurants['low'] += 0.8  # Local fast food might be slightly better
        
        # Cafes (can vary widely)
        elif tags.get('amenity') == 'cafe':
            cafes += 1
            if any(chain in name or chain in brand for chain in premium_chains):
                restaurants['mid'] += 1  # Starbucks etc are pricier
            elif any(k in name or k in brand for k in expensive_keywords):
                restaurants['mid'] += 0.5
            else:
                restaurants['low'] += 0.3  # Most cafes are affordable
        
        # Hotels
        elif tags.get('tourism') == 'hotel':
            stars = tags.get('stars', '')
            rooms = tags.get('rooms', '')
            
            if stars in ['4', '5', '4S', '5S']:
                hotels['luxury'] += 1
            elif stars in ['3', '3S']:
                hotels['standard'] += 1
            elif stars in ['1', '2', '1S', '2S']:
                hotels['budget'] += 1
            elif any(k in name for k in expensive_keywords):
                hotels['luxury'] += 1
            elif rooms and rooms.isdigit() and int(rooms) > 100:  # Large hotels tend to be nicer
                hotels['standard'] += 1
            else:
                hotels['standard'] += 0.5  # Unknown hotel
        
        elif tags.get('tourism') in ['hostel', 'motel', 'guest_house']:
            hotels['budget'] += 1
        elif tags.get('tourism') == 'apartment':
            hotels['standard'] += 0.5  # Airbnb-style can vary
        
        # Shopping
        elif tags.get('shop') in ['boutique', 'jewelry', 'wine', 'fashion', 'clothes']:
            if any(k in name or k in brand for k in expensive_keywords):
                shops['high'] += 1.5
            else:
                shops['high'] += 0.5
        elif tags.get('shop') == 'mall':
            shops['high'] += 1  # Malls indicate modern retail
            shops['standard'] += 2  # But also have standard shops
        elif tags.get('shop') == 'department_store':
            shops['standard'] += 1
        elif tags.get('shop') == 'supermarket':
            shops['standard'] += 1
        elif tags.get('shop') in ['convenience', 'kiosk', 'discount', 'second_hand', 'variety_store']:
            shops['budget'] += 1
        
        # Markets are budget-friendly
        elif tags.get('amenity') == 'marketplace':
            markets += 1
            shops['budget'] += 2
        elif tags.get('shop') == 'greengrocer':
            markets += 0.5
        
        # Other indicators
        elif tags.get('amenity') in ['bar', 'pub', 'nightclub']:
            bars += 1
        elif tags.get('amenity') in ['bank', 'atm']:
            banks += 1
    
    # Calculate ratios
    total_restaurants = sum(restaurants.values())
    total_hotels = sum(hotels.values())
    total_shops = sum(shops.values())
    
    # Restaurant score (0-100)
    if total_restaurants > 5:  # Need minimum data
        restaurant_score = (
            (restaurants['high'] * 100 + restaurants['mid'] * 50) / 
            total_restaurants
        )
    else:
        restaurant_score = 25  # Low data = assume budget
    
    # Hotel score (0-100)
    if total_hotels > 2:
        hotel_score = (
            (hotels['luxury'] * 100 + hotels['standard'] * 50) / 
            total_hotels
        )
    else:
        hotel_score = 30  # Low data = assume budget
    
    # Shopping score (0-100)
    if total_shops > 5:
        shop_score = (
            (shops['high'] * 100 + shops['standard'] * 50) / 
            total_shops
        )
        # Markets reduce the shopping score
        market_reduction = min(markets * 2, 20)
        shop_score = max(0, shop_score - market_reduction)
    else:
        shop_score = 25
    
    # Banking/infrastructure bonus (more banks = more developed = more expensive)
    bank_bonus = min(banks * 0.5, 10)
    
    # Cafe culture bonus (many cafes = usually more expensive city)
    cafe_bonus = min(cafes * 0.3, 10)
    
    # Data quality factor (0-1)
    total_pois = len(osm_data)
    data_quality = min(total_pois / 200, 1.0)  # Good data at 200+ POIs
    
    # City score from OSM data
    city_osm_score = (
        restaurant_score * 0.4 +
        hotel_score * 0.3 +
        shop_score * 0.3 +
        bank_bonus +
        cafe_bonus
    )
    
    # GDP influence (always significant)
    gdp_score = min(country_gdp / 40000 * 100, 100)  # $40k GDP = score of 100
    
    # Combine scores
    # When data quality is low, rely more on GDP
    # When data quality is high, give more weight to OSM
    if data_quality < 0.3:
        final_score = gdp_score * 0.8 + city_osm_score * 0.2
    elif data_quality < 0.7:
        final_score = gdp_score * 0.6 + city_osm_score * 0.4
    else:
        final_score = gdp_score * 0.4 + city_osm_score * 0.6
    
    return max(0, min(100, final_score))  # Clamp to 0-100


async def fetch_and_save_scores(session: AsyncSession):
    """Fetches OSM data and calculates cost scores for each city."""
    print("--- Fetching and saving cost of living scores ---")
    
    processed_ids = load_processed_cities()
    print(f"Found {len(processed_ids)} already processed cities. Resuming...")

    stmt = select(City).where(City.geoname_id.notin_(processed_ids))
    result = await session.execute(stmt)
    cities_to_process = result.scalars().all()
    total_cities = len(cities_to_process)
    print(f"Found {total_cities} new cities to process.")

    if not cities_to_process:
        return

    attribute_name = CityAttributeName.COST_OF_LIVING
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, city in enumerate(cities_to_process):
            print(f"Processing city {i + 1} of {total_cities}: {city.name}, {city.country_code}")
            
            query = COST_INDICATORS_QUERY.format(lat=city.latitude, lon=city.longitude)
            
            try:
                response = await client.post(OVERPASS_API_URL, data=query)
                response.raise_for_status()
                
                osm_data = response.json().get("elements", [])
                country_gdp = COUNTRY_GDP_PER_CAPITA.get(city.country_code, 10000)  # Default fallback
                
                # Log if we're using fallback
                if city.country_code not in COUNTRY_GDP_PER_CAPITA:
                    print(f"  WARNING: No GDP data for {city.country_code}, using default $10,000")
                
                raw_score = calculate_city_cost_score(osm_data, country_gdp)
                
                print(f"  SUCCESS: Calculated cost score of {raw_score:.1f} from {len(osm_data)} POIs")
                print(f"  Country GDP: ${country_gdp}, Data points: {len(osm_data)}")
                
                # Store or update the attribute
                stmt_existing = select(CityAttribute).where(
                    CityAttribute.city_id == city.id,
                    CityAttribute.attribute_name == attribute_name
                )
                result_existing = await session.execute(stmt_existing)
                attr = result_existing.scalars().first()
                
                if attr:
                    attr.raw_value = raw_score
                else:
                    attr = CityAttribute(
                        city_id=city.id,
                        attribute_name=attribute_name,
                        raw_value=raw_score,
                        normalized_score=0  # Will be set in normalization pass
                    )
                session.add(attr)
                await session.commit()
                log_processed_city(city.geoname_id)

            except httpx.RequestError as e:
                print(f"  FAILURE: Network error for {city.name}. Error: {e}")
            except Exception as e:
                print(f"  FAILURE: Could not process {city.name}. Error: {e}")
                # Don't continue on database errors
                if "asyncpg" in str(e) or "rollback" in str(e):
                    print("Database connection error detected. Stopping...")
                    break


async def normalize_all_scores(session: AsyncSession):
    """
    Normalizes all cost scores to 0-1 scale where 0 = cheapest, 1 = most expensive.
    Then inverts for the final score where higher = better (cheaper).
    """
    print("\n--- Normalizing all cost of living scores ---")
    attribute_name = CityAttributeName.COST_OF_LIVING
    
    stmt = select(CityAttribute.raw_value).where(
        CityAttribute.attribute_name == attribute_name,
        CityAttribute.raw_value.isnot(None)
    )
    result = await session.execute(stmt)
    raw_scores = result.scalars().all()

    if not raw_scores or len(raw_scores) < 2:
        print("Not enough raw scores found to normalize.")
        return

    # Use percentile-based normalization to handle outliers better
    scores_array = np.array(raw_scores)
    p5 = np.percentile(scores_array, 5)
    p95 = np.percentile(scores_array, 95)
    
    print(f"Score distribution: Min={min(raw_scores):.1f}, P5={p5:.1f}, P95={p95:.1f}, Max={max(raw_scores):.1f}")
    
    all_attributes_stmt = select(CityAttribute).where(CityAttribute.attribute_name == attribute_name)
    all_attributes_result = await session.execute(all_attributes_stmt)
    
    update_count = 0
    for attr in all_attributes_result.scalars().all():
        if attr.raw_value is not None:
            # Normalize using percentiles to reduce impact of outliers
            if p95 > p5:
                normalized = (attr.raw_value - p5) / (p95 - p5)
                normalized = max(0, min(1, normalized))  # Clamp to 0-1
            else:
                normalized = 0.5
            
            # Invert so higher score = cheaper = better
            attr.normalized_score = 1 - normalized
            session.add(attr)
            update_count += 1
    
    await session.commit()
    print(f"Successfully updated {update_count} attributes with normalized scores.")


async def main():
    """Main function to orchestrate the attribute update process."""
    async with AsyncSessionLocal() as session:
        await fetch_and_save_scores(session)
        await normalize_all_scores(session)


if __name__ == "__main__":
    asyncio.run(main())