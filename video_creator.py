import openai
import requests
import os
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, TextClip, CompositeVideoClip, ImageClip, VideoClip, CompositeAudioClip, concatenate_audioclips
from moviepy.audio.fx import MultiplyVolume
import math
import pysrt
import time
from pathlib import Path
import random
from elevenlabs import ElevenLabs
from proglog import ProgressBarLogger
from openai import OpenAI
from google.cloud import speech_v1
from google.cloud import storage
from pydub import AudioSegment
import io
import wave
from difflib import SequenceMatcher
from skimage.transform import resize
import json
import subprocess
import threading
import uuid

# Set the path to your Google Cloud credentials JSON file
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dogwood-boulder-392113-15af4dd46744.json'

def format_timestamp(seconds):
    """Convert seconds to SRT timestamp format"""
    if isinstance(seconds, (int, float)):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        milliseconds = int((secs % 1) * 1000)
        secs = int(secs)
    else:  # Handle timedelta objects
        hours = seconds.seconds // 3600
        minutes = (seconds.seconds % 3600) // 60
        secs = seconds.seconds % 60
        milliseconds = seconds.microseconds // 1000
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def timestamp_to_seconds(timestamp):
    """Convert SRT timestamp to seconds"""
    # Split into time and milliseconds parts
    time_parts, milliseconds = timestamp.split(',')
    hours, minutes, seconds = map(int, time_parts.split(':'))
    # Convert everything to seconds
    total_seconds = (hours * 3600) + (minutes * 60) + seconds + (int(milliseconds) / 1000)
    return float(total_seconds)

class SSELogger(ProgressBarLogger):
    """
    A custom logger that hooks into MoviePy's internal progress updates
    and forwards them to an SSE callback, while still preserving
    the classic console progress bar output.
    """
    def __init__(self, sse_callback=None):
        super().__init__()
        self.sse_callback = sse_callback
        self.print_progress = True
        self.current_frame = 0
        self.total_frames = 0

    def callback(self, **changes):
        # This call ensures MoviePy's built-in progress bar is displayed
        super().callback(**changes)

        # Get the message from changes
        message = changes.get('message', '')
        
        if self.sse_callback:
            if 'Building video' in message:
                self.sse_callback("Rendering video - Preparing...")
            elif 'Writing audio' in message:
                self.sse_callback("Rendering video - Processing audio...")
            elif 'Writing video' in message:
                self.sse_callback("Rendering video - Processing frames...")
            elif 'Done' in message:
                self.sse_callback("Rendering video - Finalizing...")
            elif 'frame' in changes:
                current_frame = changes.get('frame', 0)
                total = changes.get('total', 100)
                if total > 0:
                    percent = (current_frame / total) * 100
                    self.sse_callback(f"Rendering video - Processing frames ({percent:.0f}%)")

def get_word_timestamps_from_google(audio_file_path):
    """Get word-level timestamps using Google Cloud Speech-to-Text"""
    client = speech_v1.SpeechClient()

    # Convert MP3 to WAV
    audio = AudioSegment.from_mp3(audio_file_path)
    
    # Split audio into 30-second chunks if longer than 1 minute
    chunk_length = 30 * 1000  # 30 seconds in milliseconds
    words_with_times = []
    
    if len(audio) > 60 * 1000:  # If audio is longer than 1 minute
        chunks = math.ceil(len(audio) / chunk_length)
        for i in range(chunks):
            start_time = i * chunk_length
            end_time = min((i + 1) * chunk_length, len(audio))
            
            # Extract chunk
            chunk = audio[start_time:end_time]
            
            # Export chunk to WAV
            wav_data = io.BytesIO()
            chunk.export(wav_data, format="wav")
            wav_data.seek(0)
            content = wav_data.read()

            # Process chunk
            audio_input = speech_v1.RecognitionAudio(content=content)
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                language_code="ro-RO",
                enable_word_time_offsets=True,
            )

            response = client.recognize(config=config, audio=audio_input)
            
            # Process results and adjust timestamps
            time_offset = start_time / 1000.0  # Convert to seconds
            for result in response.results:
                for word in result.alternatives[0].words:
                    start_time = word.start_time.total_seconds() + time_offset
                    end_time = word.end_time.total_seconds() + time_offset
                    
                    words_with_times.append({
                        'word': word.word,
                        'start_time': start_time,
                        'end_time': end_time
                    })
    else:
        # For short audio, process as before
        wav_data = io.BytesIO()
        audio.export(wav_data, format="wav")
        wav_data.seek(0)
        content = wav_data.read()

        audio_input = speech_v1.RecognitionAudio(content=content)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code="ro-RO",
            enable_word_time_offsets=True,
        )

        response = client.recognize(config=config, audio=audio_input)
        
        for result in response.results:
            for word in result.alternatives[0].words:
                words_with_times.append({
                    'word': word.word,
                    'start_time': word.start_time.total_seconds(),
                    'end_time': word.end_time.total_seconds()
                })
    
    return words_with_times

