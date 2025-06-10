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

# To Deploy:

Build and push docker image to Google Container Registry

```bash
gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/safr-backend
```

Deploy to cloud run

```bash
gcloud run deploy safr-backend \
  --image gcr.io/$(gcloud config get-value project)/safr-backend \
  --platform managed \
  --region europe-west2 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --add-cloudsql-instances $(gcloud sql instances describe safr-db --format="value(connectionName)") \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$(gcloud config get-value project),DB_USER=postgres,DB_NAME=safr,CLOUD_SQL_CONNECTION_NAME=$(gcloud sql instances describe safr-db --format='value(connectionName)'),ALGORITHM=HS256,ACCESS_TOKEN_EXPIRE_MINUTES=30" \
  --set-secrets "DB_PASS=db-password:latest,SECRET_KEY=jwt-secret:latest"
```

Or one liner:

```bash
cd safr_backend && gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/safr-backend && gcloud run deploy safr-backend --image gcr.io/$(gcloud config get-value project)/safr-backend --region europe-west2
```

To update secrets:

```bash
# If you change passwords or secrets:
echo -n "new-password" | gcloud secrets versions add db-password --data-file=-
echo -n "new-jwt-secret" | gcloud secrets versions add jwt-secret --data-file=-
```

Test the deployment:

```bash
# Get the URL and test
export API_URL=$(gcloud run services describe safr-backend --region europe-west2 --format "value(status.url)")
echo "API deployed at: $API_URL"

# Quick health check
curl $API_URL/health

# Run request which requires prod db access:
curl "$API_URL/cities/" | head -20
```

Troubleshooting:

```bash
# Make sure you run the migrations and seed script (if required) before deploying:
DATABASE_URL=... poetry run alembic upgrade head
DATABASE_URL=... poetry run python scripts/seed_cities.py

# Check logs if something fails
gcloud run services logs read safr-backend --region europe-west2 --limit 50

# Check service status
gcloud run services describe safr-backend --region europe-west2
```

Attributes:

```bash
poetry run python scripts/attributes/update_air_quality.py
poetry run python scripts/attributes/update_urban_greenery.py
```

Air Quality:

- uses the average of 1 years worth historic data from OpenWeather API to calculate the air quality index - from 10/06/2025 to 10/06/2024
- unit of measurement of PM2.5 is micrograms per cubic meters (µg/m³)
- normalized score is the min-max normalized air quality index
- normalized score is inverted (lower is better)

Internet Speed:

- uses the average of last quarters median internet speed from Ookla API to calculate the internet speed index - (Q1 of 2025)
- unit of measurement of internet speed is Mbps
- normalized score is the min-max normalisation of the log-transformed internet speed index (log_score = ln(raw_score))
- any column where raw_value is 0, is deemed to be a city for which data is not available and is assigned a normalized score of 0

Urban Greenery:

- uses the overpass.kumi open source API to calculate the urban greenery index using public green areas
- normalized score is the min-max normalized urban greenery index
