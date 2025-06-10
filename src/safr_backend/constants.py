from enum import Enum

class CityAttributeName(str, Enum):
    """
    Defines the canonical, case-sensitive names for city attributes.
    This is used in the application layer to ensure consistency,
    but is NOT a database-level enum, preserving flexibility.
    """
    COST_OF_LIVING = 'cost_of_living'
    CLIMATE = 'climate'
    SAFETY = 'safety'
    URBAN_GREENERY = 'urban_greenery'
    AMENITIES = 'amenities'
    PUBLIC_TRANSIT = 'public_transit'
    AIR_QUALITY = 'air_quality'
    INTERNET_SPEED = 'internet_speed'
