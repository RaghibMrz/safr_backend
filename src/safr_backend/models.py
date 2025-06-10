from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, Index, func, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func as sql_func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)  # Removed unique=True from here
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())

    # Future fields you mentioned (can be added later via migrations):
    # travel_style_tags = Column(ARRAY(String)) # If using PostgreSQL ARRAY type
    # preferred_climate = Column(String)

    rankings = relationship("UserCityRanking", back_populates="user")

    __table_args__ = (
        # Create a unique constraint on the lowercase version of username
        Index('ix_username_lower_unique', func.lower(username), unique=True),
    )

class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    name_normalized = Column(String, nullable=True, index=True)
    country_code = Column(String, nullable=True, index=True)
    country_name = Column(String, nullable=True, index=True)
    geoname_id = Column(String, unique=True, index=True, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    population = Column(BigInteger, nullable=True)

    attributes = relationship("CityAttribute", back_populates="city")
    user_rankings = relationship("UserCityRanking", back_populates="city")


class CityAttribute(Base):
    __tablename__ = "city_attributes"

    id = Column(Integer, primary_key=True, index=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)
    attribute_name = Column(String, nullable=False, index=True)
    raw_value = Column(Float, nullable=True)
    normalized_score = Column(Float, nullable=False)

    city = relationship("City", back_populates="attributes")

    __table_args__ = (
        UniqueConstraint('city_id', 'attribute_name', name='uq_city_attribute'),
    )

class UserCityRanking(Base):
    __tablename__ = "user_city_rankings"

    id = Column(Integer, primary_key=True, index=True) # Explicit PK for the ranking entry
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)

    personal_score = Column(Float, nullable=False) # User's subjective ranking score
    objective_score = Column(Float, nullable=True) # Calculated: city data + user preferences. Nullable if not always immediately calculated/available.

    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=sql_func.now(), onupdate=sql_func.now())

    # Future fields specific to this ranking/visit:
    # notes = Column(Text)
    # last_visited = Column(Date)
    # tags = Column(ARRAY(String))

    user = relationship("User", back_populates="rankings")
    city = relationship("City", back_populates="user_rankings")

    __table_args__ = (UniqueConstraint('user_id', 'city_id', name='uq_user_city_ranking'),)