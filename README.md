# Auto-Generate Reels

Video generation application with Python backend and React frontend.

## Project Structure

The project consists of two main parts:
1. **FastAPI Backend**: Processes video creation requests and serves files
2. **React Frontend**: Provides the user interface for the application

## Setup Instructions

### Backend Setup

1. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Start the FastAPI server:
   ```bash
   cd app
   python fastapi_app.py
   ```
   
   The server will start on http://localhost:8000

### Frontend Setup

Your React Vite frontend should be in a separate directory. Follow these steps to set it up:

1. Create a new Vite React app if you don't have one already:
   ```bash
   npm create vite@latest my-video-app -- --template react
   cd my-video-app
   npm install
   ```

2. Install required dependencies:
   ```bash
   npm install axios
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

## API Endpoints

The FastAPI backend provides the following endpoints:

- `GET /`: API root
- `GET /music-list`: List available music files
- `GET /voices`: List available voices
- `POST /create-video`: Create a new video (Server-Sent Events for progress)
- `GET /download/{video_id}`: Download the generated video
- `POST /upload`: Upload additional files
- `POST /reorder`: Reorder files for the video

## Environment Variables

If your app requires specific environment variables, create a `.env` file in the backend directory with necessary values.

## Troubleshooting

- **CORS Issues**: The FastAPI backend has CORS configured to allow all origins during development. For production, update the `allow_origins` list in `fastapi_app.py`.
- **Connection Problems**: Ensure the API_BASE_URL in the React component matches your FastAPI server address.
