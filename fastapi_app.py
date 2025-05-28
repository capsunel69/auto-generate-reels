from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Request, HTTPException, Depends, Cookie, Header
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
from video_creator import create_video, create_romanian_video, cleanup_broll, create_user_directory

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
    allow_headers=["*", "X-User-ID", "Content-Type", "Authorization"],
    expose_headers=["Content-Type", "Content-Length"]
)

# Create necessary directories
os.makedirs('user_sessions', exist_ok=True)
os.makedirs('brolls/default', exist_ok=True)
os.makedirs('brolls/user_uploads', exist_ok=True)
os.makedirs('brolls/thumbnails', exist_ok=True)  # Add thumbnails directory

# Mount static directories
app.mount("/music", StaticFiles(directory="music"), name="music")
app.mount("/brolls", StaticFiles(directory="brolls"), name="brolls")
app.mount("/favicon", StaticFiles(directory="favicon"), name="favicon")
app.mount("/voices_preview", StaticFiles(directory="src/voices_preview"), name="voices_preview")

# Session management
active_sessions: Dict[str, Dict] = {}

# Get or create user ID from request
async def get_user_id(
    x_user_id: Optional[str] = Header(None),
    user_id: Optional[str] = Cookie(None)
) -> str:
    """
    Get user ID from header or cookie, or generate a new one.
    In a real app, this would be an authentication system.
    """
    if x_user_id:
        return x_user_id
    if user_id:
        return user_id
    # Generate a new user ID if none exists
    return str(uuid.uuid4())

def get_user_brolls_dir(user_id: str) -> Path:
    """Get or create a user-specific b-rolls directory"""
    user_dir = Path(f"brolls/user_uploads/{user_id}")
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

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

def generate_thumbnail(video_path: Path) -> Optional[str]:
    """Generate thumbnail for a video file"""
    if not video_path.suffix.lower() == '.mp4':
        return None
        
    thumbnail_name = f"{video_path.stem}.jpg"
    thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
    
    # Skip if thumbnail already exists
    if thumbnail_path.exists():
        return str(thumbnail_path)
        
    try:
        import subprocess
        # Generate thumbnail at 1 second mark
        subprocess.run([
            'ffmpeg', '-i', str(video_path),
            '-ss', '00:00:01.000',
            '-vframes', '1',
            str(thumbnail_path)
        ], check=True)
        logger.info(f"Generated thumbnail: {thumbnail_path}")
        return str(thumbnail_path)
    except Exception as e:
        logger.error(f"Failed to generate thumbnail for {video_path}: {e}")
        return None

def generate_all_thumbnails():
    """Generate thumbnails for all video files"""
    logger.info("Generating thumbnails for all videos...")
    
    # Process default b-rolls
    default_dir = Path("brolls/default")
    if default_dir.exists():
        for video in default_dir.glob("*.mp4"):
            generate_thumbnail(video)
    
    # Process user uploaded b-rolls
    user_dir = Path("brolls/user_uploads")
    if user_dir.exists():
        for user_folder in user_dir.glob("*"):
            if user_folder.is_dir():
                for video in user_folder.glob("*.mp4"):
                    generate_thumbnail(video)
            
    logger.info("Finished generating thumbnails")

# Models
class VideoRequest(BaseModel):
    script: str
    music: str = "funny 2.mp3"
    voice: str = "gbLy9ep70G3JW53cTzFC"
    language: str = "romanian"  # Default to Romanian for backward compatibility
    selected_brolls: List[str] = []

class BrollInfo(BaseModel):
    filename: str
    type: str
    thumbnail_url: Optional[str] = None

class UserInfo(BaseModel):
    user_id: str

# API routes
@app.get("/")
def read_root():
    return {"message": "Video Creator API"}

@app.get("/user")
async def get_user_info(user_id: str = Depends(get_user_id)):
    """Return the current user's ID"""
    return {"user_id": user_id}

