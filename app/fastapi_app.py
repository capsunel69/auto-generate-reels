from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import json
import uuid
from typing import List, Optional
from pathlib import Path
import shutil
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel
import time
from sse_starlette.sse import EventSourceResponse

# Import from existing modules
from video_creator import create_romanian_video, cleanup_broll, create_user_directory
# Import other modules as needed

# Load environment variables
load_dotenv()

app = FastAPI()

# Add CORS middleware to allow the React Vite app to access this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development. In production, set to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directories
app.mount("/music", StaticFiles(directory="music"), name="music")
app.mount("/favicon", StaticFiles(directory="favicon"), name="favicon")

# Create session/user directories if they don't exist
os.makedirs('user_sessions', exist_ok=True)

# Helper function for user sessions
def get_user_dir(user_id: str):
    user_dir = Path(f"user_sessions/{user_id}")
    if not user_dir.exists():
        create_user_directory(user_id)
    return user_dir

# Models
class VideoRequest(BaseModel):
    script: str
    music: str = "funny 2.mp3"
    voice: str = "gbLy9ep70G3JW53cTzFC"

# API routes
@app.get("/")
def read_root():
    return {"message": "Video Creator API"}

@app.get("/music-list")
def get_music_list():
    music_dir = Path('music')
    music_files = [f.name for f in music_dir.glob('*.mp3')]
    return {"music_files": music_files}

@app.get("/voices")
def get_voices():
    voices = [
        {"id": "gbLy9ep70G3JW53cTzFC", "name": "Madalina", "preview": "madalina.mp3"},
        {"id": "8QdBGRwn9G5tpGGTOaOe", "name": "Panfiliu", "preview": "panfiliu.mp3"},
        {"id": "oToG20WieQJ7KUmhMkj4", "name": "Karen", "preview": "karen.mp3"}
    ]
    return {"voices": voices}

@app.post("/create-video")
async def create_video_endpoint(request: VideoRequest, request_obj: Request):
    # Generate a user ID
    user_id = str(uuid.uuid4())
    
    # Create progress stream
    async def event_generator():
        async def progress_callback(message):
            if isinstance(message, str):
                yield {"data": message}
            else:
                yield {"data": json.dumps(message)}
        
        try:
            yield {"data": "Starting video creation..."}
            
            # Call the existing function but handle it properly for async
            for message in create_romanian_video(
                request.script, 
                user_id, 
                request.music, 
                request.voice, 
                lambda msg: asyncio.create_task(progress_callback(msg))
            ):
                if await request_obj.is_disconnected():
                    break
                yield {"data": message}
                
            yield {"data": "DONE"}
            
        except Exception as e:
            yield {"data": f"ERROR: {str(e)}"}
    
    return EventSourceResponse(event_generator())

@app.get("/download/{video_id}")
def download_video(video_id: str, background_tasks: BackgroundTasks):
    user_dir = get_user_dir(video_id)
    final_output = user_dir / "final_output.mp4"
    
    if not final_output.exists():
        return {"error": "Video not found"}
    
    def cleanup():
        time.sleep(5)  # Wait 5 seconds before cleaning up
        if final_output.exists():
            try:
                os.remove(final_output)
            except Exception as e:
                print(f"Error removing file: {e}")
    
    background_tasks.add_task(cleanup)
    
    return FileResponse(
        path=final_output,
        filename="your_video.mp4",
        media_type="video/mp4"
    )

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = Form(...)):
    user_dir = get_user_dir(user_id)
    file_path = user_dir / file.filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"filename": file.filename}

@app.post("/reorder")
async def reorder_files(user_id: str = Form(...), files: str = Form(...)):
    file_list = json.loads(files)
    user_dir = get_user_dir(user_id)
    
    # Implementation similar to your existing reorder_files function
    
    return {"success": True}

if __name__ == "__main__":
    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8000, reload=True) 