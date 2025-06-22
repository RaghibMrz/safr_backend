# scripts/attributes/update_city_area_llm_to_file.py
# DEBUGGING STRATEGY: BATCH PROCESS CITIES, WRITE RAW LLM OUTPUT DIRECTLY TO A FILE
import asyncio
import httpx
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from typing import List
import time

# --- App-specific Imports ---
from safr_backend.models import City

# --- Configuration ---
# Create an output directory for the raw JSON files
OUTPUT_DIR = Path(__file__).parent / "llm_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

PROGRESS_FILE = Path(__file__).parent / "city_area_llm_progress.log"
ERROR_LOG_FILE = Path(__file__).parent / "city_area_llm_errors.log"
BATCH_SIZE = 250

# --- Database and API Key Setup ---
dotenv_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DATABASE_URL: raise ValueError("DATABASE_URL not set.")
if not GEMINI_API_KEY: raise ValueError("FATAL: GEMINI_API_KEY not set in .env file. This script cannot run without it.")

if not DATABASE_URL: raise ValueError("DATABASE_URL not set.")
if not GEMINI_API_KEY: raise ValueError("FATAL: GEMINI_API_KEY not set in .env file. This script cannot run without it.")

engine: Engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# --- Helper Functions ---
def load_processed_cities() -> set[str]:
    """Loads the set of geoname_ids from the final combined 'all.json' file."""
    processed_ids = set()
    try:
        with open(OUTPUT_DIR / 'all.json', 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return set()
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'geoname_id' in item:
                        processed_ids.add(str(item['geoname_id'])) # Ensure geoname_id is a string
    except (json.JSONDecodeError, FileNotFoundError):
        return set()

    return processed_ids

def log_processed_cities(geoname_ids: List[str]):
    """Appends a list of geoname_ids to the progress log."""
    with open(PROGRESS_FILE, 'a') as f:
        for geoname_id in geoname_ids:
            f.write(f"{geoname_id}\n")

def log_error(batch_info: str, error: str, response_text: str = ""):
    """Logs errors to a separate error file for debugging."""
    with open(ERROR_LOG_FILE, 'a') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Batch {batch_info}: {error}\n")
        if response_text:
            f.write(f"--- RAW AI RESPONSE ---\n{response_text}\n--- END RAW ---\n")

def construct_llm_prompt(cities_batch: List[City]) -> str:
    """Constructs the detailed prompt for the Gemini API."""
    city_list_json = json.dumps(
        [{"geoname_id": city.geoname_id, "name": city.name, "country": city.country_name} for city in cities_batch],
        indent=2
    )

    return (
        "You are a world-class geography expert and data processing API. "
        "I will provide you with a JSON array of cities. For each city, your task is to find the official administrative area of the **city proper** (not the metropolitan or urban area) in square kilometers. "
        "You must return your response as a single, valid JSON array of objects, with no other text or explanation. "
        "Each object in the array must contain these exact keys: 'geoname_id' (string), 'name' (string), 'area_sq_km' (number), and 'notes' (string). "
        "In the 'notes' field, briefly specify what boundary the area corresponds to (e.g., 'Municipality', 'City-State', 'Special Administrative Region'). "
        "Please perform a thorough search for the area in square kilometers. "
        "If the data does not pertain to a city, find the area of the locale given to you."
        "If you absolutely cannot find a reliable area for a city, please skip it entirely. "
        "Do not use markdown or backticks around the JSON. Your entire response must be only the JSON data.\n\n"
        "Please make sure your output is valid JSON.\n\n"
        "Here is the list of cities:\n"
        f"{city_list_json}"
    )

async def process_batch_and_write_to_file(batch: List[City], batch_num: int, client: httpx.AsyncClient):
    """Sends a batch of cities to the AI and writes the raw response to a file."""
    prompt = construct_llm_prompt(batch)
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"
    # payload = {"contents": [{"parts": [{"text": prompt}]}]}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 65535
        }
    }

    batch_info_for_log = f"Batch {batch_num} (Starts with {batch[0].geoname_id})"
    output_filename = OUTPUT_DIR / f"llm_output_batch_{batch_num}.json"
    geoname_ids_in_batch = [city.geoname_id for city in batch]

    try:
        print(f"  Sending request to Gemini API for batch {batch_num}...")
        response = await client.post(gemini_url, json=payload, timeout=300.0)

        # Always check status code first
        if response.status_code != 200:
            error_message = f"Gemini API returned a non-200 status code: {response.status_code}"
            print(f"  ERROR: {error_message}")
            log_error(batch_info_for_log, error_message, response.text)
            log_processed_cities(geoname_ids_in_batch) # Log as processed to avoid retrying a failing batch
            return

        data = response.json()

        # --- FIX: More robust check for the expected response structure ---
        candidate = data.get('candidates', [{}])[0]
        content = candidate.get('content') if candidate else None
        parts = content.get('parts') if content else None

        if not parts:
            finish_reason = candidate.get('finishReason', 'UNKNOWN')
            error_message = f"AI response blocked or malformed. Finish reason: {finish_reason}."
            print(f"  ERROR: {error_message}")
            log_error(batch_info_for_log, error_message, json.dumps(data, indent=2))
            log_processed_cities(geoname_ids_in_batch)
            return

        ai_response_text = parts[0]['text']

        # Write the raw text response to a file
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(ai_response_text)

        print(f"  SUCCESS: Raw response for batch {batch_num} written to {output_filename}")
        # Log successful cities after the file is written
        log_processed_cities(geoname_ids_in_batch)

    except Exception as e:
        error_msg = f"An unexpected error occurred during API call: {e}"
        print(f"  ERROR: {error_msg}")
        log_error(batch_info_for_log, error_msg)
        # Also log this batch as processed to avoid getting stuck
        log_processed_cities(geoname_ids_in_batch)


