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
                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    font-family: Arial, sans-serif;
                    background-color: #f0f0f0;
                }
                .container {
                    background-color: #fff;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                    text-align: center;
                    width: 80%;
                    max-width: 500px;
                }
                textarea {
                    width: 100%;
                    margin-bottom: 10px;
                    border-radius: 4px;
                    border: 1px solid #ccc;
                }
                input[type="submit"] {
                    background-color: #007bff;
                    color: white;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                }
                input[type="submit"]:hover {
                    background-color: #0056b3;
                }
                .success-message {
                    color: #28a745;
                    margin-top: 15px;
                    font-weight: bold;
                }
                .error-message {
                    color: #dc3545;
                    margin-top: 15px;
                    font-weight: bold;
                }
                .download-btn {
                    display: none;
                    background-color: #28a745;
                    color: white;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-top: 15px;
                    text-decoration: none;
                }
                .download-btn:hover {
                    background-color: #218838;
                }
                #progress {
                    margin-top: 20px;
                    font-size: 14px;
                    color: #555;
                    text-align: left;
                    padding: 10px;
                    background-color: #f8f9fa;
                    border-radius: 4px;
                    display: none;
                    max-height: 200px;
                    overflow-y: auto;
                }
                .progress-bar {
                    width: 100%;
                    height: 20px;
                    background-color: #f0f0f0;
                    border-radius: 10px;
                    margin: 10px 0;
                    overflow: hidden;
                    display: none;
                }
                .progress-bar-fill {
                    height: 100%;
                    background-color: #007bff;
                    width: 0%;
                    transition: width 0.5s ease-in-out;
                }
                .file-input {
                    margin-bottom: 15px;
                }
                .file-input-label {
                    display: block;
                    margin-bottom: 5px;
                    color: #555;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Create Romanian Video</h1>
                <form method="post" id="videoForm" enctype="multipart/form-data">
                    <div class="file-input">
                        <label class="file-input-label">Upload B-roll Video (MP4 format)</label>
                        <input type="file" name="broll" accept="video/mp4" required>
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
                    
                    // Upload the file first
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
        return jsonify({'success': False, 'error': 'No file uploaded'})
    
    file = request.files['broll']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    if file:
        # Save the uploaded file
        upload_path = os.path.join(app.root_path, 'uploads')
        os.makedirs(upload_path, exist_ok=True)
        file_path = os.path.join(upload_path, 'uploaded_broll.mp4')
        file.save(file_path)
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'File upload failed'})

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

        @after_this_request
        def cleanup(response):
            current_app.logger.info("Starting cleanup after download...")
            
            # Schedule delayed cleanup for both files
            delayed_cleanup('uploads/uploaded_broll.mp4')  # Ensure B-roll is cleaned up
            delayed_cleanup(video_path)  # Ensure final video is cleaned up
            
            return response

        return send_file(video_path, as_attachment=True)
    except Exception as e:
        current_app.logger.error(f"Download error: {e}")
        return str(e), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)