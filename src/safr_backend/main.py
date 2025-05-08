from fastapi import FastAPI


app = FastAPI(
    title="Safr API",
    description="API for ranking travel destinations.",
    version="0.1.0"
)

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
 