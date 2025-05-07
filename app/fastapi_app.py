from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import json
import uuid
from typing import List, Optional, Dict
from pathlib import Path
import shutil
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel
import time
from sse_starlette.sse import EventSourceResponse
import logging
from datetime import datetime, timedelta

# Import from existing modules
from video_creator import create_romanian_video, cleanup_broll, create_user_directory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Create necessary directories
os.makedirs('user_sessions', exist_ok=True)
os.makedirs('../brolls/default', exist_ok=True)
os.makedirs('../brolls/user_uploads', exist_ok=True)

# Mount static directories
app.mount("/music", StaticFiles(directory="music"), name="music")
app.mount("/brolls", StaticFiles(directory="../brolls"), name="brolls")
app.mount("/favicon", StaticFiles(directory="favicon"), name="favicon")

# Session management
active_sessions: Dict[str, Dict] = {}

def cleanup_old_sessions():
    """Clean up sessions older than 1 hour"""
    current_time = datetime.now()
    for session_id, session_data in list(active_sessions.items()):
        if current_time - session_data['created_at'] > timedelta(hours=1):
            try:
                session_dir = Path(f"user_sessions/{session_id}")
                if session_dir.exists():
                    shutil.rmtree(session_dir)
                del active_sessions[session_id]
                logger.info(f"Cleaned up old session: {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning up session {session_id}: {e}")

def get_session_dir(session_id: str) -> Path:
    """Get or create a session directory"""
    session_dir = Path(f"user_sessions/{session_id}")
    if not session_dir.exists():
        session_dir.mkdir(parents=True)
        active_sessions[session_id] = {
            'created_at': datetime.now(),
            'last_activity': datetime.now()
        }
    return session_dir

# Models
class VideoRequest(BaseModel):
    script: str
    music: str = "funny 2.mp3"
    voice: str = "gbLy9ep70G3JW53cTzFC"
    selected_brolls: List[str] = []

class BrollInfo(BaseModel):
    filename: str
    type: str
    thumbnail_url: Optional[str] = None

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

@app.get("/brolls")
def get_brolls():
    """Get list of available b-rolls (both default and user uploads)"""
    default_brolls = []
    user_brolls = []
    
    # Get default b-rolls
    default_dir = Path("../brolls/default")
    if default_dir.exists():
        for file in default_dir.glob("*"):
            if file.suffix.lower() in ['.mp4', '.jpg', '.jpeg', '.png']:
                default_brolls.append({
                    "filename": file.name,
                    "type": "default",
                    "url": f"/brolls/default/{file.name}"
                })
    
    # Get user uploaded b-rolls
    user_dir = Path("../brolls/user_uploads")
    if user_dir.exists():
        for file in user_dir.glob("*"):
            if file.suffix.lower() in ['.mp4', '.jpg', '.jpeg', '.png']:
                user_brolls.append({
                    "filename": file.name,
                    "type": "user_upload",
                    "url": f"/brolls/user_uploads/{file.name}"
                })
    
    return {
        "default_brolls": default_brolls,
        "user_brolls": user_brolls
    }

@app.post("/upload-broll")
async def upload_broll(file: UploadFile = File(...)):
    """Upload a new b-roll file"""
    # Validate file type
    allowed_types = ['.mp4', '.jpg', '.jpeg', '.png']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed types: MP4, JPG, JPEG, PNG")
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = Path("../brolls/user_uploads") / unique_filename
    
    # Save file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    return {
        "filename": unique_filename,
        "type": "user_upload",
        "url": f"/brolls/user_uploads/{unique_filename}"
    }

@app.delete("/brolls/{type}/{filename}")
async def delete_broll(type: str, filename: str):
    """Delete a b-roll file"""
    if type not in ["default", "user_uploads"]:
        raise HTTPException(status_code=400, detail="Invalid b-roll type")
    
    file_path = Path(f"../brolls/{type}/{filename}")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(file_path)
        return {"message": "File deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

@app.post("/create-video")
async def create_video_endpoint(request: VideoRequest):
    """Create a video with the given script and selected resources"""
    try:
        # Generate a unique session ID
        session_id = str(uuid.uuid4())
        session_dir = get_session_dir(session_id)
        
        # Create a queue for progress messages
        progress_queue = asyncio.Queue()
        
        # Create an async event generator
        async def event_generator():
            try:
                # Process selected b-rolls
                broll_files = []
                for broll in request.selected_brolls:
                    # Check in both default and user_uploads directories
                    default_path = Path("../brolls/default") / broll
                    user_path = Path("../brolls/user_uploads") / broll
                    
                    if default_path.exists():
                        broll_files.append(str(default_path))
                    elif user_path.exists():
                        broll_files.append(str(user_path))
                    else:
                        logger.warning(f"B-roll file not found: {broll}")
                
                logger.info(f"Selected brolls: {broll_files}")
                
                # Create progress callback that uses the main event loop
                main_loop = asyncio.get_event_loop()
                def progress_callback(message):
                    if main_loop.is_running():
                        main_loop.call_soon_threadsafe(
                            lambda: asyncio.create_task(progress_queue.put(message))
                        )
                
                # Start video creation task in a separate thread
                loop = asyncio.get_event_loop()
                video_path = await loop.run_in_executor(
                    None,
                    lambda: create_romanian_video(
                        romanian_script=request.script,
                        session_id=session_id,
                        selected_music=request.music,
                        voice_id=request.voice,
                        progress_callback=progress_callback,
                        broll_files=broll_files
                    )
                )
                
                # Wait for task to complete
                while True:
                    try:
                        message = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        if "ERROR:" in message:
                            yield f"data: {json.dumps({'error': message.replace('ERROR:', '').strip()})}\n\n"
                            break
                        elif "Video creation complete!" in message:
                            yield f"data: {json.dumps({'status': 'complete', 'session_id': session_id})}\n\n"
                            break
                        else:
                            yield f"data: {json.dumps({'status': 'progress', 'message': message})}\n\n"
                    except asyncio.TimeoutError:
                        continue
                    
            except Exception as e:
                logger.error(f"Error in video task: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(event_generator(), media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Error in create_video_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{session_id}")
def download_video(session_id: str, background_tasks: BackgroundTasks):
    """Download the generated video"""
    try:
        # Look for the video in the specific session directory
        session_dir = Path("user_sessions") / session_id
        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session directory not found")

        # Find the video file in the session directory
        video_files = list(session_dir.glob("final_video_*.mp4"))
        if not video_files:
            raise HTTPException(status_code=404, detail="Video not found")
        
        # Get the most recent video file
        video_path = max(video_files, key=lambda x: x.stat().st_mtime)
        
        def cleanup():
            time.sleep(5)  # Wait 5 seconds before cleaning up
            try:
                if video_path.exists():
                    os.remove(video_path)
                    logger.info(f"Cleaned up video file: {video_path}")
            except Exception as e:
                logger.error(f"Error removing file: {e}")
        
        background_tasks.add_task(cleanup)
        
        return FileResponse(
            path=video_path,
            filename="your_video.mp4",
            media_type="video/mp4"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in download_video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Cleanup task
@app.on_event("startup")
async def startup_event():
    """Start cleanup task on startup and configure workers"""
    async def cleanup_task():
        while True:
            cleanup_old_sessions()
            await asyncio.sleep(300)  # Run every 5 minutes
    
    asyncio.create_task(cleanup_task())

if __name__ == "__main__":
    # Configure uvicorn to use multiple workers
    uvicorn.run(
        "fastapi_app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=4  # Adjust this number based on your CPU cores
    ) 