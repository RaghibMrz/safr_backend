from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

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

# --- City Schemas (Example placeholders) ---
# class CityBase(BaseModel):
#     name: str
#     country: str
#     geoname_id: Optional[str] = None
#     latitude: Optional[float] = None
#     longitude: Optional[float] = None

# class CityCreate(CityBase):
#     pass

# class CityDisplay(CityBase):
#     id: int
#     # objective_rating: Optional[float] = None # If we had a global one

#     class Config:
#         from_attributes = True

# --- UserCityRanking Schemas (Example placeholders) ---
# class UserCityRankingBase(BaseModel):
#     city_id: int
#     personal_score: float

# class UserCityRankingCreate(UserCityRankingBase):
#     pass

# class UserCityRankingDisplay(UserCityRankingBase):
#     id: int
#     user_id: int
#     objective_score: Optional[float] = None
#     created_at: datetime
#     updated_at: datetime
#     # city: CityDisplay # Nested display of city info

#     class Config:
#         from_attributes = True
