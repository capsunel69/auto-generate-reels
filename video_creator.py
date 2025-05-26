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
import re

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
        self.last_progress = 0

    def callback(self, **changes):
        # This call ensures MoviePy's built-in progress bar is displayed
        super().callback(**changes)

        if not self.sse_callback:
            return

        # Get the message from changes
        message = changes.get('message', '')
        
        # Handle different types of progress updates
        if 'frame' in changes and 'total' in changes:
            current = changes['frame']
            total = changes['total']
            if total > 0:
                progress = (current / total) * 100
                # Only send update if progress has changed significantly (more than 1%)
                if progress - self.last_progress >= 1:
                    self.last_progress = progress
                    self.sse_callback(f"Rendering video - Processing frames ({progress:.0f}%)|{progress}")
        elif message:
            # Map different messages to appropriate progress stages
            if 'Building video' in message:
                self.sse_callback("Rendering video - Preparing...|80")
            elif 'Writing audio' in message:
                self.sse_callback("Rendering video - Processing audio...|82")
            elif 'Writing video' in message:
                self.sse_callback("Rendering video - Processing frames...|85")
            elif 'Done' in message:
                self.sse_callback("Rendering video - Finalizing...|90")
            else:
                # For other messages, just pass them through
                self.sse_callback(message)

def get_word_timestamps_from_google(audio_file_path, language="romanian"):
    """Get word-level timestamps using Google Cloud Speech-to-Text with language support"""
    client = speech_v1.SpeechClient()

    # Map language codes to Google Cloud Speech language codes
    language_map = {
        "romanian": "ro-RO",
        "english": "en-US"
    }
    
    language_code = language_map.get(language.lower(), "ro-RO")
    print(f"Using speech recognition language: {language_code}")

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

            # Process chunk with language-specific configuration
            audio_input = speech_v1.RecognitionAudio(content=content)
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                language_code=language_code,
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,  # Better punctuation detection
                use_enhanced=True,  # Use enhanced model for better accuracy
                model="latest_long"  # Use latest model optimized for longer audio
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
                        'end_time': end_time,
                        'confidence': result.alternatives[0].confidence if hasattr(result.alternatives[0], 'confidence') else 1.0
                    })
    else:
        # For short audio, process as before but with improved config
        wav_data = io.BytesIO()
        audio.export(wav_data, format="wav")
        wav_data.seek(0)
        content = wav_data.read()

        audio_input = speech_v1.RecognitionAudio(content=content)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code=language_code,
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
            use_enhanced=True,
            model="latest_short"  # Use model optimized for shorter audio
        )

        response = client.recognize(config=config, audio=audio_input)
        
        for result in response.results:
            for word in result.alternatives[0].words:
                words_with_times.append({
                    'word': word.word,
                    'start_time': word.start_time.total_seconds(),
                    'end_time': word.end_time.total_seconds(),
                    'confidence': result.alternatives[0].confidence if hasattr(result.alternatives[0], 'confidence') else 1.0
                })
    
    print(f"Extracted {len(words_with_times)} words with timestamps")
    
    # Post-process to merge split contractions
    words_with_times = merge_split_contractions(words_with_times)
    
    return words_with_times