def create_grouped_srt(words_with_times, max_words=4):
    """Create SRT content with grouped words and improved timing"""
    srt_content = []
    current_index = 1
    current_group = []
    
    MIN_DURATION = 0.7  # Minimum duration for each subtitle in seconds
    GAP_DURATION = 0.1  # Gap between subtitles in seconds
    
    for word_info in words_with_times:
        current_group.append(word_info)
        
        # Create a new subtitle when we reach max words or find punctuation
        if (len(current_group) >= max_words or 
            any(p in word_info['word'] for p in '.!?,:')):
            
            start_time = current_group[0]['start_time']
            end_time = current_group[-1]['end_time']
            
            # Ensure minimum duration
            if end_time - start_time < MIN_DURATION:
                end_time = start_time + MIN_DURATION
            
            # Add gap between subtitles if needed
            if srt_content:
                last_end_time = timestamp_to_seconds(srt_content[-1].split('\n')[1].split(' --> ')[1])
                if start_time < last_end_time + GAP_DURATION:
                    start_time = last_end_time + GAP_DURATION
                    # Adjust end_time to maintain minimum duration
                    end_time = max(end_time, start_time + MIN_DURATION)
            
            # Extend short subtitles for better readability
            duration = end_time - start_time
            if duration < MIN_DURATION:
                end_time = start_time + MIN_DURATION
            
            srt_entry = f"{current_index}\n"
            srt_entry += f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n"
            srt_entry += f"{' '.join(w['word'] for w in current_group)}\n\n"
            
            srt_content.append(srt_entry)
            current_index += 1
            current_group = []
    
    # Add any remaining words
    if current_group:
        start_time = current_group[0]['start_time']
        end_time = current_group[-1]['end_time']
        
        # Apply same timing rules to final group
        if end_time - start_time < MIN_DURATION:
            end_time = start_time + MIN_DURATION
            
        if srt_content:
            last_end_time = timestamp_to_seconds(srt_content[-1].split('\n')[1].split(' --> ')[1])
            if start_time < last_end_time + GAP_DURATION:
                start_time = last_end_time + GAP_DURATION
                end_time = max(end_time, start_time + MIN_DURATION)
        
        srt_entry = f"{current_index}\n"
        srt_entry += f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n"
        srt_entry += f"{' '.join(w['word'] for w in current_group)}\n\n"
        
        srt_content.append(srt_entry)
    
    return ''.join(srt_content)