@app.get("/music-list")
def get_music_list():
    music_dir = Path('music')
    music_files = [f.name for f in music_dir.glob('*.mp3')]
    return {"music_files": music_files}

@app.get("/languages")
def get_languages():
    """Get available languages for script input"""
    languages = [
        {"code": "romanian", "name": "Romanian", "display": "Română"},
        {"code": "english", "name": "English", "display": "English"}
    ]
    return {"languages": languages}

@app.get("/voices")
def get_voices():
    voices = [
        # Romanian voices
        {"id": "gbLy9ep70G3JW53cTzFC", "name": "Madalina", "preview": "madalina.mp3", "language": "romanian"},
        {"id": "8QdBGRwn9G5tpGGTOaOe", "name": "Panfiliu", "preview": "panfiliu.mp3", "language": "romanian"},
        {"id": "oToG20WieQJ7KUmhMkj4", "name": "Karen", "preview": "karen.mp3", "language": "romanian"},
        
        # English voices (using placeholder previews for now - replace with actual English voice previews)
        {"id": "LgGXqiXAgeWadT5JmJWB", "name": "Adam Distrugatorul", "preview": "adam.mp3", "language": "english"},
        {"id": "EiNlNiXeDU1pqqOPrYMO", "name": "Narator Babuinator", "preview": "narator.mp3", "language": "english"},
        {"id": "xxHBkwyixiGK5rGxkJZu", "name": "Sculamentation Womăn", "preview": "sculamentation.mp3", "language": "english"},
        {"id": "Atp5cNFg1Wj5gyKD7HWV", "name": "Natasha Cumpanasa", "preview": "sculamentation.mp3", "language": "english"},
        {"id": "XhNlP8uwiH6XZSFnH1yL", "name": "Elizabeth", "preview": "sculamentation.mp3", "language": "english"}
    ]
    return {"voices": voices}

@app.get("/brolls")
async def get_brolls(user_id: str = Depends(get_user_id)):
    """Get list of available b-rolls (both default and user-specific uploads)"""
    default_brolls = []
    user_brolls = []
    
    def get_thumbnail_url(file_path: Path) -> Optional[str]:
        """Get thumbnail URL for a file if it exists"""
        if file_path.suffix.lower() in ['.mp4']:
            # For video files, check if thumbnail exists
            thumbnail_name = f"{file_path.stem}.jpg"
            thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
            if thumbnail_path.exists():
                # Return the URL path that will be served by the static file handler
                return f"/brolls/thumbnails/{thumbnail_name}"
        return None
    
    # Get default b-rolls
    default_dir = Path("brolls/default")
    if default_dir.exists():
        for file in default_dir.glob("*"):
            if file.suffix.lower() in ['.mp4', '.jpg', '.jpeg', '.png']:
                broll_info = {
                    "filename": file.name,
                    "type": "default",
                    "url": f"/brolls/default/{file.name}"
                }
                
                # Add thumbnail URL if available
                if file.suffix.lower() == '.mp4':
                    thumbnail_url = get_thumbnail_url(file)
                    if thumbnail_url:
                        broll_info["thumbnail_url"] = thumbnail_url
                        logger.info(f"Found thumbnail for {file.name}: {thumbnail_url}")
                
                default_brolls.append(broll_info)
    
    # Get user uploaded b-rolls
    user_dir = get_user_brolls_dir(user_id)
    if user_dir.exists():
        for file in user_dir.glob("*"):
            if file.suffix.lower() in ['.mp4', '.jpg', '.jpeg', '.png']:
                broll_info = {
                    "filename": file.name,
                    "type": "user_upload",
                    "url": f"/brolls/user_uploads/{user_id}/{file.name}"
                }
                
                # Add thumbnail URL if available
                if file.suffix.lower() == '.mp4':
                    thumbnail_url = get_thumbnail_url(file)
                    if thumbnail_url:
                        broll_info["thumbnail_url"] = thumbnail_url
                        logger.info(f"Found thumbnail for {file.name}: {thumbnail_url}")
                
                user_brolls.append(broll_info)
    
    # Generate a response with Set-Cookie header to persist the user ID
    response = JSONResponse(content={
        "default_brolls": default_brolls,
        "user_brolls": user_brolls,
        "user_id": user_id
    })
    
    # Set the user ID as a cookie (30 days expiry)
    response.set_cookie(
        key="user_id",
        value=user_id,
        max_age=60*60*24*30,
        httponly=True,
        samesite="lax"
    )
    
    return response