def merge_split_contractions(words_with_times):
    """
    Merge split contractions like "you" + "re" → "you're"
    This fixes issues where speech recognition splits contractions incorrectly
    """
    if not words_with_times:
        return words_with_times
    
    # Common contraction patterns to merge
    contraction_patterns = [
        # Pattern: (first_word, second_word, merged_word)
        ('you', 're', "you're"),
        ('don', 't', "don't"),
        ('can', 't', "can't"),
        ('won', 't', "won't"),
        ('it', 's', "it's"),
        ('that', 's', "that's"),
        ('he', 's', "he's"),
        ('she', 's', "she's"),
        ('we', 're', "we're"),
        ('they', 're', "they're"),
        ('i', 'm', "I'm"),
        ('i', 'll', "I'll"),
        ('you', 'll', "you'll"),
        ('he', 'll', "he'll"),
        ('she', 'll', "she'll"),
        ('we', 'll', "we'll"),
        ('they', 'll', "they'll"),
        ('i', 've', "I've"),
        ('you', 've', "you've"),
        ('we', 've', "we've"),
        ('they', 've', "they've"),
        ('i', 'd', "I'd"),
        ('you', 'd', "you'd"),
        ('he', 'd', "he'd"),
        ('she', 'd', "she'd"),
        ('we', 'd', "we'd"),
        ('they', 'd', "they'd"),
        ('is', 'n\'t', "isn't"),
        ('are', 'n\'t', "aren't"),
        ('was', 'n\'t', "wasn't"),
        ('were', 'n\'t', "weren't"),
        ('have', 'n\'t', "haven't"),
        ('has', 'n\'t', "hasn't"),
        ('had', 'n\'t', "hadn't"),
        ('will', 'not', "won't"),
        ('would', 'not', "wouldn't"),
        ('could', 'not', "couldn't"),
        ('should', 'not', "shouldn't"),
        ('must', 'not', "mustn't"),
    ]
    
    merged_words = []
    i = 0
    
    while i < len(words_with_times):
        current_word = words_with_times[i]
        
        # Check if this word can be merged with the next one
        merged = False
        if i < len(words_with_times) - 1:
            next_word = words_with_times[i + 1]
            
            # Normalize words for comparison (lowercase, remove punctuation)
            current_normalized = current_word['word'].lower().strip('.,!?;:"()[]{}')
            next_normalized = next_word['word'].lower().strip('.,!?;:"()[]{}')
            
            # Check against contraction patterns
            for first, second, merged_form in contraction_patterns:
                if current_normalized == first and next_normalized == second:
                    # Calculate timing gap between words
                    gap = next_word['start_time'] - current_word['end_time']
                    
                    # Only merge if the gap is small (less than 200ms)
                    if gap < 0.2:
                        # Create merged word
                        merged_word = {
                            'word': merged_form,
                            'start_time': current_word['start_time'],
                            'end_time': next_word['end_time'],
                            'confidence': min(current_word.get('confidence', 1.0), 
                                            next_word.get('confidence', 1.0))
                        }
                        merged_words.append(merged_word)
                        merged = True
                        i += 2  # Skip both words
                        print(f"Merged contraction: '{current_word['word']}' + '{next_word['word']}' → '{merged_form}'")
                        break
        
        if not merged:
            # No merge, add current word as-is
            merged_words.append(current_word)
            i += 1
    
    print(f"Contraction merging: {len(words_with_times)} → {len(merged_words)} words")
    return merged_words

