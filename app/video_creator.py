import openai
import requests
import os
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, TextClip, CompositeVideoClip, ImageClip, VideoClip
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

# Set the path to your Google Cloud credentials JSON file
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dogwood-boulder-392113-d8917a17686f.json'

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

    # Convert MP3 to WAV (Google Speech requires WAV format)
    audio = AudioSegment.from_mp3(audio_file_path)
    wav_data = io.BytesIO()
    audio.export(wav_data, format="wav")
    wav_data.seek(0)

    # Read the audio file
    content = wav_data.read()

    audio = speech_v1.RecognitionAudio(content=content)
    config = speech_v1.RecognitionConfig(
        encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="ro-RO",  # Romanian language code
        enable_word_time_offsets=True,
    )

    response = client.recognize(config=config, audio=audio)
    
    words_with_times = []
    for result in response.results:
        for word in result.alternatives[0].words:
            # Convert the protobuf Duration objects to seconds
            start_time = word.start_time.total_seconds()
            end_time = word.end_time.total_seconds()
            
            words_with_times.append({
                'word': word.word,
                'start_time': start_time,
                'end_time': end_time
            })
    
    return words_with_times

def create_grouped_srt(words_with_times, max_words=4):
    """Create SRT content with grouped words"""
    srt_content = []
    current_index = 1
    current_group = []
    
    for word_info in words_with_times:
        current_group.append(word_info)
        
        # Create a new subtitle when we reach max words or find punctuation
        if (len(current_group) >= max_words or 
            any(p in word_info['word'] for p in '.!?,:')):
            
            start_time = current_group[0]['start_time']
            end_time = current_group[-1]['end_time']
            
            # Add small gap between subtitles if needed
            if srt_content:
                last_end_time = timestamp_to_seconds(srt_content[-1].split('\n')[1].split(' --> ')[1])
                if start_time < last_end_time:
                    start_time = last_end_time + 0.001
            
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
    
    while rec_idx < len(recognized_words) and orig_idx < len(original_words):
        rec_word = recognized_words[rec_idx]['word'].lower().strip('.,!?')
        orig_word = original_words[orig_idx].lower().strip('.,!?')
        
        # If words match exactly or are very similar
        if rec_word == orig_word or SequenceMatcher(None, rec_word, orig_word).ratio() > 0.8:
            aligned_words.append({
                'word': original_words[orig_idx],  # Use original word
                'start_time': recognized_words[rec_idx]['start_time'],
                'end_time': recognized_words[rec_idx]['end_time']
            })
            rec_idx += 1
            orig_idx += 1
        else:
            # If recognized word is likely wrong, use original word with estimated timing
            if rec_idx < len(recognized_words) - 1:
                # Estimate timing based on surrounding recognized words
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