async def main():
    """Main function to fetch cities and process them in batches via AI."""
    async with AsyncSessionLocal() as session:
        # to do all the ones that havent been done yet
        processed_ids = load_processed_cities()
        print(processed_ids)
        return
        result = await session.execute(select(City.geoname_id))
        all_city_ids = {row[0] for row in result.all()}
        not_processed_ids = all_city_ids - processed_ids
        if not not_processed_ids:
            print("No new cities to process. Exiting.")
            return
        print(len(not_processed_ids))
        
        # to do all the nulls
        # with open(OUTPUT_DIR / 'all.json', 'r', encoding='utf-8') as f:
        #     data = json.load(f)
        # nulls = [item['geoname_id'] for item in data if item['area_sq_km'] is None]
        # print(nulls)
        # print(f"Found {len(nulls)} new cities to process.")

        stmt = select(City).where(City.geoname_id.in_(not_processed_ids)).order_by(City.population.desc().nulls_last())
        cities_to_process = (await session.execute(stmt)).scalars().all()
        total_cities = len(cities_to_process)
        print(f"Found {total_cities} cities to process.")
        
        if not cities_to_process:
            print("No new cities to process. Exiting.")
            return

        async with httpx.AsyncClient() as client:
            for i in range(0, total_cities, BATCH_SIZE):
                batch = cities_to_process[i:i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                total_batches = (total_cities + BATCH_SIZE - 1) // BATCH_SIZE
                
                print(f"\n{'#'*60}")
                print(f"Processing batch {batch_num}/{total_batches} (Cities {i+1}-{min(i+BATCH_SIZE, total_cities)} of {total_cities})")
                print(f"{'#'*60}")

                await process_batch_and_write_to_file(batch, batch_num, client)
                
                # if i + BATCH_SIZE < total_cities:
                    # print(f"\nPausing between batches...")
                    # await asyncio.sleep(7.0) # Be courteous to the API
        
        print(f"\n{'='*60}\nProcessing complete! Raw outputs are in the '{OUTPUT_DIR}' directory.")
        print(f"Check {ERROR_LOG_FILE} for any API or processing errors.")

if __name__ == "__main__":
    asyncio.run(main())
