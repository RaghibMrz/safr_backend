from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from pydantic import Field

# --- User Schemas ---

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

    class Config:
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "johndoe@example.com",
                "password": "a_very_secure_password"
            }
        }

class UserDisplay(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "username": "johndoe",
                "email": "johndoe@example.com",
                "created_at": "2024-05-08T10:00:00.000Z"
            }
        }

class Token(BaseModel):
    access_token: str
    token_type: str # Will typically be "bearer"

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer"
            }
        }

class TokenData(BaseModel):
    # This schema defines the data we expect to be encoded in the JWT (the "subject" or "sub")
    username: Optional[str] = None # Or could be user_id: Optional[int] = None

# --- City Schemas ---

class CityBase(BaseModel):
    """Base schema for city attributes."""
    name: str
    country_code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geoname_id: Optional[str] = None
    country_name: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "London",
                "country_code": "UK",
                "latitude": 51.5074,
                "longitude": 0.1278,
                "geoname_id": "2643743",
                "country_name": "United Kingdom"
            }
        }

class CityDisplay(CityBase):
    """Schema for displaying city information."""
    id: int # The ID from our database

    class Config:
        from_attributes = True # To map from SQLAlchemy model
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "London",
                "country_code": "UK",
                "latitude": 51.5074,
                "longitude": 0.1278,
                "geoname_id": "2643743",
                "country_name": "United Kingdom"
            }
        }

# --- UserCityRanking Schemas ---

class UserCityRankingCreate(BaseModel):
    """Schema for creating/updating a user's ranking for a city."""
    personal_score: float = Field(..., ge=0, le=100, description="User's personal score for the city (0-100)")
    # city_id will be a path parameter
    # user_id will come from the authenticated user

    class Config:
        json_schema_extra = {
            "example": {
                "personal_score": 85.5
            }
        }

class UserCityRankingDisplay(BaseModel):
    """Schema for displaying a user's city ranking."""
    id: int # ID of the ranking entry itself
    user_id: int
    city_id: int
    personal_score: float
    objective_score: Optional[float] = None # We'll keep this nullable and ignore for now
    created_at: datetime
    updated_at: datetime
    city: CityDisplay # Include full city details

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "user_id": 1,
                "city_id": 1,
                "personal_score": 85.5,
                "objective_score": None,
                "created_at": "2024-05-15T10:00:00.000Z",
                "updated_at": "2024-05-15T10:00:00.000Z",
                "city": {
                    "id": 1,
                    "name": "London",
                    "country_code": "United Kingdom",
                    "latitude": 51.5074,
                    "longitude": 0.1278,
                    "geoname_id": "2643743",
                    "country_name": "United Kingdom"
                }
            }
        }