def align_texts(original_script, recognized_words):
    """
    Align the original script words with the recognized words using their similarity
    while preserving the timestamps from recognized words.
    """
    # Split original script into words
    original_words = original_script.split()
    aligned_words = []
    
    rec_idx = 0
    orig_idx = 0
    
    while orig_idx < len(original_words):
        # If we've run out of recognized words but still have original words
        if rec_idx >= len(recognized_words):
            # Use the last recognized word's timing as a base
            if len(recognized_words) > 0:
                last_word = recognized_words[-1]
                word_duration = last_word['end_time'] - last_word['start_time']
                new_start = last_word['end_time'] + 0.1  # Add small gap
                
                # Add remaining words with estimated timing
                while orig_idx < len(original_words):
                    aligned_words.append({
                        'word': original_words[orig_idx],
                        'start_time': new_start,
                        'end_time': new_start + word_duration
                    })
                    new_start += word_duration + 0.1  # Add small gap between words
                    orig_idx += 1
            break
            
        rec_word = recognized_words[rec_idx]['word'].lower().strip('.,!?')
        orig_word = original_words[orig_idx].lower().strip('.,!?')
        
        # If words match exactly or are very similar
        if rec_word == orig_word or SequenceMatcher(None, rec_word, orig_word).ratio() > 0.8:
            aligned_words.append({
                'word': original_words[orig_idx],
                'start_time': recognized_words[rec_idx]['start_time'],
                'end_time': recognized_words[rec_idx]['end_time']
            })
            rec_idx += 1
            orig_idx += 1
        else:
            # If words don't match, estimate timing based on surrounding words
            if rec_idx < len(recognized_words):
                start_time = recognized_words[rec_idx]['start_time']
                end_time = recognized_words[rec_idx]['end_time']
                word_duration = end_time - start_time
                
                aligned_words.append({
                    'word': original_words[orig_idx],
                    'start_time': start_time,
                    'end_time': end_time
                })
            orig_idx += 1
            rec_idx += 1
    
    return aligned_words

def create_clip_from_image(image_path, duration=5):
    """Create a video clip from an image with a subtle pan/zoom effect"""
    image = ImageClip(image_path)
    
    # Resize to fit 9:16 aspect ratio while maintaining original size for zoom
    target_w, target_h = 1080, 1920
    clip_aspect = image.w / image.h
    target_aspect = target_w / target_h

    if clip_aspect > target_aspect:
        # Image is wider than 9:16
        new_width = int(image.h * (9/16))
        x_offset = (image.w - new_width) // 2
        image = image.cropped(x1=x_offset, width=new_width)
    else:
        # Image is taller than 9:16
        new_height = int(image.w * (16/9))
        y_offset = (image.h - new_height) // 2
        image = image.cropped(y1=y_offset, height=new_height)

    # Resize to slightly larger than final size to allow for zoom
    base_size = (int(target_w * 1.1), int(target_h * 1.1))
    image = image.resized(base_size)

    def make_frame(t):
        progress = t / duration
        
        # Calculate zoom factor (1.0 to 1.1)
        zoom = 1.0 + (0.1 * progress)
        
        # Get the frame
        frame = image.get_frame(0)  # Always get the first frame since it's a static image
        
        # Calculate crop dimensions
        current_w = int(target_w * zoom)
        current_h = int(target_h * zoom)
        
        # Calculate crop position to keep center
        x1 = (base_size[0] - current_w) // 2
        y1 = (base_size[1] - current_h) // 2
        
        # Crop the frame
        cropped = frame[y1:y1+current_h, x1:x1+current_w]
        
        # Resize to final dimensions
        return resize(cropped, (target_h, target_w), preserve_range=True).astype('uint8')

    # Create the clip with the new frame generator
    return VideoClip(make_frame, duration=duration)

def create_user_directory(session_id):
    """Create a unique working directory for each user session with proper isolation"""
    user_dir = os.path.join('user_sessions', session_id)
    uploads_dir = os.path.join(user_dir, 'uploads')
    
    # Ensure directories exist and are empty
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)
    
    # Clean any existing temporary files in the directory
    try:
        for filename in os.listdir(user_dir):
            if filename.startswith(('TEMP_', 'audio_file_', 'sub_file_')):
                filepath = os.path.join(user_dir, filename)
                try:
                    os.remove(filepath)
                except Exception as e:
                    print(f"Warning: Could not remove temp file {filepath}: {str(e)}")
    except Exception as e:
        print(f"Warning: Error cleaning temporary files: {str(e)}")
    
    return user_dir, uploads_dir

def srt_time_to_ass_time(srt_time):
    """Convert SRT time format to ASS time format"""
    hours = srt_time.hours
    minutes = srt_time.minutes
    seconds = srt_time.seconds
    milliseconds = srt_time.milliseconds
    
    # Format to ASS time format (H:MM:SS.cc)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds//10:02d}"

