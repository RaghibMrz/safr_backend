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

# --- CORS Middleware ---
# origins that are allowed to make requests to your API.
# For development, allowing all origins ("*") is common.
# For production, you should restrict this to your frontend's domain(s).
origins = [
    "http://localhost",         # Common for web development
    "http://localhost:8081",    # Default Expo Go port, sometimes used by web version
    "http://localhost:19006",   # Another Expo development port
    # Add other origins if needed, e.g., your production frontend URL
    # If your React Native app makes requests without a typical "Origin" header (common for native),
    # allowing "*" might be necessary, or specific checks for mobile might be needed.
    # However, for emulators using http://10.0.2.2, the origin might appear as that.
    "*" # Allows all origins - USE WITH CAUTION IN PRODUCTION
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