@app.post("/upload-broll")
async def upload_broll(file: UploadFile = File(...), user_id: str = Depends(get_user_id)):
    """Upload a new b-roll file for a specific user"""
    # Validate file type
    allowed_types = ['.mp4', '.jpg', '.jpeg', '.png']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed types: MP4, JPG, JPEG, PNG")
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    user_dir = get_user_brolls_dir(user_id)
    file_path = user_dir / unique_filename
    
    # Save file with progress tracking
    try:
        # Get content length if available
        content_length = int(file.headers.get("content-length", 0))
        
        # Create a chunked upload with progress tracking
        chunk_size = 1024 * 1024  # 1MB chunks
        total_read = 0
        progress = 0
        
        with open(file_path, "wb") as buffer:
            # Read file in chunks to track progress
            while chunk := await file.read(chunk_size):
                buffer.write(chunk)
                total_read += len(chunk)
                
                # Update progress percentage if content length is known
                if content_length > 0:
                    new_progress = int((total_read / content_length) * 100)
                    if new_progress > progress and new_progress % 10 == 0:  # Log every 10%
                        progress = new_progress
                        logger.info(f"Upload progress for {unique_filename}: {progress}%")
            
        logger.info(f"Upload complete: {unique_filename}, size: {total_read} bytes")
            
        # For video files, generate thumbnail
        if file_ext.lower() == '.mp4':
            generate_thumbnail(file_path)
                
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        if file_path.exists():
            try:
                os.remove(file_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Return response with thumbnail URL if available
    response_data = {
        "filename": unique_filename,
        "type": "user_upload",
        "url": f"/brolls/user_uploads/{user_id}/{unique_filename}",
        "size": total_read
    }
    
    if file_ext.lower() == '.mp4':
        thumbnail_name = f"{file_path.stem}.jpg"
        thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
        if thumbnail_path.exists():
            response_data["thumbnail_url"] = f"/brolls/thumbnails/{thumbnail_name}"
    
    return response_data

@app.delete("/brolls/{type}/{filename}")
async def delete_broll(type: str, filename: str, user_id: str = Depends(get_user_id)):
    """Delete a b-roll file"""
    if type not in ["default", "user_uploads"]:
        raise HTTPException(status_code=400, detail="Invalid b-roll type")
    
    # Only allow deletion of user's own b-rolls
    if type == "user_uploads":
        file_path = Path(f"brolls/user_uploads/{user_id}/{filename}")
    else:
        # Admin-only operation in a real app
        file_path = Path(f"brolls/{type}/{filename}")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(file_path)
        
        # Also remove thumbnail if it exists
        if file_path.suffix.lower() == '.mp4':
            thumbnail_name = f"{file_path.stem}.jpg"
            thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
            if thumbnail_path.exists():
                os.remove(thumbnail_path)
                
        return {"message": "File deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

@app.post("/create-video")
async def create_video_endpoint(request: VideoRequest, user_id: str = Depends(get_user_id)):
    """Create a video with the given script and selected resources"""
    try:
        # Generate a unique session ID
        session_id = str(uuid.uuid4())
        session_dir = get_session_dir(session_id)
        
        # Create a queue for progress messages that will be shared between threads
        progress_queue = asyncio.Queue()
        
        # Create an initial progress message
        await progress_queue.put(json.dumps({
            'status': 'progress',
            'message': 'Starting video creation...',
            'percentage': 0
        }))
        
        # Create an async event generator for SSE
        async def event_generator():
            try:
                logger.info(f"SSE connection established for session_id: {session_id}")
                
                # First send an initial message to establish the connection
                message = json.dumps({'status': 'progress', 'message': 'Starting video creation...', 'percentage': 0})
                yield f"data: {message}\n\n"
                await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                
                # Process selected b-rolls
                broll_files = []
                for broll in request.selected_brolls:
                    # Check in default directory
                    default_path = Path("brolls/default") / broll
                    # Check in user-specific directory
                    user_path = Path(f"brolls/user_uploads/{user_id}") / broll
                    
                    if default_path.exists():
                        broll_files.append(str(default_path))
                    elif user_path.exists():
                        broll_files.append(str(user_path))
                    else:
                        logger.warning(f"B-roll file not found: {broll}")
                
                logger.info(f"Selected brolls: {broll_files}")
                
                # Create progress callback that immediately sends SSE messages
                main_loop = asyncio.get_event_loop()
                
                def progress_callback(message):
                    # Parse the message for percentage if available
                    percentage = None
                    message_text = message
                    
                    if '|' in message:
                        try:
                            message_text, percentage_str = message.split('|')
                            percentage = float(percentage_str)
                            message_text = message_text.strip()
                            logger.info(f"Progress update - Message: {message_text}, Percentage: {percentage}")
                        except Exception as e:
                            logger.error(f"Error parsing progress message: {message} - Error: {e}")
                            percentage = None
                    
                    # Create progress data
                    progress_data = {
                        'status': 'progress',
                        'message': message_text
                    }
                    if percentage is not None:
                        progress_data['percentage'] = percentage
                        
                    # Log the progress data being sent
                    logger.info(f"Queueing progress data: {progress_data}")
                    
                    # Put the message in the queue from the background thread
                    if main_loop.is_running():
                        main_loop.call_soon_threadsafe(
                            lambda: asyncio.create_task(
                                progress_queue.put(json.dumps(progress_data))
                            )
                        )
                
                # Start video creation in a background task
                video_task = asyncio.create_task(
                    asyncio.to_thread(
                        create_video,
                        script=request.script,
                        session_id=session_id,
                        language=request.language,
                        selected_music=request.music,
                        voice_id=request.voice,
                        progress_callback=progress_callback,
                        broll_files=broll_files
                    )
                )
                
                # While the video is being created, stream progress updates
                video_path = None
                while True:
                    # Check if video task is done
                    if video_task.done():
                        # Get the result (or raise exception if it failed)
                        video_path = video_task.result()
                        # We still need to process any remaining messages in the queue
                        if progress_queue.empty():
                            break
                    
                    try:
                        # Get message with a short timeout
                        message = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                        logger.info(f"Sending SSE message: {message}")
                        
                        # Send the message immediately
                        yield f"data: {message}\n\n"
                        await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                        
                        # Check if this is a completion message
                        try:
                            data = json.loads(message)
                            if isinstance(data, dict) and "Video creation complete!" in str(data.get('message', '')):
                                logger.info("Detected completion message, will send final status after processing queue")
                        except json.JSONDecodeError:
                            pass
                            
                    except asyncio.TimeoutError:
                        # No message available, just continue and check video_task again
                        await asyncio.sleep(0.1)
                        continue
                        
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        error_msg = json.dumps({'error': str(e)})
                        yield f"data: {error_msg}\n\n"
                        await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                        raise
                
                # Send the final completion message
                complete_message = json.dumps({
                    'status': 'complete',
                    'session_id': session_id,
                    'video_path': video_path
                })
                logger.info(f"Sending completion message: {complete_message}")
                yield f"data: {complete_message}\n\n"
                await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                logger.info(f"SSE connection completed for session_id: {session_id}")
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error in video task: {error_msg}")
                error_data = json.dumps({'error': error_msg})
                yield f"data: {error_data}\n\n"
                await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                # Make sure we cancel the video task if it's still running
                if 'video_task' in locals() and not video_task.done():
                    video_task.cancel()
                logger.error(f"SSE connection terminated with error for session_id: {session_id}")
        
        # Return the streaming response with SSE
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "X-Accel-Buffering": "no",  # Disable buffering in Nginx
                "Access-Control-Allow-Origin": "*"  # For CORS - in production use your actual origin
            }
        )
        
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