def create_subtitle_clips(srt_file, videosize, user_dir):
    """
    Convert SRT to ASS with TikTok-style subtitles:
    - Fixed groups of 2-3 words
    - Words in a group are highlighted sequentially as they're spoken
    - Then move to the next group
    - Fade effects only between groups, not for each word
    """
    try:
        import pysrt
        import random
        import os
        
        # Get the absolute path to the font file and ensure proper path formatting
        font_path = os.path.abspath(os.path.join('src', 'fonts', 'Montserrat-Black.ttf'))
        font_path = font_path.replace('\\', '/')
        
        # Verify font exists
        if not os.path.exists(font_path):
            print(f"Warning: Font not found at {font_path}, falling back to Arial")
            font_name = "Arial"
        else:
            print(f"Using font from: {font_path}")
            font_name = "Montserrat-Black"

        # Create ASS file in user directory
        ass_file = os.path.join(user_dir, "subtitles.ass")
        
        ass_content = f"""[Script Info]
Title: Romanian Video Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; Default style - for words not currently being spoken
Style: Default,{font_name},64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4,0,2,400,400,30,1
; Highlighted style - for words currently being spoken
Style: Highlight,{font_name},64,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4,0,2,400,400,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Try to extract individual word information from the JSON timing file
        words_with_times = []
        try:
            # Check if we have our original words_with_times data
            words_file = os.path.join(os.path.dirname(srt_file), f"words_timing_{os.path.basename(srt_file).split('_')[2].split('.')[0]}.json")
            if os.path.exists(words_file):
                with open(words_file, 'r', encoding='utf-8') as f:
                    words_with_times = json.load(f)
                print(f"Loaded {len(words_with_times)} words with timing data")
            else:
                print(f"Word timing file not found: {words_file}")
        except Exception as e:
            print(f"Could not extract word-level timing: {e}")
            
        if words_with_times:
            # Group size - how many words in each fixed group
            group_size = 3  # Show 3 words at a time
            
            # Create fixed groups of words
            word_groups = []
            for i in range(0, len(words_with_times), group_size):
                group = []
                for j in range(group_size):
                    if i + j < len(words_with_times):
                        group.append(words_with_times[i + j])
                if group:
                    word_groups.append(group)
            
            # Process each word within each fixed group
            for group_idx, group in enumerate(word_groups):
                # For each word in the group, create a subtitle event
                for i, current_word in enumerate(group):
                    start_time = current_word['start_time']
                    end_time = current_word['end_time']
                    
                    # Convert times to ASS format
                    start_ass = format_timestamp_to_ass(start_time)
                    end_ass = format_timestamp_to_ass(end_time)
                    
                    # Build the text with highlighting tags
                    text_parts = []
                    for j, word_info in enumerate(group):
                        word = word_info['word'].upper()  # Convert to uppercase
                        
                        # Only highlight the current word being spoken
                        if j == i:
                            text_parts.append(f"{{\\c&H00FFFF&\\bord4}}{word}{{\\c&HFFFFFF&\\bord3}}")
                        else:
                            text_parts.append(word)
                    
                    text = " ".join(text_parts)
                    
                    # Calculate position (centered horizontally, with vertical offset)
                    x_pos = 540  # Center of 1080 width
                    y_pos = 1000  # Vertical position
                    
                    # Only add fade effects for the first and last word in each group
                    # This creates fade between groups but not for each word
                    animation = ""
                    if i == 0:  # First word in the group
                        # Only add fade-in if this is the first group or a new group
                        if group_idx > 0:
                            animation = "\\fad(80,0)"  # Fade in only
                    elif i == len(group) - 1:  # Last word in the group
                        # Only add fade-out if this is the last group or we're moving to a new group
                        if group_idx < len(word_groups) - 1:
                            animation = "\\fad(0,80)"  # Fade out only
                    
                    # Add subtle animations for the entire group
                    dialogue_line = (
                        f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,"
                        f"{{\\pos({x_pos},{y_pos})"
                        f"{animation}"
                        f"\\blur0.5"
                        f"\\bord3"
                        f"\\shad2"
                        f"}}{text}\n"
                    )
                    
                    ass_content += dialogue_line
        else:
            # Fallback to traditional subtitle display if word timing isn't available
            subs = pysrt.open(srt_file)
            
            # Helper to convert SRT time to an ASS time
            def srt_time_to_ass_time(srt_time):
                hours = srt_time.hours
                minutes = srt_time.minutes
                seconds = srt_time.seconds
                milliseconds = srt_time.milliseconds
                return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds//10:02d}"
            
            for sub in subs:
                start_time = srt_time_to_ass_time(sub.start)
                end_time = srt_time_to_ass_time(sub.end)

                # Convert the text to uppercase
                text = sub.text.upper()

                # Simple line-wrapping logic
                words = text.split()
                lines = []
                current_line = []
                current_length = 0
                
                # Reduced maximum characters per line from 30 to ~20
                for word in words:
                    if current_length + len(word) > 20:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                        current_length = len(word)
                    else:
                        current_line.append(word)
                        current_length += len(word) + 1
                if current_line:
                    lines.append(' '.join(current_line))
                wrapped_text = '\\N'.join(lines)

                # Enhanced animation with a bolder visual style:
                dialogue_line = (
                    f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,"
                    f"{{\\pos(540,1000)"
                    f"\\fad(100,100)"               # Fade in/out
                    f"\\blur0.5"                    # Mild blur
                    f"\\bord3"                      # Thicker border
                    f"\\shad2"                      # Stronger shadow
                    f"\\t(0,150,\\fscx110\\fscy110)" # Quick pop up to 110%
                    f"\\t(150,300,\\fscx100\\fscy100)}}"
                    f"{wrapped_text}\n"
                )

                ass_content += dialogue_line
        
        # Save ASS file to user directory
        with open(ass_file, "w", encoding="utf-8") as f:
            f.write(ass_content)
        
        print(f"Created ASS file at: {ass_file}")
        return ass_file

    except Exception as e:
        print(f"Error in create_subtitle_clips: {str(e)}")
        return None

def format_timestamp_to_ass(seconds):
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

def create_styled_subtitles(video_input, ass_file, user_dir, session_id):
    """Apply ASS subtitles using FFmpeg"""
    try:
        # Ensure paths are properly formatted and escaped
        video_input = os.path.normpath(video_input).replace('\\', '/')
        ass_file = os.path.normpath(ass_file).replace('\\', '/')
        output_filename = os.path.normpath(os.path.join(user_dir, f"final_video_with_subs_{session_id}.mp4")).replace('\\', '/')

        # Add debug logging
        print(f"Creating final video:")
        print(f"- Input video: {video_input}")
        print(f"- ASS file: {ass_file}")
        print(f"- Output path: {output_filename}")
        print(f"- User directory: {user_dir}")

        # Verify files exist
        if not os.path.exists(video_input):
            raise Exception(f"Input video not found: {video_input}")
        if not os.path.exists(ass_file):
            raise Exception(f"ASS subtitle file not found: {ass_file}")

        print(f"Video input path: {video_input}")
        print(f"ASS file path: {ass_file}")
        print(f"Output path: {output_filename}")

        # Create FFmpeg command with proper path escaping
        cmd = [
            'ffmpeg', '-y',
            '-i', video_input,
            '-vf', f"ass='{ass_file}'",  # Wrap the ass file path in quotes
            '-c:v', 'libx264',  # Explicitly specify video codec
            '-c:a', 'copy',     # Copy audio stream
            '-preset', 'fast',   # Use fast encoding preset
            output_filename
        ]

        # Join command for logging
        cmd_str = ' '.join(cmd)
        print(f"Executing FFmpeg command: {cmd_str}")

        # Execute FFmpeg command
        process = subprocess.Popen(
            cmd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            print("FFmpeg stdout:", stdout)
            print("FFmpeg stderr:", stderr)
            raise Exception(f"FFmpeg failed with error: {stderr}")

        # Verify output was created
        if not os.path.exists(output_filename):
            raise Exception("Output file was not created")

        print(f"Video with styled subtitles created as {output_filename}")
        return output_filename

    except Exception as e:
        print(f"Error in create_styled_subtitles: {str(e)}")
        # If something goes wrong, return the original video
        return video_input

def cleanup_user_files(user_dir, final_output):
    """Clean up temporary files for a user session with better error handling"""
    try:
        # Get session_id from the directory path
        session_id = os.path.basename(user_dir)
        
        for root, dirs, files in os.walk(user_dir, topdown=False):
            for name in files:
                file_path = os.path.join(root, name)
                # Only delete files that belong to this session and aren't the final output
                if (session_id in name and 
                    file_path != final_output and 
                    not "final_video_" in name):
                    try:
                        # Force Python to release any handles
                        import gc
                        gc.collect()
                        
                        os.remove(file_path)
                        print(f"Cleaned up: {file_path}")
                    except Exception as e:
                        print(f"Warning: Could not delete {file_path}: {str(e)}")
            
            # Try to remove empty directories
            for name in dirs:
                try:
                    dir_path = os.path.join(root, name)
                    if os.path.exists(dir_path) and not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        print(f"Removed empty directory: {dir_path}")
                except Exception as e:
                    print(f"Warning: Could not remove directory {dir_path}: {str(e)}")
    
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")

def delayed_cleanup(file_path, delay=5):
    """Attempt to delete a file after a delay with multiple retries."""
    def cleanup():
        # First delay to let initial processes finish
        time.sleep(delay)
        
        # Try up to 3 times with increasing delays
        for attempt in range(3):
            try:
                if os.path.exists(file_path):
                    # Don't delete if it's a final video
                    if "final_video_" in os.path.basename(file_path):
                        print(f"Skipping deletion of final video: {file_path}")
                        break
                        
                    # Force Python to release any handles it might have
                    import gc
                    gc.collect()
                    
                    os.remove(file_path)
                    print(f"File {file_path} cleaned up successfully on attempt {attempt + 1}")
                    
                    # Also try to remove the parent directory if it's empty
                    parent_dir = os.path.dirname(file_path)
                    try:
                        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                            os.rmdir(parent_dir)
                            print(f"Removed empty directory: {parent_dir}")
                    except Exception as e:
                        print(f"Warning: Could not remove directory {parent_dir}: {str(e)}")
                    break
                else:
                    print(f"File {file_path} already deleted")
                    break
            except Exception as e:
                print(f"Cleanup attempt {attempt + 1} failed for {file_path}: {e}")
                time.sleep(delay * (attempt + 1))  # Increase delay with each attempt

    threading.Thread(target=cleanup).start()

def cleanup_broll():
    """
    Manually called after user has finished downloading or viewing
    the final video. This tries to delete all uploaded b-roll files.
    """
    print("Attempting to clean up b-roll...")
    uploads_dir = "../brolls/user_uploads"
    
    # Define allowed file extensions
    allowed_extensions = ('.mp4', '.jpg', '.jpeg', '.png')
    
    for file in os.listdir(uploads_dir):
        if file.lower().endswith(allowed_extensions):
            file_path = os.path.join(uploads_dir, file)
            # Try multiple times with delays
            for attempt in range(3):
                try:
                    time.sleep(2)  # Wait for file handles to be released
                    os.remove(file_path)
                    print(f"Uploaded b-roll {file} cleaned up successfully")
                    break
                except Exception as e:
                    if attempt == 2:  # Only print error on last attempt
                        print(f"Warning: Could not delete uploaded b-roll {file}: {str(e)}")

def create_romanian_video(romanian_script, session_id, selected_music="funny 2.mp3", voice_id="gbLy9ep70G3JW53cTzFC", progress_callback=None, broll_files=None):
    """Modified to accept selected_music and voice_id parameters"""
    user_dir, uploads_dir = create_user_directory(session_id)
    
    # Generate a unique video ID
    video_id = str(uuid.uuid4())[:8]
    
    # Update all file paths to include session_id to ensure uniqueness
    audio_path = os.path.join(user_dir, f"audio_file_{session_id}.mp3")
    srt_path = os.path.join(user_dir, f"sub_file_{session_id}.srt")
    output_path = os.path.join(user_dir, f"final_clip_file_{session_id}.mp4")
    temp_audio_path = os.path.join(user_dir, f"TEMP_MPY_wvf_snd_{session_id}.mp3")
    final_output = os.path.join(user_dir, f"final_video_{session_id}_{video_id}.mp4")

    try:
        # Retrieve your ElevenLabs API key from an environment variable
        ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY is not set in environment variables.")
        
        # Use the voice_id parameter instead of hardcoded value
        VOICE_ID = voice_id
        SUBTITLE_GAP = 0
        
        # Initialize ElevenLabs client
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        if progress_callback:
            progress_callback("Generating audio file...|10")
        # Generate audio using ElevenLabs with voice parameters
        print("Generating audio file...")
        audio_stream = client.text_to_speech.convert_as_stream(
            text=romanian_script,
            voice_id=VOICE_ID,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.68,        # Range: 0-1. Higher value = more stable, lower = more variable
                "similarity_boost": 0.85, # Range: 0-1. Higher value = closer to original voice
                "style": 0.05,            # Range: 0-1. Higher value = more stylized
                "use_speaker_boost": True # Enhances clarity and target speaker similarity
            }
        )
        
        # Save the streaming audio
        with open(audio_path, "wb") as file:
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    file.write(chunk)

        # Retrieve your OpenAI API key from an environment variable
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in environment variables.")

        # Initialize OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        if progress_callback:
            progress_callback("Generating subtitles...|30")
        print("Generating subtitles...")
        
        # Get word-level timestamps from Google Cloud
        words_with_times = get_word_timestamps_from_google(audio_path)
        
        # Align the original script with the recognized words
        aligned_words = align_texts(romanian_script, words_with_times)
        
        # Create SRT file with aligned words
        srt_content = create_grouped_srt(aligned_words, max_words=4)
        
        # Save the processed SRT file
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
            
        # Save word timing data for word-by-word highlighting
        words_timing_path = os.path.join(user_dir, f"words_timing_{session_id}.json")
        with open(words_timing_path, "w", encoding="utf-8") as f:
            json.dump(aligned_words, f, indent=2)

        if progress_callback:
            progress_callback("Creating video...|50")
        print("Creating video...")
        audio_clip = AudioFileClip(audio_path)
        total_duration = audio_clip.duration

        # Use provided b-roll files or fall back to default behavior
        if not broll_files:
            broll_files = ["src/placeholder-broll.mp4"]

        print(f"\nUsing broll files in order: {broll_files}\n")

        # Process each file
        processed_clips = []
        for broll_path in broll_files:
            file_ext = broll_path.lower().split('.')[-1]
            
            if file_ext in ['jpg', 'jpeg', 'png']:
                # Process image files
                clip = create_clip_from_image(broll_path, duration=5)
            else:
                # Process video files (existing logic)
                clip = VideoFileClip(broll_path).without_audio()
                
                # Resize and crop to fit 9:16 aspect ratio
                clip_aspect = clip.w / clip.h
                target_aspect = 9 / 16

                if clip_aspect > target_aspect:
                    new_width = clip.h * (9 / 16)
                    zoom_factor = 1080 / new_width
                else:
                    new_height = clip.w * (16 / 9)
                    zoom_factor = 1920 / new_height

                clip = clip.resized(zoom_factor)

                x_center = clip.w / 2
                y_center = clip.h / 2
                clip = clip.cropped(
                    x1=x_center - 540,
                    y1=y_center - 960,
                    width=1080,
                    height=1920
                )
            
            processed_clips.append(clip)

        # Add a small buffer at the end of the video
        CLIP_DURATION = 5
        BUFFER_DURATION = 0.5  # seconds of buffer at the end
        
        # Calculate how many times we need to loop through clips
        # Add buffer to total duration
        total_duration_with_buffer = total_duration + BUFFER_DURATION
        total_clips_needed = math.ceil(total_duration_with_buffer / CLIP_DURATION)
        
        # Create final sequence of clips
        final_clips = []
        for i in range(total_clips_needed):
            clip_index = i % len(processed_clips)
            clip = processed_clips[clip_index]
            
            # Calculate start and end times for this segment
            start_time = i * CLIP_DURATION
            end_time = min((i + 1) * CLIP_DURATION, total_duration_with_buffer)
            segment_duration = end_time - start_time
            
            # If clip is shorter than needed duration, loop it
            if clip.duration < segment_duration:
                clip = clip.loop(duration=segment_duration)
            else:
                clip = clip.subclipped(0, segment_duration)
            
            final_clips.append(clip)

        # Concatenate all clips
        final_clip = concatenate_videoclips(final_clips)
        
        # Load the voice audio
        voice_audio = AudioFileClip(audio_path)
        
        # Load and prepare background music using selected music
        bg_music = AudioFileClip(f"music/{selected_music}")
        
        # Loop the background music if it's shorter than the voice audio
        if bg_music.duration < voice_audio.duration:
            num_loops = math.ceil(voice_audio.duration / bg_music.duration)
            bg_music = concatenate_audioclips([bg_music] * num_loops)
        
        # Trim background music to match voice duration (plus small buffer)
        bg_music = bg_music.with_duration(voice_audio.duration + BUFFER_DURATION)
        
        # Lower the volume of background music using MultiplyVolume
        bg_music = bg_music.with_effects([MultiplyVolume(0.15)])  # 15% of original volume
        
        # Combine voice and background music
        final_audio = CompositeAudioClip([voice_audio, bg_music])

        # Use combined audio instead of just voice audio
        final_clip = final_clip.with_audio(final_audio)

        # Create SSELogger instance with a proper callback
        def sse_callback(msg):
            if progress_callback:
                progress_callback(msg)
                
        sse_logger = SSELogger(sse_callback=sse_callback)
        
        if progress_callback:
            progress_callback("Rendering video (it may take a while)...|60")
        final_clip.write_videofile(
            output_path,
            fps=30,
            logger=sse_logger,
            temp_audiofile=temp_audio_path
        )

        # Ensure temp audio file is cleaned up
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception as e:
                print(f"Warning: Could not remove temp audio file: {str(e)}")

        # Update subtitle creation to use user directory
        if os.path.exists(srt_path):
            if progress_callback:
                progress_callback("Adding styled subtitles...|90")
            print("Adding styled subtitles...")
            ass_file = create_subtitle_clips(srt_path, (1080, 1920), user_dir)
            if ass_file and os.path.exists(ass_file):
                final_output = create_styled_subtitles(output_path, ass_file, user_dir, session_id)
                
                # Clean up temporary files only after successful creation
                if os.path.exists(final_output):
                    try:
                        os.remove(output_path)  # Remove the non-subtitled version
                        os.remove(ass_file)  # Remove the temporary subtitle file
                        os.remove(audio_path)  # Remove the temporary audio file
                        os.remove(srt_path)  # Remove the temporary subtitle file
                    except Exception as e:
                        print(f"Warning: Could not remove temporary files: {str(e)}")
            else:
                print("Failed to create subtitle file, using video without subtitles")
                final_output = output_path

        # Let the user see the "download" button
        if progress_callback:
            progress_callback("Video creation complete! |100")
        print("Video creation complete!")

        # Clean up the clip resources before returning
        if final_clip:
            final_clip.close()
        if voice_audio:
            voice_audio.close()
        if bg_music:
            bg_music.close()
        if final_audio:
            final_audio.close()

        # Optional small delay for Windows to release file handles
        time.sleep(1)

        return final_output  # Return the path to the final video instead of True
        
    except Exception as e:
        print(f"Error creating video: {str(e)}")
        if progress_callback:
            progress_callback(f"ERROR: {str(e)}")
        raise e

    finally:
        # Update cleanup to include new audio clips
        try:
            if 'final_clip' in locals() and final_clip:
                final_clip.close()
            if 'voice_audio' in locals() and voice_audio:
                voice_audio.close()
            if 'bg_music' in locals() and bg_music:
                bg_music.close()
            if 'final_audio' in locals() and final_audio:
                final_audio.close()
        except Exception as e:
            print(f"Warning: Error during cleanup: {str(e)}")
        
        # Force garbage collection
        import gc
        gc.collect()

if __name__ == "__main__":
    create_romanian_video()