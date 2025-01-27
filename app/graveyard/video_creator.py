## This is the old video creator. It is not used anymore.
## It is kept here for reference.
## It is not used in the current version of the app.
## In this (still working) version, we use the Whisper API to generate subtitles
## The main issue with whisper was that it was not able to generate subtitles word-for-word
## So we used Google Cloud Speech-to-Text to generate the subtitles
import openai
import requests
import os
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, TextClip, CompositeVideoClip
import math
import pysrt
import time
from pathlib import Path
import random
from elevenlabs import ElevenLabs
from proglog import ProgressBarLogger
from openai import OpenAI

def format_timestamp(seconds):
    """Convert seconds to SRT timestamp format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def timestamp_to_seconds(timestamp):
    """Convert SRT timestamp to seconds"""
    # Remove milliseconds
    time_parts, milliseconds = timestamp.split(',')
    hours, minutes, seconds = map(int, time_parts.split(':'))
    total_seconds = hours * 3600 + minutes * 60 + seconds + int(milliseconds) / 1000
    return total_seconds

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
        SUBTITLE_GAP = 0.001
        
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
        # Generate SRT file using Whisper for timing
        print("Generating subtitles...")
        with open("audio_file.mp3", "rb") as audio_file:
            try:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="srt"
                )
                # The transcript is already a string, no need to access .text
            except Exception as e:
                print(f"OpenAI API Error: {str(e)}")
                raise
        
        # Parse the SRT content to get timing
        srt_lines = transcript.split('\n')
        last_timestamp = None
        for line in reversed(srt_lines):
            if ' --> ' in line:
                last_timestamp = line.split(' --> ')[1].strip()
                break
        
        total_duration = timestamp_to_seconds(last_timestamp)
        
        # Clean and split original script into words, removing empty strings and extra spaces
        original_words = [word.strip() for word in romanian_script.split() if word.strip()]
        
        # Process the words to create SRT segments
        srt_content = []
        current_index = 1
        
        # Split the original script into natural phrases using punctuation
        phrases = []
        current_phrase = []
        for word in original_words:
            current_phrase.append(word)
            if any(p in word for p in '.!?,:'):
                phrases.append(current_phrase)
                current_phrase = []
        if current_phrase:  # Add any remaining words
            phrases.append(current_phrase)
        
        # Calculate timing for each phrase
        words_per_second = len(original_words) / total_duration
        
        for i, phrase in enumerate(phrases):
            # Calculate approximate start and end times based on word position
            phrase_start_idx = sum(len(p) for p in phrases[:i])
            phrase_end_idx = phrase_start_idx + len(phrase)
            
            start_time = (phrase_start_idx / len(original_words)) * total_duration
            end_time = (phrase_end_idx / len(original_words)) * total_duration
            
            # Add gap between subtitles
            if srt_content:
                prev_timestamp = srt_content[-1].split('\n')[1].split(' --> ')[1]
                prev_end = timestamp_to_seconds(prev_timestamp)
                if start_time < prev_end + SUBTITLE_GAP:
                    start_time = prev_end + SUBTITLE_GAP
            
            srt_entry = f"{current_index}\n"
            srt_entry += f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n"
            srt_entry += f"{' '.join(phrase)}\n\n"
            srt_content.append(srt_entry)
            current_index += 1

        # Save the processed SRT file
        with open("sub_file.srt", "w", encoding="utf-8") as f:
            f.write(''.join(srt_content))

        if progress_callback:
            yield from progress_callback("Creating video...|50")
        print("Creating video...")
        audio_clip = AudioFileClip("audio_file.mp3")
        total_duration = audio_clip.duration

        # Get all uploaded broll files
        broll_files = []
        uploads_dir = "uploads"
        for file in os.listdir(uploads_dir):
            if file.startswith("uploaded_broll_") and file.endswith(".mp4"):
                broll_files.append(os.path.join(uploads_dir, file))

        # If no uploaded files, use default
        if not broll_files:
            broll_files = ["src/placeholder-broll.mp4"]

        # Process each broll file
        processed_clips = []
        for broll_path in broll_files:
            video = VideoFileClip(broll_path).without_audio()
            
            # Resize and crop to fit 9:16 aspect ratio
            clip_aspect = video.w / video.h
            target_aspect = 9 / 16

            if clip_aspect > target_aspect:
                new_width = video.h * (9 / 16)
                zoom_factor = 1080 / new_width
            else:
                new_height = video.w * (16 / 9)
                zoom_factor = 1920 / new_height

            video = video.resized(zoom_factor)

            x_center = video.w / 2
            y_center = video.h / 2
            video = video.cropped(
                x1=x_center - 540,
                y1=y_center - 960,
                width=1080,
                height=1920
            )
            processed_clips.append(video)

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
        total_seconds = (td.hours * 3600 + td.minutes * 60 + 
                        td.seconds + td.milliseconds / 1000.0)
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        centiseconds = int((total_seconds * 100) % 100)  # ASS uses centiseconds
        return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
    
    for sub in subs:
        start_time = srt_time_to_ass_time(sub.start)
        end_time = srt_time_to_ass_time(sub.end)
        text = sub.text.replace('\n', '\\N')  # ASS line breaks
        
        # Added \q1 for alternative wrapping mode and increased margins
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
    
    for file in os.listdir(uploads_dir):
        if file.startswith("uploaded_broll_") and file.endswith(".mp4"):
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