def create_grouped_srt(words_with_times, max_words=4):
    """Create SRT content with grouped words and improved timing"""
    srt_content = []
    current_index = 1
    current_group = []
    
    MIN_DURATION = 0.7  # Minimum duration for each subtitle in seconds
    GAP_DURATION = 0.1  # Gap between subtitles in seconds
    
    # Find natural break points (spaces between words with longer pauses)
    natural_breaks = []
    for i in range(1, len(words_with_times)):
        prev_word = words_with_times[i-1]
        curr_word = words_with_times[i]
        
        # If the gap between words is notably larger than average, it's a natural break
        if curr_word['start_time'] - prev_word['end_time'] > 0.3:
            natural_breaks.append(i)
    
    for i, word_info in enumerate(words_with_times):
        current_group.append(word_info)
        
        # Create a new subtitle at natural breaks, max words, or punctuation
        at_natural_break = i in natural_breaks
        at_max_words = len(current_group) >= max_words
        contains_punctuation = any(p in word_info['word'] for p in '.!?,;:')
        
        if at_max_words or contains_punctuation or at_natural_break:
            # Only break if we have at least 1 word in the group
            if len(current_group) >= 1:
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
                
                # Create SRT entry
                srt_entry = f"{current_index}\n"
                srt_entry += f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n"
                srt_entry += f"{' '.join(w['word'] for w in current_group)}\n\n"
                
                srt_content.append(srt_entry)
                current_index += 1
                current_group = []
    
    # Add any remaining words in the last group
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
    Improved text alignment using confidence scores and better fuzzy matching
    while preserving the timestamps from recognized words.
    """
    from difflib import SequenceMatcher
    import re
    
    # Split original script into words and normalize
    original_words = original_script.split()
    aligned_words = []
    
    # Normalize function for better matching
    def normalize_word(word):
        """Normalize word for comparison - remove punctuation, convert to lowercase"""
        return re.sub(r'[^\w\'-]', '', word.lower())
    
    # Pre-process both sequences
    normalized_original = [normalize_word(word) for word in original_words]
    normalized_recognized = [normalize_word(word['word']) for word in recognized_words]
    
    # Calculate average word duration and confidence
    total_duration = 0
    total_confidence = 0
    valid_words = 0
    
    for word in recognized_words:
        if 'start_time' in word and 'end_time' in word:
            duration = word['end_time'] - word['start_time']
            if 0.05 < duration < 2.0:  # Filter reasonable durations
                total_duration += duration
                total_confidence += word.get('confidence', 1.0)
                valid_words += 1
    
    avg_word_duration = total_duration / valid_words if valid_words > 0 else 0.25
    avg_confidence = total_confidence / valid_words if valid_words > 0 else 1.0
    
    print(f"Average word duration: {avg_word_duration:.3f}s, Average confidence: {avg_confidence:.3f}")
    
    # Use sequence matching for better alignment
    matcher = SequenceMatcher(None, normalized_original, normalized_recognized)
    matching_blocks = matcher.get_matching_blocks()
    
    orig_idx = 0
    rec_idx = 0
    last_end_time = 0
    
    for match in matching_blocks:
        orig_start, rec_start, size = match.a, match.b, match.size
        
        # Handle unmatched original words before this match
        while orig_idx < orig_start:
            # Estimate timing for unmatched original words
            if rec_idx < len(recognized_words):
                # Use timing from next recognized word
                base_time = recognized_words[rec_idx]['start_time']
                estimated_start = max(last_end_time, base_time - avg_word_duration)
            else:
                # Use last known time + estimated duration
                estimated_start = last_end_time + 0.05
            
            estimated_end = estimated_start + avg_word_duration
            
            aligned_words.append({
                'word': original_words[orig_idx],
                'start_time': estimated_start,
                'end_time': estimated_end,
                'confidence': avg_confidence * 0.5,  # Lower confidence for estimated words
                'estimated': True
            })
            
            last_end_time = estimated_end
            orig_idx += 1
        
        # Handle unmatched recognized words before this match
        while rec_idx < rec_start:
            rec_idx += 1
        
        # Handle the matching block
        for i in range(size):
            if orig_idx + i < len(original_words) and rec_idx + i < len(recognized_words):
                rec_word = recognized_words[rec_idx + i]
                aligned_words.append({
                    'word': original_words[orig_idx + i],
                    'start_time': rec_word['start_time'],
                    'end_time': rec_word['end_time'],
                    'confidence': rec_word.get('confidence', 1.0),
                    'estimated': False
                })
                last_end_time = rec_word['end_time']
        
        orig_idx = orig_start + size
        rec_idx = rec_start + size
    
    # Handle any remaining original words
    while orig_idx < len(original_words):
        estimated_start = last_end_time + 0.05
        estimated_end = estimated_start + avg_word_duration
        
        aligned_words.append({
            'word': original_words[orig_idx],
            'start_time': estimated_start,
            'end_time': estimated_end,
            'confidence': avg_confidence * 0.5,
            'estimated': True
        })
        
        last_end_time = estimated_end
        orig_idx += 1
    
    # Post-process to smooth timing and fix overlaps
    for i in range(1, len(aligned_words)):
        prev_word = aligned_words[i-1]
        curr_word = aligned_words[i]
        
        # Fix overlaps
        if curr_word['start_time'] < prev_word['end_time']:
            # Adjust current word start time
            gap = 0.02  # 20ms minimum gap
            aligned_words[i]['start_time'] = prev_word['end_time'] + gap
            
            # Ensure minimum duration
            min_duration = 0.1
            if aligned_words[i]['end_time'] - aligned_words[i]['start_time'] < min_duration:
                aligned_words[i]['end_time'] = aligned_words[i]['start_time'] + min_duration
    
    print(f"Aligned {len(aligned_words)} words ({sum(1 for w in aligned_words if not w.get('estimated', False))} matched, {sum(1 for w in aligned_words if w.get('estimated', False))} estimated)")
    
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

def format_timestamp_to_ass(seconds):
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

def create_subtitle_clips(srt_file, videosize, user_dir):
    """
    Convert SRT to ASS with improved TikTok-style subtitles:
    - No word highlighting - just clean subtitle display
    - Better punctuation handling - keep apostrophes, remove other punctuation
    - Improved synchronization for both Romanian and English
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
Title: Video Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; Default style - clean white text without highlighting
Style: Default,{font_name},64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4,0,2,400,400,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Function to clean word for display while preserving apostrophes and hyphens
        def clean_word_for_display(word):
            """
            Clean a word for subtitle display:
            - Preserve apostrophes (') and hyphens (-) within words
            - Remove other punctuation like ,.!?;:()[]{}
            - Convert to uppercase
            """
            import re
            
            # Convert to uppercase
            word = word.upper()
            
            # Remove quotes (but NOT apostrophes) - be more specific
            # Remove Romanian quotes and regular quotes, but preserve apostrophes
            word = re.sub(r'[„"""]', '', word)  # Removed \' from this regex
            
            # Remove specific punctuation from start/end of word, but keep apostrophes and hyphens
            word = word.strip(',.;:!?()[]{}')
            
            # Keep only letters, numbers, apostrophes, and hyphens
            # This preserves Romanian diacritics, apostrophes, and hyphens within words
            allowed_chars = r'\w\'\-șțăîâŞŢĂÎÂ'
            word = re.sub(f'[^{allowed_chars}]', '', word)
            
            return word.strip()

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
            # Minimal timing buffer for precise synchronization
            TIMING_BUFFER = 0.02  # Reduced to 20ms for better precision
            
            # Adaptive grouping based on confidence and natural breaks
            def create_adaptive_groups(words):
                """Create word groups adaptively based on confidence, timing, and natural breaks"""
                groups = []
                current_group = []
                
                for i, word in enumerate(words):
                    confidence = word.get('confidence', 1.0)
                    is_estimated = word.get('estimated', False)
                    
                    # Check for natural break points
                    is_end_of_sentence = any(p in word['word'] for p in '.!?')
                    is_comma_pause = ',' in word['word']
                    
                    # Detect pauses between words - more strict detection
                    is_natural_pause = False
                    pause_duration = 0
                    if i < len(words) - 1:
                        next_word = words[i + 1]
                        pause_duration = next_word['start_time'] - word['end_time']
                        # More strict pause detection - only break on significant pauses
                        is_natural_pause = pause_duration > 0.4  # Increased to 400ms for stricter detection
                    
                    # Determine group size based on confidence and word characteristics
                    max_group_size = 3 if confidence > 0.8 and not is_estimated else 2  # Smaller groups for better timing
                    
                    current_group.append(word)
                    
                    # Create new group based on various criteria - more conservative
                    should_break = (
                        len(current_group) >= max_group_size or
                        is_end_of_sentence or
                        is_natural_pause or
                        (is_comma_pause and len(current_group) >= 2) or
                        (is_estimated and len(current_group) >= 1)  # Break immediately for estimated words
                    )
                    
                    if should_break and current_group:
                        groups.append(current_group)
                        current_group = []
                
                # Add any remaining words
                if current_group:
                    groups.append(current_group)
                
                return groups
            
            word_groups = create_adaptive_groups(words_with_times)
            
            # Minimal transition gap for precise timing
            GROUP_TRANSITION_GAP = 0.05  # Reduced to 50ms for better precision
            
            # Calculate and adjust group timings with improved precision
            group_timings = []
            for group in word_groups:
                # Use actual word timing without buffer for start time
                group_start = group[0]['start_time']  # No buffer for more precise timing
                group_end = group[-1]['end_time']
                
                # Calculate actual spoken duration
                actual_duration = group_end - group_start
                
                # Adaptive minimum duration based on group size and confidence
                avg_confidence = sum(w.get('confidence', 1.0) for w in group) / len(group)
                
                # More conservative minimum duration - only extend if really necessary
                min_duration = max(0.3, actual_duration * 0.8)  # At least 80% of actual duration or 300ms
                
                if group_end - group_start < min_duration:
                    group_end = group_start + min_duration
                
                group_timings.append({
                    'start': group_start,
                    'end': group_end,
                    'confidence': avg_confidence,
                    'actual_duration': actual_duration
                })
            
            # Improved timing adjustments to prevent overlaps while preserving natural pauses
            for i in range(1, len(group_timings)):
                prev_timing = group_timings[i-1]
                curr_timing = group_timings[i]
                
                # Calculate the natural pause between groups
                natural_pause = curr_timing['start'] - prev_timing['end']
                
                # Only adjust if there's actually an overlap or very small gap
                if natural_pause < GROUP_TRANSITION_GAP:
                    # Adjust start time to create minimal gap
                    group_timings[i]['start'] = prev_timing['end'] + GROUP_TRANSITION_GAP
                    
                    # Only extend end time if the actual duration would be too short
                    new_duration = group_timings[i]['end'] - group_timings[i]['start']
                    min_required = max(0.3, curr_timing['actual_duration'] * 0.8)
                    
                    if new_duration < min_required:
                        group_timings[i]['end'] = group_timings[i]['start'] + min_required
            
            # Process each word group - NO HIGHLIGHTING, just clean subtitles
            for group_idx, group in enumerate(word_groups):
                group_start = group_timings[group_idx]['start']
                group_end = group_timings[group_idx]['end']
                group_confidence = group_timings[group_idx]['confidence']
                
                # Build the text for the entire group
                text_parts = []
                for word_info in group:
                    word = clean_word_for_display(word_info['word'])
                    text_parts.append(word)
                
                text = " ".join(text_parts)
                
                # Position and styling
                x_pos = 540  # Center of 1080 width
                y_pos = 1000  # Vertical position
                
                # Adaptive fade effects based on confidence
                fade_in = 40 if group_confidence > 0.8 else 60
                fade_out = 50 if group_confidence > 0.8 else 80
                
                # Convert times to ASS format
                start_ass = format_timestamp_to_ass(group_start)
                end_ass = format_timestamp_to_ass(group_end)
                
                # Clean subtitle without any highlighting effects
                dialogue_line = (
                    f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,"
                    f"{{\\pos({x_pos},{y_pos})"
                    f"\\fad({fade_in},{fade_out})"
                    f"\\blur0.3"
                    f"\\bord3"
                    f"\\shad1.5"
                    f"}}{text}\n"
                )
                
                ass_content += dialogue_line
                
                # NO HIGHLIGHTING CODE - removed all word-by-word highlighting
                
        else:
            # Fallback to traditional subtitle display with improved timing
            subs = pysrt.open(srt_file)
            
            # Minimal timing buffer for precise sync
            SUB_TIMING_BUFFER = 0.02  # Reduced to 20ms for better precision
            
            # Improved overlap prevention with better timing logic
            for i in range(1, len(subs)):
                prev_sub = subs[i-1]
                curr_sub = subs[i]
                
                prev_end = prev_sub.end.to_time().total_seconds()
                curr_start = curr_sub.start.to_time().total_seconds()
                
                # Calculate natural pause between subtitles
                natural_pause = curr_start - prev_end
                
                # Only adjust if there's an overlap or very small gap
                min_gap = 0.05  # Reduced to 50ms for better precision
                if natural_pause < min_gap:
                    new_start = prev_end + min_gap
                    curr_sub.start.from_seconds(new_start)
                    
                    curr_end = curr_sub.end.to_time().total_seconds()
                    # More conservative minimum duration
                    min_duration = 0.3
                    if curr_end - new_start < min_duration:
                        curr_sub.end.from_seconds(new_start + min_duration)
            
            for sub in subs:
                # Use precise timing without aggressive buffering
                start_time_seconds = sub.start.to_time().total_seconds()
                start_time_seconds = max(0, start_time_seconds)  # Don't go negative
                end_time_seconds = sub.end.to_time().total_seconds()
                
                start_time = format_timestamp_to_ass(start_time_seconds)
                end_time = format_timestamp_to_ass(end_time_seconds)

                # Process text with improved word cleaning
                words = sub.text.split()
                cleaned_words = [clean_word_for_display(word) for word in words]
                text = " ".join(cleaned_words)

                # Improved line wrapping
                words = text.split()
                lines = []
                current_line = []
                current_length = 0
                
                for word in words:
                    if current_length + len(word) > 18:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                        current_length = len(word)
                    else:
                        current_line.append(word)
                        current_length += len(word) + 1
                if current_line:
                    lines.append(' '.join(current_line))
                wrapped_text = '\\N'.join(lines)

                # Clean styling without highlighting
                dialogue_line = (
                    f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,"
                    f"{{\\pos(540,1000)"
                    f"\\fad(60,60)"
                    f"\\blur0.3"
                    f"\\bord3"
                    f"\\shad1.5"
                    f"\\t(0,100,\\fscx103\\fscy103)"  # Subtle scale animation
                    f"\\t(100,200,\\fscx100\\fscy100)}}"
                    f"{wrapped_text}\n"
                )

                ass_content += dialogue_line
        
        # Save ASS file
        with open(ass_file, "w", encoding="utf-8") as f:
            f.write(ass_content)
        
        print(f"Created clean ASS file (no highlighting) at: {ass_file}")
        return ass_file

    except Exception as e:
        print(f"Error in create_subtitle_clips: {str(e)}")
        return None

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

