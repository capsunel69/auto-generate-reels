# Auto-Generate Reels

Video generation application with Python FastAPI backend and React frontend.

## Project Structure

The project consists of two main parts:
1. **FastAPI Backend**: Processes video creation requests and serves files
2. **React Frontend**: Provides the user interface for the application

## Directory Structure

```
auto-generate-reels/
├── app/
│   ├── fastapi_app.py      # FastAPI application
│   ├── video_creator.py    # Video creation logic
│   └── run_api.py         # API server runner
├── brolls/
│   ├── default/           # Default b-roll videos and images
│   └── user_uploads/      # User-uploaded b-roll content
├── music/                 # Background music files
├── react-example/
│   └── VideoCreator.jsx   # React component for video creation
└── requirements.txt       # Python dependencies
```

## Setup Instructions

### Backend Setup

1. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up environment variables in a `.env` file:
   ```
   ELEVENLABS_API_KEY=your_elevenlabs_api_key
   OPENAI_API_KEY=your_openai_api_key
   GOOGLE_APPLICATION_CREDENTIALS=path_to_google_credentials.json
   ```

3. Start the FastAPI server:
   ```bash
   cd app
   python run_api.py
   ```
   
   The server will start on http://localhost:8000

### Frontend Setup

1. Create a new Vite React app if you don't have one already:
   ```bash
   npm create vite@latest my-video-app -- --template react
   cd my-video-app
   npm install
   ```

2. Install required dependencies:
   ```bash
   npm install axios tailwindcss @tailwindcss/forms
   ```

3. Copy the `VideoCreator.jsx` component from `react-example/` to your React app's components directory.

4. Import and use the VideoCreator component in your app:
   ```jsx
   // src/App.jsx
   import { useState } from 'react'
   import VideoCreator from './components/VideoCreator'
   
   function App() {
     return (
       <div className="App">
         <VideoCreator />
       </div>
     )
   }
   
   export default App
   ```

5. Start the development server:
   ```bash
   npm run dev
   ```

## B-roll Management

The application supports two types of b-roll content:

1. **Default B-rolls**: Pre-installed videos and images in the `brolls/default/` directory
2. **User Uploads**: User-uploaded content stored in `brolls/user_uploads/`

To add default b-rolls:
1. Place your video files (MP4) or images (JPG, PNG) in the `brolls/default/` directory
2. The files will automatically appear in the b-roll selection interface

## API Endpoints

The FastAPI backend provides the following endpoints:

- `GET /`: API root
- `GET /music-list`: List available music files
- `GET /voices`: List available voices
- `GET /brolls`: List available b-rolls (both default and user uploads)
- `POST /upload-broll`: Upload a new b-roll file
- `DELETE /brolls/{type}/{filename}`: Delete a b-roll file
- `POST /create-video`: Create a new video (Server-Sent Events for progress)
- `GET /download/{video_id}`: Download the generated video

## Environment Variables

Create a `.env` file in the backend directory with the following variables:

```
ELEVENLABS_API_KEY=your_elevenlabs_api_key
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=path_to_google_credentials.json
```

## Troubleshooting

- **CORS Issues**: The FastAPI backend has CORS configured to allow all origins during development. For production, update the `allow_origins` list in `fastapi_app.py`.
- **File Upload Issues**: Ensure the `brolls` directory and its subdirectories have proper write permissions.
- **Video Creation Errors**: Check the console logs for detailed error messages. Common issues include missing API keys or insufficient disk space.

## Production Deployment

For production deployment:

1. Update CORS settings in `fastapi_app.py` to only allow your frontend domain
2. Set up proper environment variables
3. Use a production-grade server like Gunicorn with Uvicorn workers
4. Consider using a CDN for serving static files (b-rolls, music)
5. Implement proper authentication and rate limiting
6. Set up proper logging and monitoring

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request
