# app.py
from dotenv import load_dotenv
import os
from flask import after_this_request, current_app
import time
import threading
import json

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

@app.route('/video-creator', methods=['GET'])
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

                .file-preview {
                    margin: 1rem 0;
                    display: none;
                }

                .file-list {
                    list-style: none;
                    padding: 0;
                    margin: 0;
                }

                .file-item {
                    display: flex;
                    align-items: center;
                    padding: 0.5rem;
                    margin: 0.25rem 0;
                    background: #f8fafc;
                    border: 1px solid #e5e7eb;
                    border-radius: 0.5rem;
                    cursor: move;
                }

                .file-item:hover {
                    background: #f1f5f9;
                }

                .file-item img {
                    width: 60px;
                    height: 60px;
                    object-fit: cover;
                    margin-right: 1rem;
                    border-radius: 0.25rem;
                }

                .file-item .file-name {
                    flex-grow: 1;
                }

                .file-item .remove-file {
                    color: var(--error-color);
                    cursor: pointer;
                    padding: 0.25rem 0.5rem;
                }

                .drag-handle {
                    cursor: move;
                    padding: 0.5rem;
                    color: var(--text-secondary);
                }

                .nav-menu {
                    display: flex;
                    justify-content: center;
                    gap: 1rem;
                    margin-bottom: 2rem;
                }

                .nav-link {
                    padding: 0.5rem 1rem;
                    text-decoration: none;
                    color: var(--text-primary);
                    background-color: var(--card-bg);
                    border-radius: 0.5rem;
                    transition: all 0.15s ease-in-out;
                    border: 1px solid #e5e7eb;
                }

                .nav-link:hover {
                    background-color: var(--primary-color);
                    color: white;
                }

                .nav-link.active {
                    background-color: var(--primary-color);
                    color: white;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="nav-menu">
                    <a href="/scraper" class="nav-link">News Scraper</a>
                    <a href="/video-creator" class="nav-link active">Video Creator</a>
                    <a href="/" class="nav-link">Back Home</a>
                </div>
                <h1>Create Romanian Video</h1>
                <form method="post" id="videoForm" enctype="multipart/form-data">
                    <div class="file-input">
                        <label class="file-input-label">Upload B-roll Videos and Images (MP4, JPG, JPEG, PNG)</label>
                        <input type="file" name="broll" accept="video/mp4,image/jpeg,image/jpg,image/png" multiple required>
                    </div>
                    <div class="file-preview">
                        <h3>Uploaded Files (drag to reorder)</h3>
                        <ul class="file-list" id="fileList"></ul>
                    </div>
                    <textarea name="script" id="scriptInput" rows="10" cols="30" placeholder="Enter Romanian script here..." required></textarea><br>
                    <input type="submit" value="Create Video">
                </form>
                <div class="progress-bar">
                    <div class="progress-bar-fill"></div>
                </div>
                <div id="progress"></div>
                <a href="/download" id="downloadBtn" class="download-btn">Download Video</a>
            </div>
            <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.14.0/Sortable.min.js"></script>
            <script>
                // Initialize drag-and-drop functionality
                new Sortable(document.getElementById('fileList'), {
                    animation: 150,
                    handle: '.drag-handle'
                });

                document.querySelector('input[type="file"]').addEventListener('change', function(e) {
                    const fileList = document.getElementById('fileList');
                    const filePreview = document.querySelector('.file-preview');
                    fileList.innerHTML = '';
                    filePreview.style.display = 'block';

                    Array.from(e.target.files).forEach((file, index) => {
                        const li = document.createElement('li');
                        li.className = 'file-item';
                        li.dataset.filename = file.name;
                        
                        const dragHandle = document.createElement('span');
                        dragHandle.className = 'drag-handle';
                        dragHandle.innerHTML = '⋮⋮';
                        
                        const preview = document.createElement(file.type.startsWith('video/') ? 'video' : 'img');
                        if (file.type.startsWith('video/')) {
                            preview.src = URL.createObjectURL(file);
                            preview.style.width = '60px';
                            preview.style.height = '60px';
                        } else {
                            preview.src = URL.createObjectURL(file);
                        }
                        
                        const fileName = document.createElement('span');
                        fileName.className = 'file-name';
                        fileName.textContent = file.name;
                        
                        const removeBtn = document.createElement('span');
                        removeBtn.className = 'remove-file';
                        removeBtn.textContent = '×';
                        removeBtn.onclick = function() {
                            li.remove();
                            if (fileList.children.length === 0) {
                                filePreview.style.display = 'none';
                            }
                        };
                        
                        li.appendChild(dragHandle);
                        li.appendChild(preview);
                        li.appendChild(fileName);
                        li.appendChild(removeBtn);
                        fileList.appendChild(li);
                    });
                });

                document.getElementById('videoForm').onsubmit = async function(event) {
                    event.preventDefault();
                    const form = event.target;
                    const fileList = document.getElementById('fileList');
                    const formData = new FormData(form);

                    // Get the actual order of files after drag and drop
                    const fileOrder = Array.from(fileList.children).map(li => li.dataset.filename);

                    // Reset and show progress elements
                    const progressDiv = document.getElementById('progress');
                    const progressBar = document.querySelector('.progress-bar');
                    const progressBarFill = document.querySelector('.progress-bar-fill');
                    const downloadBtn = document.getElementById('downloadBtn');

                    progressDiv.style.display = 'block';
                    progressBar.style.display = 'block';
                    progressDiv.innerHTML = '';
                    progressBarFill.style.width = '0%';
                    downloadBtn.style.display = 'none';

                    try {
                        // First upload the files
                        const uploadResponse = await fetch('/upload', {
                            method: 'POST',
                            body: formData
                        });
                        const uploadData = await uploadResponse.json();
                        
                        if (!uploadData.success) {
                            throw new Error(uploadData.error || 'Upload failed');
                        }

                        // Then reorder the files using the actual UI order
                        const reorderResponse = await fetch('/reorder', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                file_order: fileOrder  // Send the actual filenames in UI order
                            })
                        });
                        const reorderData = await reorderResponse.json();
                        
                        if (!reorderData.success) {
                            throw new Error(reorderData.error || 'Reorder failed');
                        }

                        // Finally start video creation
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
                    } catch (error) {
                        progressDiv.innerHTML += '<br><span class="error-message">Error: ' + error.message + '</span>';
                    }
                };

                // Add this at the start of your script section
                window.onload = function() {
                    // Check if there's a transferred script
                    const transferredScript = localStorage.getItem('transferScript');
                    if (transferredScript) {
                        document.getElementById('scriptInput').value = transferredScript;
                        // Clear the stored script
                        localStorage.removeItem('transferScript');
                    }
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
    
    # Save files with sequential names and track original names
    saved_files = []
    filename_mapping = {}  # Map original names to uploaded names
    
    for i, file in enumerate(files):
        if file and file.filename.lower().endswith(('.mp4', '.jpg', '.jpeg', '.png')):
            uploaded_filename = f'uploaded_broll_{i}.mp4'
            file_path = os.path.join(upload_path, uploaded_filename)
            file.save(file_path)
            saved_files.append(uploaded_filename)
            filename_mapping[file.filename] = uploaded_filename
            print(f"Saved {file.filename} as {uploaded_filename}")
    
    # Save both the initial order and the filename mapping
    with open(os.path.join(upload_path, 'order.json'), 'w') as f:
        json.dump(saved_files, f)
    
    with open(os.path.join(upload_path, 'filename_mapping.json'), 'w') as f:
        json.dump(filename_mapping, f)
    
    return jsonify({'success': True})

@app.route('/reorder', methods=['POST'])
def reorder_files():
    """Handle reordering of already uploaded files"""
    try:
        upload_path = os.path.join(app.root_path, 'uploads')
        data = request.get_json()
        original_order = data.get('file_order', [])
        
        # Load the filename mapping
        with open(os.path.join(upload_path, 'filename_mapping.json'), 'r') as f:
            filename_mapping = json.load(f)
        
        # Convert original filenames to uploaded filenames
        new_order = [filename_mapping[original_name] for original_name in original_order]
        
        # Save the new order
        with open(os.path.join(upload_path, 'order.json'), 'w') as f:
            json.dump(new_order, f)
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error during reordering: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

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

@app.route('/scraper', methods=['GET', 'POST'])
def scraper():
    if request.method == 'POST':
        data = request.get_json()
        url = data.get('url')
        custom_prompt = data.get('custom_prompt')
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'})
        
        from news_scraper import create_news_script
        script = create_news_script(url, custom_prompt)
        return jsonify({'success': True, 'script': script})
    
    # Initial prompt from news_scraper.py
    initial_prompt = """
    Create a short, engaging script in Romanian for a TikTok news video (30-60 seconds). 
    The script should:
    - Start with an extremely captivating hook in the first 3 seconds
    - Use pattern interrupts or shocking facts to grab attention
    - Be conversational and engaging
    - Focus on the most important facts
    - Be clear and concise
    - Use simple Romanian language that's easy to understand
    - Be around 100-150 words
    - Only include the script text, no suggestions or additional formatting
    
    Important: The entire response must be in Romanian language.
    """
    
    return render_template_string('''
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>News Scraper</title>
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

                .form-group {
                    margin-bottom: 1.5rem;
                }

                label {
                    display: block;
                    margin-bottom: 0.5rem;
                    font-weight: 500;
                    color: var(--text-secondary);
                }

                input[type="url"], textarea {
                    width: 100%;
                    padding: 0.75rem;
                    border: 1px solid #e5e7eb;
                    border-radius: 0.5rem;
                    font-size: 1rem;
                    transition: border-color 0.15s ease-in-out;
                    box-sizing: border-box;
                }

                input[type="url"]:focus, textarea:focus {
                    outline: none;
                    border-color: var(--primary-color);
                    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
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

                .nav-menu {
                    display: flex;
                    justify-content: center;
                    gap: 1rem;
                    margin-bottom: 2rem;
                }

                .nav-link {
                    padding: 0.5rem 1rem;
                    text-decoration: none;
                    color: var(--text-primary);
                    background-color: var(--card-bg);
                    border-radius: 0.5rem;
                    transition: all 0.15s ease-in-out;
                    border: 1px solid #e5e7eb;
                }

                .nav-link:hover {
                    background-color: var(--primary-color);
                    color: white;
                }

                .nav-link.active {
                    background-color: var(--primary-color);
                    color: white;
                }
                
                                .success-message {
                    color: var(--success-color);
                    font-weight: 500;
                }

                .error-message {
                    color: var(--error-color);
                    font-weight: 500;
                }
                
                #progress {
                    margin-top: 1.5rem;
                    font-size: 0.875rem;
                    color: var(--text-secondary);
                    background-color: #f8fafc;
                    border-radius: 0.5rem;
                    padding: 1rem;
                    border: 1px solid #e5e7eb;
                }

                #result {
                    margin-top: 1.5rem;
                    width: 100%;
                    font-size: 0.875rem;
                    color: var(--text-primary);
                    background-color: #f8fafc;
                    border-radius: 0.5rem;
                    padding: 1rem;
                    border: 1px solid #e5e7eb;
                }

                #result:focus {
                    outline: none;
                    border-color: var(--primary-color);
                    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
                }

                .use-script-btn {
                    display: none;
                    background-color: var(--success-color);
                    color: white;
                    padding: 0.75rem 1.5rem;
                    border: none;
                    border-radius: 0.5rem;
                    font-weight: 500;
                    cursor: pointer;
                    transition: background-color 0.15s ease-in-out;
                    width: 100%;
                    margin-top: 1rem;
                }

                .use-script-btn:hover {
                    background-color: var(--success-hover);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="nav-menu">
                    <a href="/scraper" class="nav-link active">News Scraper</a>
                    <a href="/video-creator" class="nav-link">Video Creator</a>
                    <a href="/" class="nav-link">Back Home</a>
                </div>
                <h1>News Article Scraper</h1>
                <form id="scraperForm">
                    <div class="form-group">
                        <label for="url">News Article URL:</label>
                        <input type="url" name="url" placeholder="Enter news article URL..." required>
                    </div>
                    <div class="form-group">
                        <label for="customPrompt">Customize OpenAI Prompt:</label>
                        <textarea name="custom_prompt" id="customPrompt" rows="10">{{ initial_prompt }}</textarea>
                    </div>
                    <input type="submit" value="Generate Script">
                </form>
                <div id="progress" style="display: none;"></div>
                <textarea id="result" style="display: none;" rows="10"></textarea>
                <button id="useScript" style="display: none;" class="use-script-btn">Use Script in Video Creator</button>
            </div>
            <script>
                document.getElementById('scraperForm').onsubmit = async function(e) {
                    e.preventDefault();
                    const form = e.target;
                    const url = form.url.value;
                    const customPrompt = form.customPrompt.value;
                    const progress = document.getElementById('progress');
                    const result = document.getElementById('result');
                    const useScriptBtn = document.getElementById('useScript');
                    
                    progress.style.display = 'block';
                    progress.innerHTML = '<span class="success-message">Generating script...</span>';
                    result.style.display = 'none';
                    result.value = '';
                    useScriptBtn.style.display = 'none';
                    
                    try {
                        const response = await fetch('/scrape', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ url: url, custom_prompt: customPrompt })
                        });
                        
                        const data = await response.json();
                        if (data.success) {
                            progress.innerHTML = '<span class="success-message">Script generated successfully!</span>';
                            result.style.display = 'block';
                            result.value = data.script.slice(1, -1);
                            useScriptBtn.style.display = 'block';
                        } else {
                            progress.innerHTML = '<span class="error-message">Error: ' + data.error + '</span>';
                        }
                    } catch (error) {
                        progress.innerHTML = '<span class="error-message">Error: ' + error.message + '</span>';
                    }
                };

                document.getElementById('useScript').onclick = function() {
                    const script = document.getElementById('result').value;
                    // Store the script in localStorage
                    localStorage.setItem('transferScript', script);
                    // Redirect to video creator
                    window.location.href = '/video-creator';
                };
            </script>
        </body>
        </html>
    ''', initial_prompt=initial_prompt)

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        data = request.get_json()
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'})
        
        from news_scraper import create_news_script
        script = create_news_script(url)
        return jsonify({'success': True, 'script': script})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/')
def home():
    return render_template_string('''
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>AI Video Creator</title>
            <style>
                :root {
                    --primary-color: #4f46e5;
                    --primary-hover: #4338ca;
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
                    padding: 3rem;
                    border-radius: 1.5rem;
                    box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
                    width: 90%;
                    max-width: 800px;
                    margin: 2rem;
                    backdrop-filter: blur(10px);
                    text-align: center;
                }

                .logo {
                    font-size: 2.5rem;
                    font-weight: 800;
                    color: var(--primary-color);
                    margin-bottom: 1rem;
                    letter-spacing: -0.025em;
                }

                h1 {
                    font-size: 3.5rem;
                    font-weight: 800;
                    margin-bottom: 1.5rem;
                    color: var(--text-primary);
                    line-height: 1.2;
                    letter-spacing: -0.025em;
                }

                .tagline {
                    font-size: 1.25rem;
                    color: var(--text-secondary);
                    margin-bottom: 3rem;
                    max-width: 600px;
                    margin-left: auto;
                    margin-right: auto;
                }

                .tools-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 2rem;
                    margin-top: 3rem;
                }

                .tool-card {
                    background: var(--background);
                    padding: 2rem;
                    border-radius: 1rem;
                    text-decoration: none;
                    color: var(--text-primary);
                    transition: all 0.3s ease;
                    border: 1px solid #e5e7eb;
                }

                .tool-card:hover {
                    transform: translateY(-5px);
                    box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
                    border-color: var(--primary-color);
                }

                .tool-icon {
                    font-size: 2rem;
                    margin-bottom: 1rem;
                }

                .tool-title {
                    font-size: 1.25rem;
                    font-weight: 600;
                    margin-bottom: 0.5rem;
                }

                .tool-description {
                    font-size: 0.875rem;
                    color: var(--text-secondary);
                }

                .gradient-text {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="logo">🎥 AI Video Creator</div>
                <h1>Transform Your Content<br><span class="gradient-text">Into Engaging Videos</span></h1>
                <p class="tagline">
                    Streamline your content creation process with our AI-powered tools. 
                    From news scraping to video generation, create compelling content in minutes.
                </p>
                
                <div class="tools-grid">
                    <a href="/scraper" class="tool-card">
                        <div class="tool-icon">📰</div>
                        <div class="tool-title">News Scraper</div>
                        <div class="tool-description">
                            Transform news articles into well-structured scripts ready for video production.
                        </div>
                    </a>
                    
                    <a href="/video-creator" class="tool-card">
                        <div class="tool-icon">🎬</div>
                        <div class="tool-title">Video Creator</div>
                        <div class="tool-description">
                            Create professional videos with custom B-roll footage and automated subtitles.
                        </div>
                    </a>
                </div>
            </div>
            <div class="footer">
                Made with <span class="heart">❤️</span> by Capsuna Kukeritoru
            </div>
            <style>
                .footer {
                    position: fixed;
                    bottom: 60px;
                    left: 50%;
                    transform: translateX(-50%);
                    background-color: rgba(255, 255, 255, 0.9);
                    padding: 8px 20px;
                    border-radius: 20px;
                    font-size: 0.9rem;
                    color: var(--text-secondary);
                    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                    backdrop-filter: blur(5px);
                }

                .heart {
                    display: inline-block;
                    animation: heartbeat 1.5s ease infinite;
                }

                @keyframes heartbeat {
                    0% { transform: scale(1); }
                    50% { transform: scale(1.2); }
                    100% { transform: scale(1); }
                }
            </style>
        </body>
        </html>
    ''')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)