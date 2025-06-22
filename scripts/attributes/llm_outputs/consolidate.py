import json
from pathlib import Path
import re
from safr_backend.models import City
from safr_backend.database import AsyncSessionLocal
import asyncio
from sqlalchemy import update, case

# --- Configuration ---
INPUT_DIR = Path(__file__).parent
OUTPUT_FILE = INPUT_DIR / "all_new.json"

def combine_json_files():
    """
    Finds all 'llm_output_batch_*.json' files, combines their content,
    and writes the result to a single 'all.json' file.
    """
    combined_data = []
    error_log = []

    # Find all files matching the batch output pattern
    batch_files = sorted(INPUT_DIR.glob("llm_output_batch_*.json"))

    if not batch_files:
        print(f"No 'llm_output_batch_*.json' files found in '{INPUT_DIR}'.")
        return
        
    print(f"Found {len(batch_files)} batch files to process...")

    for file_path in batch_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # The LLM sometimes returns raw text that isn't valid JSON.
                # We need to find the JSON array within the text.
                text_content = f.read()
                
                # Use regex to find the JSON array, ignoring potential markdown backticks
                json_match = re.search(r'\[.*\]', text_content, re.DOTALL)
                
                if not json_match:
                    raise json.JSONDecodeError(f"No JSON array found in file.", text_content, 0)
                    
                json_string = json_match.group(0)
                data = json.loads(json_string)

                if isinstance(data, list):
                    combined_data.extend(data)
                else:
                    # This case should be rare if the LLM follows instructions
                    error_log.append(f"File {file_path.name}: Content is not a list.")

        except json.JSONDecodeError as e:
            error_msg = f"File {file_path.name}: Invalid JSON. Error: {e}"
            print(f"  - WARNING: {error_msg}")
            error_log.append(error_msg)
        except Exception as e:
            error_msg = f"File {file_path.name}: An unexpected error occurred: {e}"
            print(f"  - ERROR: {error_msg}")
            error_log.append(error_msg)

    # Write the combined data to the output file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(combined_data, f, indent=2)
        print(f"\nSuccessfully combined {len(combined_data)} records into '{OUTPUT_FILE}'.")
    except Exception as e:
        print(f"\nFATAL: Could not write to output file '{OUTPUT_FILE}'. Error: {e}")


    # Write any errors to the error log
    if error_log:
        print("\nSome errors occurred during processing.")


def get_all_nulls():
    with open(INPUT_DIR / "all.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    nulls = [item['geoname_id'] for item in data if item['area_sq_km'] is None]
    return nulls

def get_non_nulls():
    with open(INPUT_DIR / "all.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    non_nulls = [item for item in data if item['area_sq_km'] is not None]
    return non_nulls

def get_all_boroughs_in_london():
    with open(INPUT_DIR / "all.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    borough = [item['geoname_id'] for item in data if 'London' in item['notes']]
    return borough

async def update_city_table(batch_size: int = 1000):
    """
    Fetches area data and updates the City table in batches using an
    efficient bulk UPDATE statement.
    """
    all_areas = get_non_nulls()
    if not all_areas:
        return

    area_map = {item['geoname_id']: item['area_sq_km'] for item in all_areas}
    geoname_ids = list(area_map.keys())

    for i in range(0, len(geoname_ids), batch_size):
        id_batch = geoname_ids[i:i + batch_size]
        area_sub_map = {gid: area_map[gid] for gid in id_batch}

        stmt = (
            update(City)
            .where(City.geoname_id.in_(id_batch))
            .values(
                area=case(
                    area_sub_map,
                    value=City.geoname_id,
                )
            )
        )

        async with AsyncSessionLocal() as session:
            await session.execute(stmt)
            await session.commit()


if __name__ == "__main__":
    # combine batch files
    # combine_json_files()

    # nulls
    # nulls = get_all_nulls()
    # print(nulls)
    # print(len(nulls))

    # get all duplicates
    # duplicates = [item for item in get_all_nulls() if get_non_nulls().count(item) > 1]
    # print(duplicates)
    # print(len(duplicates))

    # non nulls
    # non_nulls = get_non_nulls()
    # with open(INPUT_DIR / "all_non_nulls.json", 'w', encoding='utf-8') as f:
    #     json.dump(non_nulls, f, indent=2)

    # print(len(non_nulls))
    
    # get all boroughs in london
    # boroughs = get_all_boroughs_in_london()
    # print(boroughs)
    # print(len(boroughs))
    
    # update city table
    asyncio.run(update_city_table())
    