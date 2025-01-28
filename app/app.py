# app.py
from dotenv import load_dotenv
import os
from flask import after_this_request, current_app
import time
import threading

# Load environment variables from .env file
load_dotenv()

from flask import Flask, request, render_template_string, jsonify, send_file, Response
from video_creator import create_romanian_video, cleanup_broll

app = Flask(__name__)

@app.route('/progress')
def progress_stream():
    romanian_script = request.args.get('script', '')

    def generate():
        def progress_callback(message):
            yield f"data: {message}\n\n"

        try:
            yield "data: Starting video creation...\n\n"
            for message in create_romanian_video(romanian_script, progress_callback):
                yield message
            yield "data: DONE\n\n"
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/', methods=['GET'])
def create_video():
    return render_template_string('''
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Create Romanian Video</title>
            <style>
                :root {
                    --primary-color: #4f46e5;
                    --primary-hover: #4338ca;
                    --success-color: #22c55e;
                    --success-hover: #16a34a;
                    --error-color: #ef4444;
                    --background: #f9fafb;
                    --card-bg: #ffffff;
                    --text-primary: #111827;
                    --text-secondary: #6b7280;
                }

                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    font-family: 'Inter', system-ui, -apple-system, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: var(--text-primary);
                    line-height: 1.5;
                }

                .container {
                    background-color: var(--card-bg);
                    padding: 2rem;
                    border-radius: 1rem;
                    box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
                    width: 90%;
                    max-width: 600px;
                    margin: 2rem;
                    backdrop-filter: blur(10px);
                }

                h1 {
                    font-size: 1.875rem;
                    font-weight: 700;
                    margin-bottom: 1.5rem;
                    color: var(--text-primary);
                }

                textarea {
                    width: 100%;
                    margin-bottom: 1rem;
                    border: 1px solid #e5e7eb;
                    border-radius: 0.5rem;
                    font-size: 1rem;
                    transition: border-color 0.15s ease-in-out;
                    resize: vertical;
                    padding: 0.75rem;
                    box-sizing: border-box;
                }

                textarea:focus {
                    outline: none;
                    border-color: var(--primary-color);
                    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
                }

                .file-input {
                    margin-bottom: 1.5rem;
                }

                .file-input-label {
                    display: block;
                    font-weight: 500;
                    margin-bottom: 0.5rem;
                    color: var(--text-secondary);
                }

                input[type="file"] {
                    width: 100%;
                    padding: 0.5rem;
                    border: 1px dashed #e5e7eb;
                    border-radius: 0.5rem;
                    background-color: #f9fafb;
                    box-sizing: border-box;
                }

                input[type="submit"] {
                    background-color: var(--primary-color);
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border: none;
                    border-radius: 0.5rem;
                    font-weight: 500;
                    cursor: pointer;
                    transition: background-color 0.15s ease-in-out;
                    width: 100%;
                }

                input[type="submit"]:hover {
                    background-color: var(--primary-hover);
                }

                .progress-bar {
                    width: 100%;
                    height: 0.5rem;
                    background-color: #e5e7eb;
                    border-radius: 1rem;
                    margin: 1.5rem 0;
                    overflow: hidden;
                    display: none;
                }

                .progress-bar-fill {
                    height: 100%;
                    background-color: var(--primary-color);
                    width: 0%;
                    transition: width 0.3s ease-in-out;
                }

                #progress {
                    margin-top: 1.5rem;
                    font-size: 0.875rem;
                    color: var(--text-secondary);
                    background-color: #f8fafc;
                    border-radius: 0.5rem;
                    padding: 1rem;
                    display: none;
                    max-height: 200px;
                    overflow-y: auto;
                    border: 1px solid #e5e7eb;
                }

                .success-message {
                    color: var(--success-color);
                    font-weight: 500;
                }

                .error-message {
                    color: var(--error-color);
                    font-weight: 500;
                }

                .download-btn {
                    display: none;
                    background-color: var(--success-color);
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border: none;
                    border-radius: 0.5rem;
                    font-weight: 500;
                    cursor: pointer;
                    text-decoration: none;
                    text-align: center;
                    margin-top: 1rem;
                    transition: background-color 0.15s ease-in-out;
                }

                .download-btn:hover {
                    background-color: var(--success-hover);
                }

                /* Add smooth scrollbar for progress div */
                #progress::-webkit-scrollbar {
                    width: 8px;
                }

                #progress::-webkit-scrollbar-track {
                    background: #f1f1f1;
                    border-radius: 4px;
                }

                #progress::-webkit-scrollbar-thumb {
                    background: #cbd5e1;
                    border-radius: 4px;
                }

                #progress::-webkit-scrollbar-thumb:hover {
                    background: #94a3b8;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Create Romanian Video</h1>
                <form method="post" id="videoForm" enctype="multipart/form-data">
                    <div class="file-input">
                        <label class="file-input-label">Upload B-roll Videos and Images (MP4, JPG, JPEG, PNG)</label>
                        <input type="file" name="broll" accept="video/mp4,image/jpeg,image/jpg,image/png" multiple required>
                    </div>
                    <textarea name="script" rows="10" cols="30" placeholder="Enter Romanian script here..." required></textarea><br>
                    <input type="submit" value="Create Video">
                </form>
                <div class="progress-bar">
                    <div class="progress-bar-fill"></div>
                </div>
                <div id="progress"></div>
                <a href="/download" id="downloadBtn" class="download-btn">Download Video</a>
            </div>
            <script>
                document.getElementById('videoForm').onsubmit = function(event) {
                    event.preventDefault();
                    const form = event.target;
                    const progressDiv = document.getElementById('progress');
                    const progressBar = document.querySelector('.progress-bar');
                    const progressBarFill = document.querySelector('.progress-bar-fill');
                    const downloadBtn = document.getElementById('downloadBtn');

                    // Reset and show progress elements
                    progressDiv.style.display = 'block';
                    progressBar.style.display = 'block';
                    progressDiv.innerHTML = '';
                    progressBarFill.style.width = '0%';
                    downloadBtn.style.display = 'none';

                    // Create FormData object to handle file upload
                    const formData = new FormData(form);
                    
                    // Upload the files first
                    fetch('/upload', {
                        method: 'POST',
                        body: formData
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            // Start SSE connection after successful upload
                            const script = form.querySelector('textarea[name="script"]').value;
                            const eventSource = new EventSource(`/progress?script=${encodeURIComponent(script)}`);
                            
                            eventSource.onmessage = function(event) {
                                if (event.data === 'DONE') {
                                    eventSource.close();
                                    downloadBtn.style.display = 'inline-block';
                                    progressDiv.innerHTML += '<br><span class="success-message">Video created successfully!</span>';
                                    progressBarFill.style.width = '100%';
                                } else if (event.data.startsWith('ERROR:')) {
                                    eventSource.close();
                                    progressDiv.innerHTML += '<br><span class="error-message">' + event.data.substring(7) + '</span>';
                                } else {
                                    const [message, percentage] = event.data.split('|');
                                    if (percentage) {
                                        progressBarFill.style.width = percentage + '%';
                                    }
                                    progressDiv.innerHTML += message + '<br>';
                                    progressDiv.scrollTop = progressDiv.scrollHeight;
                                }
                            };

                            eventSource.onerror = function() {
                                eventSource.close();
                                progressDiv.innerHTML += '<br><span class="error-message">Connection lost</span>';
                            };
                        } else {
                            progressDiv.innerHTML += '<br><span class="error-message">' + data.error + '</span>';
                        }
                    })
                    .catch(error => {
                        progressDiv.innerHTML += '<br><span class="error-message">Upload failed: ' + error.message + '</span>';
                    });
                };
            </script>
        </body>
        </html>
    ''')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'broll' not in request.files:
        return jsonify({'success': False, 'error': 'No files uploaded'})
    
    files = request.files.getlist('broll')
    if not files or files[0].filename == '':
        return jsonify({'success': False, 'error': 'No files selected'})
    
    upload_path = os.path.join(app.root_path, 'uploads')
    os.makedirs(upload_path, exist_ok=True)
    
    # Clean up any existing b-roll files
    for existing_file in os.listdir(upload_path):
        if existing_file.startswith("uploaded_broll_"):
            try:
                os.remove(os.path.join(upload_path, existing_file))
            except:
                pass
    
    # Save the new files
    for i, file in enumerate(files):
        if file and file.filename.lower().endswith(('.mp4', '.jpg', '.jpeg', '.png')):
            # Keep the original file extension
            ext = os.path.splitext(file.filename)[1].lower()
            file_path = os.path.join(upload_path, f'uploaded_broll_{i}{ext}')
            file.save(file_path)
    
    return jsonify({'success': True})

