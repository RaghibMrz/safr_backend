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