@app.delete("/delete-user-brolls/{session_id}")
async def delete_user_brolls(session_id: str, user_id: str = Depends(get_user_id)):
    """Delete all user uploaded b-rolls after successful video creation"""
    try:
        # Verify the session exists
        session_dir = Path("user_sessions") / session_id
        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get a list of all user-uploaded b-rolls for this specific user
        user_dir = Path(f"brolls/user_uploads/{user_id}")
        if not user_dir.exists():
            return JSONResponse(
                status_code=200,
                content={
                    "message": "No user b-rolls to delete",
                    "deleted_count": 0
                }
            )
            
        user_brolls = list(user_dir.glob("*"))
        deleted_count = 0
        failed_files = []
        
        # Add files to background task for deletion with retries
        # This allows the HTTP response to return while deletion continues
        background_tasks = BackgroundTasks()
        
        def delete_with_retries():
            nonlocal deleted_count, failed_files
            import time
            
            # First attempt - try to delete all files
            for file_path in user_brolls:
                try:
                    # Delete the file
                    os.remove(file_path)
                    
                    # Also delete any thumbnails
                    if file_path.suffix.lower() == '.mp4':
                        thumbnail_name = f"{file_path.stem}.jpg"
                        thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
                        if thumbnail_path.exists():
                            os.remove(thumbnail_path)
                    
                    deleted_count += 1
                    logger.info(f"Deleted uploaded b-roll: {file_path}")
                except Exception as e:
                    logger.warning(f"First attempt: Error deleting b-roll {file_path}: {e}")
                    failed_files.append(file_path)
            
            # If there are any failed files, wait and retry
            if failed_files:
                # Wait for 5 seconds to allow processes to release file locks
                time.sleep(5)
                retry_files = failed_files.copy()
                failed_files.clear()
                
                # Second attempt - try each file that failed before
                for file_path in retry_files:
                    try:
                        # Try deleting the file again
                        os.remove(file_path)
                        
                        # Also delete any thumbnails
                        if file_path.suffix.lower() == '.mp4':
                            thumbnail_name = f"{file_path.stem}.jpg"
                            thumbnail_path = Path("brolls/thumbnails") / thumbnail_name
                            if thumbnail_path.exists():
                                os.remove(thumbnail_path)
                        
                        deleted_count += 1
                        logger.info(f"Deleted uploaded b-roll on second attempt: {file_path}")
                    except Exception as e:
                        logger.error(f"Second attempt: Error deleting b-roll {file_path}: {e}")
                        # Add to failed files list for final report
                        failed_files.append(file_path)
            
            # Log final summary
            if failed_files:
                logger.warning(f"Failed to delete {len(failed_files)} b-roll files after retries")
            else:
                logger.info(f"Successfully deleted all {deleted_count} b-roll files")
        
        # Schedule deletion task in background
        background_tasks.add_task(delete_with_retries)
        
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Scheduled deletion of {len(user_brolls)} uploaded b-rolls",
                "scheduled_count": len(user_brolls)
            },
            background=background_tasks
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_user_brolls: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Cleanup task
@app.on_event("startup")
async def startup_event():
    """Start cleanup task on startup and configure workers"""
    # Generate thumbnails for all videos on startup
    generate_all_thumbnails()
    
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