def clean_script_for_tts(script):
    """
    Clean script text for TTS processing:
    - Remove parentheses and their contents
    - Remove brackets and their contents
    - Remove standalone punctuation (commas, periods, quotes)
    - Preserve hyphens, apostrophes within words (like "printr-un")
    - Normalize spacing
    - Remove emojis and special characters
    """
    import re
    
    # Store original length for comparison
    original_length = len(script)
    
    # Remove content within parentheses and the parentheses themselves
    script = re.sub(r'\([^)]*\)', ' ', script)
    
    # Remove content within brackets and the brackets themselves
    script = re.sub(r'\[[^\]]*\]', ' ', script)
    
    # Remove content within curly braces and the braces themselves
    script = re.sub(r'\{[^}]*\}', ' ', script)
    
    # First, remove quotes (including Romanian-style quotes)
    script = re.sub(r'[„""\'"]', ' ', script)
    
    # Process word by word to preserve hyphens and apostrophes within words
    words = script.split()
    cleaned_words = []
    
    for word in words:
        # Remove most punctuation from the start/end of words
        word = word.strip(',.;:!?()[]{}""\'„"')
        
        # Skip if word is empty after cleaning
        if not word:
            continue
            
        # Keep the word if it still has content
        cleaned_words.append(word)
    
    # Rejoin with spaces
    script = ' '.join(cleaned_words)
    
    # Replace ellipses and other problematic symbols with spaces
    script = re.sub(r'[…]', ' ', script)
    
    # Remove any non-alphanumeric characters except for allowed punctuation within words
    allowed_chars = r'\w\s\'\-șțăîâŞŢĂÎÂ'
    script = re.sub(f'[^{allowed_chars}]', ' ', script)
    
    # Remove excessive whitespace and normalize to single spaces
    script = re.sub(r'\s+', ' ', script).strip()
    
    # Calculate how much was removed
    cleaned_length = len(script)
    chars_removed = original_length - cleaned_length
    
    return {
        'text': script,
        'original_length': original_length,
        'cleaned_length': cleaned_length,
        'chars_removed': chars_removed,
        'percent_removed': round((chars_removed / original_length * 100), 2) if original_length > 0 else 0
    }

