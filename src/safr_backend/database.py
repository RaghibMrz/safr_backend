import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

# Load environment variables from .env file
# Make sure your .env file is in the project root directory (safr_backend/)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL is None:
    raise ValueError("DATABASE_URL environment variable not set. Please create a .env file in the project root.")

# Create an asynchronous engine
engine = create_async_engine(DATABASE_URL, echo=True) # echo=True for logging SQL, can be removed in production

# Create a sessionmaker for asynchronous sessions
# expire_on_commit=False is often useful with FastAPI's dependency injection
AsyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for SQLAlchemy models
Base = declarative_base()

# Dependency to get a DB session
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit() # Commit transactions that were successful
        except:
            await session.rollback() # Rollback in case of an error
            raise
        finally:
            await session.close()