def create_romanian_video(romanian_script, progress_callback=None):
    """
    Generates the final video with Romanian script, audio, 
    and subtitles. Returns True if successful.
    """
    parkour_video = None
    clips = []
    final_clip = None
    audio_clip = None
    
    try:
        # Retrieve your ElevenLabs API key from an environment variable
        ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY is not set in environment variables.")
        
        VOICE_ID = "SWN0Y4Js5I9UJiF9VqEP"
        SUBTITLE_GAP = 0
        
        # Initialize ElevenLabs client
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        if progress_callback:
            yield from progress_callback("Generating audio file...|10")
        # Generate audio using ElevenLabs
        print("Generating audio file...")
        audio_stream = client.text_to_speech.convert_as_stream(
            text=romanian_script,
            voice_id=VOICE_ID,
            model_id="eleven_multilingual_v2"
        )
        
        # Save the streaming audio
        with open("audio_file.mp3", "wb") as file:
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
            yield from progress_callback("Generating subtitles...|30")
        print("Generating subtitles...")
        
        # Get word-level timestamps from Google Cloud
        words_with_times = get_word_timestamps_from_google("audio_file.mp3")
        
        # Align the original script with the recognized words
        aligned_words = align_texts(romanian_script, words_with_times)
        
        # Create SRT file with aligned words
        srt_content = create_grouped_srt(aligned_words, max_words=4)
        
        # Save the processed SRT file
        with open("sub_file.srt", "w", encoding="utf-8") as f:
            f.write(srt_content)

        if progress_callback:
            yield from progress_callback("Creating video...|50")
        print("Creating video...")
        audio_clip = AudioFileClip("audio_file.mp3")
        total_duration = audio_clip.duration

        # Get all uploaded broll files (now including images)
        broll_files = []
        uploads_dir = "uploads"
        for file in os.listdir(uploads_dir):
            if file.startswith("uploaded_broll_") and file.lower().endswith(('.mp4', '.jpg', '.jpeg', '.png')):
                broll_files.append(os.path.join(uploads_dir, file))

        # If no uploaded files, use default
        if not broll_files:
            broll_files = ["src/placeholder-broll.mp4"]

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

        # Calculate how many times we need to loop through clips
        CLIP_DURATION = 5  # Duration for each clip in seconds
        total_clips_needed = math.ceil(total_duration / CLIP_DURATION)
        
        # Create final sequence of clips
        final_clips = []
        for i in range(total_clips_needed):
            clip_index = i % len(processed_clips)
            clip = processed_clips[clip_index]
            
            # Calculate start and end times for this segment
            start_time = i * CLIP_DURATION
            end_time = min((i + 1) * CLIP_DURATION, total_duration)
            segment_duration = end_time - start_time
            
            # If clip is shorter than needed duration, loop it
            if clip.duration < segment_duration:
                clip = clip.loop(duration=segment_duration)
            else:
                clip = clip.subclipped(0, segment_duration)
            
            final_clips.append(clip)

        # Concatenate all clips
        final_clip = concatenate_videoclips(final_clips)
        
        # Add audio
        final_clip = final_clip.with_audio(audio_clip)

        # Create SSELogger instance with a proper callback
        def sse_callback(msg):
            if progress_callback:
                yield from progress_callback(msg)
                
        sse_logger = SSELogger(sse_callback=sse_callback)
        
        output_filename = "final_clip_file.mp4"
        yield from progress_callback("Rendering video (it may take a while)...|60")
        final_clip.write_videofile(
            output_filename,
            fps=30,
            logger='bar'
        )

        # Then add subtitles if they exist
        if os.path.exists("sub_file.srt"):
            if progress_callback:
                yield from progress_callback("Adding styled subtitles...|90")
            print("Adding styled subtitles...")
            ass_file = create_subtitle_clips("sub_file.srt", (1080, 1920))
            final_output = create_styled_subtitles(output_filename, ass_file)
            
            # Clean up temporary files only after successful creation
            if os.path.exists(final_output):
                os.remove(output_filename)  # Remove the non-subtitled version
                os.remove(ass_file)  # Remove the temporary subtitle file
                os.remove("audio_file.mp3")  # Remove the temporary audio file
                os.remove("sub_file.srt")  # Remove the temporary subtitle file

        # Let the user see the "download" button
        # we pass 100% progress so the user knows we are finished
        if progress_callback:
            yield from progress_callback("Video creation complete! |100")
        print("Video creation complete!")

        # Clean up the clip resources before returning
        if parkour_video:
            parkour_video.close()
        for clip in clips:
            try:
                clip.close()
            except:
                pass
        if final_clip:
            final_clip.close()
        if audio_clip:
            audio_clip.close()

        # Optional small delay for Windows to release file handles
        time.sleep(1)

        return True
        
    except Exception as e:
        print(f"Error creating video: {str(e)}")
        raise e

    finally:
        # Ensure all resources are closed in the finally block
        try:
            if parkour_video:
                parkour_video.close()
        except:
            pass
        for clip in clips:
            try:
                clip.close()
            except:
                pass
        try:
            if final_clip:
                final_clip.close()
        except:
            pass
        try:
            if audio_clip:
                audio_clip.close()
        except:
            pass
        
        # Force garbage collection to release file handles
        import gc
        gc.collect()

def create_subtitle_clips(srt_file, videosize):
    """Convert SRT to ASS and create styled subtitles"""
    ass_content = """[Script Info]
Title: Romanian Video Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default, Arial, 72, &H00FFFFFF, &H000000FF, &H00000000, &H80000000, 1, 0, 0, 0, 100, 100, 0, 0, 1, 2, 4, 2, 150, 150, 30, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    subs = pysrt.open(srt_file)
    
    def srt_time_to_ass_time(td):
        """Convert SubRipTime to ASS time format"""
        total_milliseconds = (td.hours * 3600000 + 
                            td.minutes * 60000 + 
                            td.seconds * 1000 + 
                            td.milliseconds)
        
        hours = int(total_milliseconds // 3600000)
        minutes = int((total_milliseconds % 3600000) // 60000)
        seconds = int((total_milliseconds % 60000) // 1000)
        centiseconds = int((total_milliseconds % 1000) // 10)  # Convert to centiseconds for ASS
        
        return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
    
    for sub in subs:
        start_time = srt_time_to_ass_time(sub.start)
        end_time = srt_time_to_ass_time(sub.end)
        text = sub.text.replace('\n', '\\N')  # ASS line breaks
        
        ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{{\\fad(200,200)\\pos(540,1200)\\q1\\w8}}{text}\n"
    
    # Save ASS file
    ass_file = "subtitles.ass"
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_content)
    
    return ass_file

def create_styled_subtitles(video_input, ass_file):
    """Apply ASS subtitles using FFmpeg"""
    output_filename = "final_video_with_subs.mp4"
    # Added -strict -2 flag for better compatibility and -max_interleave_delta 0 for precise timing
    os.system(f'ffmpeg -y -i {video_input} -vf "ass={ass_file}" -max_interleave_delta 0 -strict -2 -c:a copy {output_filename}')
    print(f"Video with styled subtitles created as {output_filename}")
    return output_filename

def cleanup_broll():
    """
    Manually called after user has finished downloading or viewing
    the final video. This tries to delete all uploaded b-roll files.
    """
    print("Attempting to clean up b-roll...")
    uploads_dir = "uploads"
    
    # Define allowed file extensions
    allowed_extensions = ('.mp4', '.jpg', '.jpeg', '.png')
    
    for file in os.listdir(uploads_dir):
        if file.startswith("uploaded_broll_") and file.lower().endswith(allowed_extensions):
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

if __name__ == "__main__":
    create_romanian_video()