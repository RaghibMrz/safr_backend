from enum import Enum

class CityAttributeName(str, Enum):
    """
    Defines the canonical, case-sensitive names for city attributes.
    This is used in the application layer to ensure consistency,
    but is NOT a database-level enum, preserving flexibility.
    """
    URBAN_GREENERY = 'urban_greenery'
    AIR_QUALITY = 'air_quality'
    INTERNET_SPEED = 'internet_speed'
    COST_OF_LIVING = 'cost_of_living'
    CITY_AREA = 'city_area'
    # PUBLIC_TRANSIT = 'public_transit'
    # CLIMATE = 'climate'
    # SAFETY = 'safety'



'''
New Attribute Suggestions
For Digital Nomads & Remote Workers

Coworking Spaces Density: Count/density of coworking spaces
Cafe WiFi Culture: Number of cafes with WiFi (could scrape Google Places API)
Cost of Living Index: Essential for long-term stays

For Urban/Metropolitan Lovers

Public Transit Score: Density and quality of public transportation
Nightlife Vibrancy: Number of bars, clubs, late-night venues
Population Density: Direct metric for "bustling city" feel
Skyscraper Index: Count buildings > 150m (use OpenStreetMap or skyscraperpage.com)

For Culture & History Enthusiasts

UNESCO Sites: Both within city and nearby (weighted by distance)
Museum Density: Museums per capita or per square km
Historical Building Ratio: Buildings older than 100/200 years
Cultural Events: Annual festivals, concerts (harder to maintain)

For Religious/Spiritual Travelers

Religious Site Diversity: Different types of religious buildings
Pilgrimage Significance: Is it a major pilgrimage destination?
Halal/Kosher/Veg Options: Restaurant density by dietary restriction

For Nature & Outdoor Enthusiasts

Proximity to Nature: Distance to nearest national park/mountain/beach
Hiking Trail Access: Trails within 50km radius
Water Body Access: Rivers, lakes, ocean within city
Biodiversity Index: If available from environmental databases

For Families

Safety Index: Crime statistics (carefully normalized)
School Quality: If targeting expat families
Family Entertainment: Zoos, aquariums, theme parks
Healthcare Quality: Hospital ratings/density

For Sports & Fitness

Sports Facilities: Gyms, pools, courts per capita
Bike Infrastructure: Bike lanes, bike-sharing systems
Running Routes: Popular running paths (Strava heatmaps?)
Professional Sports: Teams and venues

Climate & Weather

Sunshine Hours: Annual sunshine hours
Temperature Comfort: Days within comfortable range (20-25°C)
Rainfall Pattern: Not just amount but distribution
Natural Disaster Risk: Earthquakes, floods, hurricanes



'''
