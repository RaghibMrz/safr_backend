# Safr Backend

================

This is the backend code for Safr, a travel ranking app.

## Structure

### models.py

Database structure.

### schemas.py

API data shape and validation.

### security.py

Password hashing and verification.

### database.py

Database connection and session management.

### main.py

FastAPI application entry point.

### alembic

Database migration tool.

## Cities

Please make sure you seed your database with cities before running the API, you can do this by running the following command:

```bash
poetry run python scripts/seed_cities.py
```

## Demo API calls

### Get a token

```bash
curl -X POST "http://127.0.0.1:8000/token" \  \
 -H "accept: application/json" \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "username=johndoe&password=a_very_secure_password"
```

### Update a city ranking

```bash
curl -X PUT "http://127.0.0.1:8000/rankings/cities/1006" \
 -H "accept: application/json" \
 -H "Authorization: Bearer YOUR_TOKEN" \
 -H "Content-Type: application/json" \
 -d '{"personal_score": 85.5}'
```

### Get my ranked cities

```bash
curl -X GET "http://127.0.0.1:8000/rankings/me?skip=0&limit=10&sort_desc=true" \
 -H "accept: application/json" \
 -H "Authorization: Bearer YOUR_TOKEN"
```

### Delete a city ranking

```bash
curl -X DELETE "http://127.0.0.1:8000/rankings/cities/1006" \
 -H "accept: application/json" \
 -H "Authorization: Bearer YOUR_TOKEN"
```

## Docker

```bash
poetry run docker-compose up --build
```

## Run backend

```bash
poetry run uvicorn src.safr_backend.main:app --reload --host 0.0.0.0 --port 8000
```
