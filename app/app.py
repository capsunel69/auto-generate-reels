# app.py
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from flask import Flask, request, render_template_string, jsonify, send_file, Response
from video_creator import create_romanian_video

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
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Create Romanian Video</h1>
                <form method="post" id="videoForm">
                    <textarea name="script" rows="10" cols="30" placeholder="Enter Romanian script here..." required></textarea><br>
                    <input type="submit" value="Create Video">
                </form>
                <div id="progress"></div>
                <a href="/download" id="downloadBtn" class="download-btn">Download Video</a>
            </div>
            <script>
    document.getElementById('videoForm').onsubmit = function(event) {
        event.preventDefault();
        const form = event.target;
        const progressDiv = document.getElementById('progress');
        const downloadBtn = document.getElementById('downloadBtn');

        // Reset and show progress div
        progressDiv.style.display = 'block';
        progressDiv.innerHTML = '';
        downloadBtn.style.display = 'none';

        const script = form.querySelector('textarea[name="script"]').value;
        const eventSource = new EventSource(`/progress?script=${encodeURIComponent(script)}`);

        eventSource.onmessage = function(event) {
            if (event.data === 'DONE') {
                eventSource.close();
                downloadBtn.style.display = 'inline-block';
                progressDiv.innerHTML += '<br><span class="success-message">Video created successfully!</span>';
            } else if (event.data.startsWith('ERROR:')) {
                eventSource.close();
                progressDiv.innerHTML += '<br><span class="error-message">' + event.data.substring(7) + '</span>';
            } else {
                progressDiv.innerHTML += event.data + '<br>';
                progressDiv.scrollTop = progressDiv.scrollHeight;
            }
        };

        eventSource.onerror = function() {
            eventSource.close();
            progressDiv.innerHTML += '<br><span class="error-message">Connection lost</span>';
        };
    };
</script>
        </body>
        </html>
    ''')

@app.route('/download')
def download_video():
    try:
        return send_file('final_video_with_subs.mp4', as_attachment=True)
    except Exception as e:
        return str(e), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)