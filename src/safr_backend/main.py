from fastapi import FastAPI
from .routers import users, auth # Relative import for users and auth routers
from .routers import cities
from .routers import rankings

app = FastAPI(
    title="Safr API",
    description="API for ranking travel destinations.",
    version="0.1.0"
)

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