def create_video(script, session_id, language="romanian", selected_music="funny 2.mp3", voice_id="gbLy9ep70G3JW53cTzFC", progress_callback=None, broll_files=None):
    """Create a video with the given script and selected resources. Supports multiple languages."""
    try:
        user_dir, uploads_dir = create_user_directory(session_id)
        
        # Generate a unique video ID
        video_id = str(uuid.uuid4())[:8]
        
        # Update all file paths to include session_id to ensure uniqueness
        audio_path = os.path.join(user_dir, f"audio_file_{session_id}.mp3")
        srt_path = os.path.join(user_dir, f"sub_file_{session_id}.srt")
        output_path = os.path.join(user_dir, f"final_clip_file_{session_id}.mp4")
        temp_audio_path = os.path.join(user_dir, f"TEMP_MPY_wvf_snd_{session_id}.mp3")
        final_output = os.path.join(user_dir, f"final_video_{session_id}_{video_id}.mp4")

        # Initialize progress at 0%
        if progress_callback:
            progress_callback("Starting video creation...|0")

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
            
        # Clean the script for TTS to improve audio quality
        script_info = clean_script_for_tts(script)
        tts_script = script_info['text']
        
        # Log cleaning results
        print(f"Script cleaning results:")
        print(f"- Original script length: {script_info['original_length']} characters")
        print(f"- Cleaned script length: {script_info['cleaned_length']} characters")
        print(f"- Characters removed: {script_info['chars_removed']} ({script_info['percent_removed']}%)")
        
        # Save both original and cleaned scripts for reference
        with open(os.path.join(user_dir, f"original_script_{session_id}.txt"), "w", encoding="utf-8") as f:
            f.write(script)
        with open(os.path.join(user_dir, f"cleaned_script_{session_id}.txt"), "w", encoding="utf-8") as f:
            f.write(tts_script)
            
        # Select the appropriate model based on language
        if language.lower() == "english":
            model_id = "eleven_multilingual_v2"  # Works well for English
        else:
            model_id = "eleven_multilingual_v2"  # Works for Romanian and other languages
            
        # Generate audio using ElevenLabs with voice parameters
        print(f"Generating audio file for {language} language...")
        audio_stream = client.text_to_speech.convert_as_stream(
            text=tts_script,
            voice_id=VOICE_ID,
            model_id=model_id,
            voice_settings={
                "stability": 0.68,
                "similarity_boost": 0.85,
                "style": 0.05,
                "use_speaker_boost": True
            }
        )
        
        # Save the streaming audio
        with open(audio_path, "wb") as file:
            for chunk in audio_stream:
                if isinstance(chunk, bytes):
                    file.write(chunk)

        if progress_callback:
            progress_callback("Audio file generated successfully|20")

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
        words_with_times = get_word_timestamps_from_google(audio_path, language)
        
        if progress_callback:
            progress_callback("Processing word timings...|35")
        
        # Align the cleaned script with the recognized words
        aligned_words = align_texts(tts_script, words_with_times)
        
        if progress_callback:
            progress_callback("Creating subtitle file...|40")
        
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
        total_files = len(broll_files)
        for idx, broll_path in enumerate(broll_files, 1):
            if progress_callback:
                progress_callback(f"Processing b-roll {idx}/{total_files}...|{50 + (idx/total_files * 10)}")
                
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

        if progress_callback:
            progress_callback("Preparing final video sequence...|65")

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

        if progress_callback:
            progress_callback("Concatenating video clips...|70")

        # Concatenate all clips
        final_clip = concatenate_videoclips(final_clips)
        
        if progress_callback:
            progress_callback("Processing audio tracks...|75")
            
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
                if "Building video" in msg:
                    progress_callback("Rendering video - Preparing...|80")
                elif "Writing audio" in msg:
                    progress_callback("Rendering video - Processing audio...|82")
                elif "Writing video" in msg:
                    progress_callback("Rendering video - Processing frames...|85")
                elif "frame" in msg:
                    # Extract frame number and total frames
                    try:
                        frame_info = msg.split("frame=")[1].split("/")[0].strip()
                        total_frames = msg.split("frames=")[1].split()[0].strip()
                        percent = (int(frame_info) / int(total_frames)) * 100
                        progress_callback(f"Rendering video - Processing frames ({percent:.0f}%)|{85 + (percent * 0.05)}")
                    except:
                        progress_callback(msg)
                elif "Done" in msg:
                    progress_callback("Rendering video - Finalizing...|90")
                else:
                    progress_callback(msg)
                
        sse_logger = SSELogger(sse_callback=sse_callback)
        
        if progress_callback:
            progress_callback("Rendering final video...|80")
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
                if progress_callback:
                    progress_callback("Rendering final video with subtitles...|95")
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
            progress_callback("Video creation complete!|100")
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

def create_romanian_video(romanian_script, session_id, selected_music="funny 2.mp3", voice_id="gbLy9ep70G3JW53cTzFC", progress_callback=None, broll_files=None):
    """Backward compatibility wrapper for create_video function"""
    return create_video(
        script=romanian_script,
        session_id=session_id,
        language="romanian",
        selected_music=selected_music,
        voice_id=voice_id,
        progress_callback=progress_callback,
        broll_files=broll_files
    )

if __name__ == "__main__":
    create_video()