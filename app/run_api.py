"""
Run the FastAPI server
"""
import uvicorn

if __name__ == "__main__":
    print("Starting FastAPI server...")
    print("API will be available at http://localhost:8000")
    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8000, reload=True) 