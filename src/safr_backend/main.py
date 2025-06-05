import os
from fastapi import FastAPI
from .routers import users, auth # Relative import for users and auth routers
from .routers import cities
from .routers import rankings
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Safr API",
    description="API for ranking travel destinations.",
    version="0.1.0"
)
PORT = int(os.getenv("PORT", 8080))

# --- CORS Middleware ---
if os.getenv("GOOGLE_CLOUD_PROJECT"):
    origins = ["*"]
else:
    origins = [
    "http://localhost",         # Common for web development
    "http://localhost:8081",    # Default Expo Go port, sometimes used by web version
    "http://localhost:19006",   # Another Expo development port
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # List of origins allowed
    allow_credentials=True, # Allow cookies (if you were using them)
    allow_methods=["*"],    # Allow all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],    # Allow all headers
)
# --- End CORS Middleware ---


app.include_router(auth.router) # Handles /token
app.include_router(users.router) # Handles /users/
app.include_router(cities.router)  # Handles /cities/
app.include_router(rankings.router) # Handles /rankings/


@app.get("/")
async def read_root():
    """
    Root endpoint providing a welcome message.
    Useful for basic connectivity checks.
    """
    return {"message": "Root endpoint"}

@app.get("/health")
async def health_check():
    """
    Health check endpoint to ensure the API is running.
    """
    return {"status": "ok"}
 

@app.on_event("shutdown")
async def on_shutdown():
    print("Safr API shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
    