import { useState, useEffect } from 'react';
import axios from 'axios';

// API base URL - update this to match your FastAPI server location
const API_BASE_URL = 'http://localhost:8000';

const VideoCreator = () => {
  const [script, setScript] = useState('');
  const [musicOptions, setMusicOptions] = useState([]);
  const [selectedMusic, setSelectedMusic] = useState('');
  const [voiceOptions, setVoiceOptions] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [progress, setProgress] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const [userId, setUserId] = useState('');
  const [error, setError] = useState('');

  // Fetch music and voice options on component mount
  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const musicRes = await axios.get(`${API_BASE_URL}/music-list`);
        setMusicOptions(musicRes.data.music_files);
        setSelectedMusic(musicRes.data.music_files[0] || '');

        const voicesRes = await axios.get(`${API_BASE_URL}/voices`);
        setVoiceOptions(voicesRes.data.voices);
        setSelectedVoice(voicesRes.data.voices[0]?.id || '');
      } catch (err) {
        setError('Failed to load options: ' + err.message);
      }
    };

    fetchOptions();
  }, []);

  // Handle form submission
  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsCreating(true);
    setProgress('');
    setDownloadUrl('');
    setError('');

    try {
      // Set up Server-Sent Events
      const eventSource = new EventSource(
        `${API_BASE_URL}/create-video?script=${encodeURIComponent(script)}&music=${encodeURIComponent(selectedMusic)}&voice=${encodeURIComponent(selectedVoice)}`
      );

      eventSource.onmessage = (event) => {
        const data = event.data;
        
        if (data === 'DONE') {
          eventSource.close();
          setIsCreating(false);
          setProgress(prevProgress => prevProgress + '\nVideo created successfully!');
        } else if (data.startsWith('ERROR')) {
          eventSource.close();
          setIsCreating(false);
          setError(data.substring(7)); // Remove 'ERROR: ' prefix
        } else if (data.includes('user_id')) {
          try {
            const jsonData = JSON.parse(data);
            if (jsonData.user_id) {
              setUserId(jsonData.user_id);
            }
          } catch (e) {
            // Not JSON data, continue
          }
          setProgress(prevProgress => prevProgress + '\n' + data);
        } else {
          setProgress(prevProgress => prevProgress + '\n' + data);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        setIsCreating(false);
        setError('Connection to server lost');
      };
    } catch (err) {
      setIsCreating(false);
      setError('Failed to create video: ' + err.message);
    }
  };

  // Handle file upload
  const handleFileUpload = async (e) => {
    if (!userId) {
      setError('No user ID available. Please start video creation first.');
      return;
    }

    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('user_id', userId);

    try {
      await axios.post(`${API_BASE_URL}/upload`, formData);
      setProgress(prevProgress => prevProgress + `\nUploaded file: ${file.name}`);
    } catch (err) {
      setError('Failed to upload file: ' + err.message);
    }
  };

  // Download the created video
  const handleDownload = () => {
    if (!userId) {
      setError('No video available for download');
      return;
    }

    window.open(`${API_BASE_URL}/download/${userId}`, '_blank');
  };

  return (
    <div className="video-creator">
      <h1>Create a Video</h1>
      
      {error && <div className="error">{error}</div>}
      
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="script">Script:</label>
          <textarea
            id="script"
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={6}
            required
            disabled={isCreating}
          />
        </div>
        
        <div className="form-group">
          <label htmlFor="music">Background Music:</label>
          <select
            id="music"
            value={selectedMusic}
            onChange={(e) => setSelectedMusic(e.target.value)}
            disabled={isCreating || !musicOptions.length}
          >
            {musicOptions.map((music) => (
              <option key={music} value={music}>
                {music}
              </option>
            ))}
          </select>
        </div>
        
        <div className="form-group">
          <label htmlFor="voice">Voice:</label>
          <select
            id="voice"
            value={selectedVoice}
            onChange={(e) => setSelectedVoice(e.target.value)}
            disabled={isCreating || !voiceOptions.length}
          >
            {voiceOptions.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name}
              </option>
            ))}
          </select>
        </div>
        
        <button 
          type="submit" 
          disabled={isCreating || !script}
          className="primary-button"
        >
          {isCreating ? 'Creating...' : 'Create Video'}
        </button>
      </form>
      
      {progress && (
        <div className="progress-container">
          <h3>Progress:</h3>
          <pre className="progress-log">{progress}</pre>
        </div>
      )}
      
      {userId && !isCreating && (
        <div className="actions">
          <div className="form-group">
            <label htmlFor="fileUpload">Upload Additional File:</label>
            <input
              id="fileUpload"
              type="file"
              onChange={handleFileUpload}
              disabled={isCreating}
            />
          </div>
          
          <button
            onClick={handleDownload}
            className="download-button"
            disabled={isCreating}
          >
            Download Video
          </button>
        </div>
      )}
      
      <style jsx>{`
        .video-creator {
          max-width: 800px;
          margin: 0 auto;
          padding: 2rem;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        
        h1 {
          margin-bottom: 2rem;
          color: #333;
        }
        
        .form-group {
          margin-bottom: 1.5rem;
        }
        
        label {
          display: block;
          margin-bottom: 0.5rem;
          font-weight: 500;
        }
        
        textarea, select {
          width: 100%;
          padding: 0.75rem;
          border: 1px solid #ddd;
          border-radius: 4px;
          font-size: 1rem;
        }
        
        button {
          padding: 0.75rem 1.5rem;
          border: none;
          border-radius: 4px;
          font-size: 1rem;
          font-weight: 500;
          cursor: pointer;
        }
        
        .primary-button {
          background-color: #4f46e5;
          color: white;
        }
        
        .download-button {
          background-color: #22c55e;
          color: white;
        }
        
        button:disabled {
          opacity: 0.7;
          cursor: not-allowed;
        }
        
        .error {
          padding: 1rem;
          background-color: #fee2e2;
          border: 1px solid #ef4444;
          border-radius: 4px;
          color: #b91c1c;
          margin-bottom: 1.5rem;
        }
        
        .progress-container {
          margin-top: 2rem;
        }
        
        .progress-log {
          background-color: #f9fafb;
          border: 1px solid #ddd;
          border-radius: 4px;
          padding: 1rem;
          max-height: 300px;
          overflow-y: auto;
          font-family: monospace;
          white-space: pre-wrap;
        }
        
        .actions {
          margin-top: 2rem;
          padding-top: 1.5rem;
          border-top: 1px solid #eee;
        }
      `}</style>
    </div>
  );
};

export default VideoCreator; 