def delayed_cleanup(file_path, delay=5):
    """Attempt to delete a file after a delay with multiple retries."""
    def cleanup():
        with app.app_context():
            # First delay to let initial processes finish
            time.sleep(delay)
            
            # Try up to 3 times with increasing delays
            for attempt in range(3):
                try:
                    if os.path.exists(file_path):
                        # Force Python to release any handles it might have
                        import gc
                        gc.collect()
                        
                        os.remove(file_path)
                        current_app.logger.info(f"File {file_path} cleaned up successfully on attempt {attempt + 1}")
                        break
                    else:
                        current_app.logger.info(f"File {file_path} already deleted")
                        break
                except Exception as e:
                    current_app.logger.error(f"Cleanup attempt {attempt + 1} failed for {file_path}: {e}")
                    time.sleep(delay * (attempt + 1))  # Increase delay with each attempt

    threading.Thread(target=cleanup).start()

@app.route('/download')
def download_video():
    try:
        video_path = 'final_video_with_subs.mp4'
        if not os.path.exists(video_path):
            return "Video file not found", 404
        
        allowed_extensions = ('.mp4', '.jpg', '.jpeg', '.png')
        
        @after_this_request
        def cleanup(response):
            current_app.logger.info("Starting cleanup after download...")
            
            # Schedule delayed cleanup for uploads directory and final video
            uploads_dir = os.path.join(app.root_path, 'uploads')
            for file in os.listdir(uploads_dir):
                if file.startswith("uploaded_broll_") and file.lower().endswith(allowed_extensions):
                    delayed_cleanup(os.path.join(uploads_dir, file))
            
            delayed_cleanup(video_path)  # Ensure final video is cleaned up
            
            return response

        return send_file(video_path, as_attachment=True)
    except Exception as e:
        current_app.logger.error(f"Download error: {e}")
        return str(e), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)