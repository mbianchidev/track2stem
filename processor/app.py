import os
import subprocess
import logging
import traceback
import threading
import time
import re
import pty
import select
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import shutil

# Validation pattern for job IDs: alphanumeric characters and hyphens only (up to 255 characters)
JOB_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-]{0,254}$')
ALLOWED_OUTPUT_FORMATS = {'mp3', 'wav', 'flac'}
ALLOWED_STEM_MODES = {'all', 'isolate'}
ALLOWED_STEMS = {'vocals', 'drums', 'bass', 'guitar', 'piano', 'other'}
ALLOWED_MODELS = {
    'htdemucs', 'htdemucs_ft', 'htdemucs_6s', 'hdemucs_mmi',
    'mdx', 'mdx_extra', 'mdx_q', 'mdx_extra_q',
}
SIX_STEM_MODELS = {'htdemucs_6s'}
ALLOWED_CLIP_MODES = {'rescale', 'clamp'}
ALLOWED_SHIFTS = set(range(0, 11))  # 0-10
ALLOWED_SEGMENTS = {None, 8, 10, 15, 20, 25, 30, 40, 60}
ALLOWED_OVERLAPS = {None, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5}


def validate_job_id(job_id):
    """Validate that job_id contains only safe characters (alphanumeric and hyphens)."""
    if not job_id or not JOB_ID_PATTERN.match(job_id):
        return False
    return True


def safe_join(base_dir, *paths):
    """Safely join paths and ensure the result stays within the base directory."""
    joined = os.path.join(base_dir, *paths)
    real_base = os.path.realpath(base_dir)
    real_joined = os.path.realpath(joined)
    try:
        common = os.path.commonpath([real_base, real_joined])
    except ValueError:
        # Raised, for example, if paths are on different drives on Windows
        raise ValueError(f"Path traversal detected: {joined} escapes {base_dir}")
    if common != real_base:
        raise ValueError(f"Path traversal detected: {joined} escapes {base_dir}")
    # Return the normalized, verified-safe path
    return real_joined

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

UPLOAD_FOLDER = '/app/uploads'
OUTPUT_FOLDER = '/app/outputs'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'}
WAV_EXTENSIONS = {'wav'}  # Extensions that support WAV output

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Track processing progress
processing_status = {}

# Track active subprocesses for cancellation
active_processes = {}
process_lock = threading.Lock()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_wav_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in WAV_EXTENSIONS

def convert_to_flac(src_path, dst_path):
    """Convert an audio file to FLAC format using ffmpeg."""
    ffmpeg_cmd = ['ffmpeg', '-y', '-i', src_path, dst_path]
    logger.info(f"Converting to FLAC: {' '.join(ffmpeg_cmd)}")
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FLAC conversion failed: {result.stderr}")
        raise RuntimeError(f"FLAC conversion failed for {src_path}")
    # Remove original file after successful conversion
    if os.path.exists(src_path):
        os.remove(src_path)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """Get processing status for a job"""
    if not validate_job_id(job_id):
        return jsonify({'error': 'Invalid job ID'}), 400
    if job_id in processing_status:
        return jsonify(processing_status[job_id])
    return jsonify({'status': 'unknown', 'progress': 0})

@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    """Cancel a running job by killing its subprocess"""
    if not validate_job_id(job_id):
        return jsonify({'error': 'Invalid job ID'}), 400
    logger.info(f"Cancel request received for job: {job_id}")
    
    with process_lock:
        if job_id in active_processes:
            proc_info = active_processes[job_id]
            process = proc_info.get('process')
            stop_event = proc_info.get('stop_event')
            master_fd = proc_info.get('master_fd')
            
            if stop_event:
                stop_event.set()
            
            # Close PTY master fd first
            if master_fd:
                try:
                    os.close(master_fd)
                except:
                    pass
            
            if process and process.poll() is None:  # Still running
                logger.info(f"Killing process for job {job_id}")
                try:
                    process.terminate()
                    # Give it a moment to terminate gracefully
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()  # Force kill if it doesn't stop
                    logger.info(f"Process for job {job_id} terminated")
                except Exception as e:
                    logger.error(f"Error killing process: {e}")
            
            # Clean up
            del active_processes[job_id]
            processing_status[job_id] = {'status': 'cancelled', 'progress': 0, 'stage': 'Cancelled by user'}
            
            # Clean up any partial files
            job_output_dir = safe_join(OUTPUT_FOLDER, job_id)
            if os.path.exists(job_output_dir):
                try:
                    shutil.rmtree(job_output_dir)
                    logger.info(f"Cleaned up output directory for cancelled job {job_id}")
                except Exception as e:
                    logger.error(f"Error cleaning up output dir: {e}")
            
            return jsonify({'status': 'cancelled', 'job_id': job_id})
        else:
            logger.info(f"No active process found for job {job_id}")
            return jsonify({'status': 'not_found', 'job_id': job_id}), 404

@app.route('/process', methods=['POST'])
def process_audio():
    logger.info("=== Starting new processing request ===")
    job_id = None
    start_time = time.time()  # Track processing time
    
    try:
        if 'file' not in request.files:
            logger.error("No file in request")
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        job_id = request.form.get('job_id', 'unknown')
        output_format = request.form.get('output_format', 'mp3').lower()  # mp3, wav, or flac
        stem_mode = request.form.get('stem_mode', 'all').lower()  # 'all' or 'isolate'
        isolate_stem = request.form.get('isolate_stem', 'vocals').lower()  # which stem to isolate
        model = request.form.get('model', 'htdemucs_6s').lower()  # demucs model
        clip_mode = request.form.get('clip_mode', 'rescale').lower()  # rescale or clamp
        
        # Parse numeric options with safe defaults
        try:
            shifts = int(request.form.get('shifts', '0'))
        except (ValueError, TypeError):
            shifts = 0
        
        segment_raw = request.form.get('segment', '')
        segment = None
        if segment_raw:
            try:
                segment = int(segment_raw)
            except (ValueError, TypeError):
                segment = None
        
        overlap_raw = request.form.get('overlap', '')
        overlap = None
        if overlap_raw:
            try:
                overlap = float(overlap_raw)
            except (ValueError, TypeError):
                overlap = None
        
        # Validate user inputs to prevent injection and path traversal
        if not validate_job_id(job_id):
            logger.error(f"Invalid job ID: {job_id}")
            return jsonify({'error': 'Invalid job ID'}), 400
        
        if output_format not in ALLOWED_OUTPUT_FORMATS:
            logger.error(f"Invalid output format: {output_format}")
            return jsonify({'error': 'Invalid output format'}), 400
        
        if stem_mode not in ALLOWED_STEM_MODES:
            logger.error(f"Invalid stem mode: {stem_mode}")
            return jsonify({'error': 'Invalid stem mode'}), 400
        
        if isolate_stem not in ALLOWED_STEMS:
            logger.error(f"Invalid isolate stem: {isolate_stem}")
            return jsonify({'error': 'Invalid isolate stem'}), 400
        
        if model not in ALLOWED_MODELS:
            logger.error(f"Invalid model: {model}")
            return jsonify({'error': 'Invalid model'}), 400
        
        if clip_mode not in ALLOWED_CLIP_MODES:
            logger.error(f"Invalid clip mode: {clip_mode}")
            return jsonify({'error': 'Invalid clip mode'}), 400
        
        if shifts not in ALLOWED_SHIFTS:
            logger.error(f"Invalid shifts value: {shifts}")
            return jsonify({'error': 'Invalid shifts value'}), 400
        
        if segment is not None and segment not in ALLOWED_SEGMENTS:
            logger.error(f"Invalid segment value: {segment}")
            return jsonify({'error': 'Invalid segment value'}), 400
        
        if overlap is not None and overlap not in ALLOWED_OVERLAPS:
            logger.error(f"Invalid overlap value: {overlap}")
            return jsonify({'error': 'Invalid overlap value'}), 400
        
        logger.info(f"Job ID: {job_id}, Filename: {file.filename}, Format: {output_format}, Mode: {stem_mode}, Isolate: {isolate_stem}, Model: {model}")
        
        # Initialize status
        processing_status[job_id] = {'status': 'uploading', 'progress': 5, 'stage': 'Receiving file'}
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            logger.error(f"File type not allowed: {file.filename}")
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Determine output format
        # For demucs: use WAV output when user requests wav or flac (flac converted after)
        # Use MP3 output when user requests mp3
        if output_format == 'mp3':
            demucs_output_fmt = 'mp3'
        else:
            # WAV and FLAC both use WAV from demucs; FLAC is converted afterwards
            demucs_output_fmt = 'wav'
        actual_output_format = output_format
        logger.info(f"Requested format: {output_format}, Demucs output: {demucs_output_fmt}")
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        # The filename from backend includes job_id prefix like "uuid_originalname.mp3"
        # Extract the original filename by removing the job_id prefix if present
        if filename.startswith(job_id + '_'):
            original_filename = filename[len(job_id) + 1:]
        else:
            original_filename = filename
        
        input_path = safe_join(UPLOAD_FOLDER, f"{job_id}_{original_filename}")
        logger.info(f"Saving file to: {input_path}")
        logger.info(f"Original filename: {original_filename}")
        file.save(input_path)
        
        file_size = os.path.getsize(input_path)
        logger.info(f"File saved successfully. Size: {file_size / (1024*1024):.2f} MB")
        
        processing_status[job_id] = {'status': 'processing', 'progress': 10, 'stage': 'File saved, starting separation'}
        
        # Create output directory for this job
        job_output_dir = safe_join(OUTPUT_FOLDER, job_id)
        os.makedirs(job_output_dir, exist_ok=True)
        logger.info(f"Output directory created: {job_output_dir}")
        
        # Run Demucs separation
        processing_status[job_id] = {'status': 'processing', 'progress': 15, 'stage': f'Loading AI model ({model})'}
        logger.info(f"Starting Demucs separation with {model} model...")
        
        cmd = [
            'python', '-m', 'demucs',
            '-o', OUTPUT_FOLDER,
            '-n', model,
        ]
        
        # Add format-specific options
        if demucs_output_fmt == 'mp3':
            cmd.extend([
                '--mp3',
                '--mp3-bitrate', '320',  # Highest quality MP3 (320 kbps)
            ])
        # For WAV/FLAC output, demucs outputs WAV by default (no --mp3 flag)
        
        # Add clip mode
        if clip_mode == 'clamp':
            cmd.extend(['--clip-mode', 'clamp'])
        
        # Add shifts (shift trick for better quality, N times slower)
        if shifts > 0:
            cmd.extend(['--shifts', str(shifts)])
        
        # Add segment size (for memory management)
        if segment is not None:
            cmd.extend(['--segment', str(segment)])
        
        # Add overlap
        if overlap is not None:
            cmd.extend(['--overlap', str(overlap)])
        
        cmd.append(input_path)
        
        logger.info(f"Running command: {' '.join(cmd)}")
        processing_status[job_id] = {'status': 'processing', 'progress': 10, 'stage': 'Starting AI separation...'}
        
        # Use PTY to capture tqdm progress output (tqdm uses \r for updates)
        # PTY makes demucs think it's writing to a terminal, so we get real-time updates
        master_fd, slave_fd = pty.openpty()
        
        process = subprocess.Popen(
            cmd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env={**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'PYTHONUNBUFFERED': '1', 'TERM': 'xterm'}
        )
        
        # Close slave FD in parent process
        os.close(slave_fd)
        
        # Store process reference for cancellation
        stop_threads = threading.Event()
        with process_lock:
            active_processes[job_id] = {
                'process': process,
                'stop_event': stop_threads,
                'master_fd': master_fd
            }
        
        # Tracking variables
        output_lines = []
        last_progress = 10
        progress_lock = threading.Lock()
        
        def format_elapsed(seconds):
            """Format elapsed time as Xm Ys"""
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        def update_progress(new_progress, stage_msg):
            """Thread-safe progress update"""
            nonlocal last_progress
            with progress_lock:
                if new_progress > last_progress:
                    last_progress = new_progress
                    elapsed = time.time() - start_time
                    processing_status[job_id] = {
                        'status': 'processing',
                        'progress': new_progress,
                        'stage': stage_msg,
                        'elapsed': format_elapsed(elapsed)
                    }
                    logger.info(f"Progress: {new_progress}% - {stage_msg}")
        
        # Regex patterns for tqdm output
        progress_pattern = re.compile(r'(\d+)%\|')
        fraction_pattern = re.compile(r'(\d+)/(\d+)')
        
        def read_output():
            """Read PTY output and parse progress"""
            buffer = ""
            
            while not stop_threads.is_set():
                try:
                    # Use select to check if data is available (with timeout)
                    ready, _, _ = select.select([master_fd], [], [], 0.5)
                    
                    if not ready:
                        # Check if process has ended
                        if process.poll() is not None:
                            break
                        continue
                    
                    # Read available data
                    try:
                        chunk = os.read(master_fd, 4096).decode('utf-8', errors='replace')
                    except OSError:
                        break
                    
                    if not chunk:
                        break
                    
                    buffer += chunk
                    
                    # Process buffer - split by \r or \n to handle tqdm updates
                    while '\r' in buffer or '\n' in buffer:
                        # Find first delimiter
                        r_idx = buffer.find('\r')
                        n_idx = buffer.find('\n')
                        
                        if r_idx != -1 and (n_idx == -1 or r_idx < n_idx):
                            line, buffer = buffer[:r_idx], buffer[r_idx+1:]
                        else:
                            line, buffer = buffer[:n_idx], buffer[n_idx+1:]
                        
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Remove ANSI escape codes for cleaner logging
                        clean_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line)
                        if clean_line:
                            output_lines.append(clean_line)
                            logger.info(f"[Demucs] {clean_line}")
                        
                        # Parse progress from tqdm output
                        progress_match = progress_pattern.search(line)
                        if progress_match:
                            try:
                                pct = int(progress_match.group(1))
                                # Map demucs 0-100% to our 10-90%
                                mapped = 10 + int(pct * 0.80)
                                update_progress(mapped, f'Separating stems... ({mapped}%)')
                            except (ValueError, IndexError):
                                pass
                        else:
                            # Check for model loading messages
                            lower_line = line.lower()
                            if 'loading' in lower_line or 'downloading' in lower_line:
                                update_progress(12, 'Loading AI model...')
                            elif 'separating' in lower_line:
                                frac_match = fraction_pattern.search(line)
                                if frac_match:
                                    try:
                                        curr, total = int(frac_match.group(1)), int(frac_match.group(2))
                                        if total > 0:
                                            pct = int((curr / total) * 100)
                                            mapped = 10 + int(pct * 0.80)
                                            update_progress(mapped, f'Processing track {curr}/{total}... ({mapped}%)')
                                    except:
                                        pass
                                        
                except Exception as e:
                    logger.warning(f"Error reading output: {e}")
                    break
            
            # Process any remaining buffer
            if buffer.strip():
                clean = re.sub(r'\x1b\[[0-9;]*[mK]', '', buffer.strip())
                if clean:
                    output_lines.append(clean)
                    logger.info(f"[Demucs] {clean}")
        
        def estimate_progress():
            """Time-based progress estimation - updates immediately, then every 2 seconds"""
            # Typical processing: 3-10 minutes depending on file size
            estimated_duration = 300  # 5 minute baseline
            
            # Update immediately on first run, then every 2 seconds
            while not stop_threads.is_set():
                elapsed = time.time() - start_time
                
                # Calculate time-based progress (10% to 85%)
                time_progress = 10 + min(75, int((elapsed / estimated_duration) * 75))
                
                with progress_lock:
                    current = last_progress
                    status = processing_status.get(job_id, {})
                    
                    # Only update if time-based is higher and we're still processing
                    if (time_progress > current and 
                        status.get('status') == 'processing' and
                        current < 85):
                        processing_status[job_id] = {
                            'status': 'processing',
                            'progress': time_progress,
                            'stage': f'Processing audio... ({time_progress}%)',
                            'elapsed': format_elapsed(elapsed)
                        }
                
                # Sleep after update (so first update is immediate)
                for _ in range(4):  # 4 x 0.5s = 2s, but check stop_threads frequently
                    if stop_threads.is_set():
                        break
                    time.sleep(0.5)
        
        # Start both threads
        output_thread = threading.Thread(target=read_output, daemon=True)
        estimation_thread = threading.Thread(target=estimate_progress, daemon=True)
        output_thread.start()
        estimation_thread.start()
        
        logger.info(f"Started output reader and progress estimator for job {job_id}")
        
        # Wait for process to complete
        try:
            return_code = process.wait(timeout=1800)  # 30 min timeout
        except subprocess.TimeoutExpired:
            process.kill()
            stop_threads.set()
            try:
                os.close(master_fd)
            except:
                pass
            output_thread.join(timeout=5)
            estimation_thread.join(timeout=2)
            with process_lock:
                if job_id in active_processes:
                    del active_processes[job_id]
            raise subprocess.TimeoutExpired(cmd, 1800)
        
        # Signal threads to stop and clean up
        stop_threads.set()
        try:
            os.close(master_fd)
        except:
            pass
        output_thread.join(timeout=10)
        estimation_thread.join(timeout=2)
        
        full_output = '\n'.join(output_lines)
        
        if return_code != 0:
            logger.error(f"Demucs failed with return code {return_code}")
            logger.error(f"Output: {full_output}")
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': 'Processing failed'}
            # Clean up from active_processes
            with process_lock:
                if job_id in active_processes:
                    del active_processes[job_id]
            return jsonify({
                'error': 'Processing failed',
                'details': full_output
            }), 500
        
        elapsed = time.time() - start_time
        processing_status[job_id] = {'status': 'processing', 'progress': 90, 'stage': 'AI separation complete, organizing files...', 'elapsed': format_elapsed(elapsed)}
        logger.info("Demucs completed successfully, organizing output files...")
        
        # Demucs creates: OUTPUT_FOLDER/{model}/filename_without_ext/stem.mp3 (or .wav)
        # Use the original filename with job_id prefix consistently
        filename_no_ext = os.path.splitext(f"{job_id}_{original_filename}")[0]
        demucs_output = safe_join(OUTPUT_FOLDER, model, filename_no_ext)
        
        logger.info(f"Looking for output in: {demucs_output}")
        
        if not os.path.exists(demucs_output):
            # Try alternate paths for the model
            alt_path = safe_join(OUTPUT_FOLDER, model, os.path.splitext(filename)[0])
            logger.info(f"Trying alternate path: {alt_path}")
            if os.path.exists(alt_path):
                demucs_output = alt_path
            else:
                # List what's actually there
                model_dir = os.path.join(OUTPUT_FOLDER, model)
                if os.path.exists(model_dir):
                    contents = os.listdir(model_dir)
                    logger.info(f"Contents of {model} dir: {contents}")
                    if contents:
                        demucs_output = os.path.join(model_dir, contents[0])
                        logger.info(f"Using first directory: {demucs_output}")
        
        # Move files to job output directory and collect paths
        output_files = {}
        # Determine available stems based on model
        if model in SIX_STEM_MODELS:
            all_stems = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other']
        else:
            all_stems = ['vocals', 'drums', 'bass', 'other']
        demucs_ext = 'wav' if demucs_output_fmt == 'wav' else 'mp3'
        
        # Get original filename without extension for naming output files
        original_name_no_ext = os.path.splitext(original_filename)[0]
        
        if stem_mode == 'isolate':
            # Isolate mode: output the isolated stem + combined "other" track
            logger.info(f"Isolate mode: extracting {isolate_stem} and combining the rest")
            
            # First, get the isolated stem
            for ext in [demucs_ext, 'mp3', 'wav']:
                src = os.path.join(demucs_output, f"{isolate_stem}.{ext}")
                if os.path.exists(src):
                    if actual_output_format == 'flac':
                        dst_filename = f"{original_name_no_ext}_t2s_{isolate_stem}.flac"
                        dst = os.path.join(job_output_dir, dst_filename)
                        convert_to_flac(src, dst)
                    else:
                        dst_filename = f"{original_name_no_ext}_t2s_{isolate_stem}.{ext}"
                        dst = os.path.join(job_output_dir, dst_filename)
                        shutil.move(src, dst)
                    logger.info(f"Isolated stem saved: {dst}")
                    output_files[isolate_stem] = dst
                    break
            
            # Now combine all other stems into "instrumental" or "backing"
            # We'll use ffmpeg to mix them
            other_stems = [s for s in all_stems if s != isolate_stem]
            stem_files = []
            for stem in other_stems:
                for ext in [demucs_ext, 'mp3', 'wav']:
                    src = os.path.join(demucs_output, f"{stem}.{ext}")
                    if os.path.exists(src):
                        stem_files.append(src)
                        break
            
            if stem_files:
                # Use ffmpeg to mix the remaining stems
                backing_name = "instrumental" if isolate_stem == "vocals" else "backing"
                dst_filename = f"{original_name_no_ext}_t2s_{backing_name}.{actual_output_format}"
                dst = os.path.join(job_output_dir, dst_filename)
                
                # Build ffmpeg command to mix multiple audio files
                ffmpeg_cmd = ['ffmpeg', '-y']
                for f in stem_files:
                    ffmpeg_cmd.extend(['-i', f])
                
                # Create filter to mix all inputs
                # Use normalize=1 to properly normalize the mixed output and prevent clipping
                filter_complex = f"amix=inputs={len(stem_files)}:duration=longest:normalize=1"
                ffmpeg_cmd.extend(['-filter_complex', filter_complex])
                
                # Output settings
                if actual_output_format == 'mp3':
                    ffmpeg_cmd.extend(['-b:a', '320k'])
                ffmpeg_cmd.append(dst)
                
                logger.info(f"Mixing stems with ffmpeg: {' '.join(ffmpeg_cmd)}")
                mix_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                
                if mix_result.returncode == 0:
                    output_files[backing_name] = dst
                    logger.info(f"Created combined backing track: {dst}")
                else:
                    logger.error(f"FFmpeg mix failed: {mix_result.stderr}")
        else:
            # All stems mode: output all stems
            for stem in all_stems:
                for ext in [demucs_ext, 'mp3', 'wav']:
                    src = os.path.join(demucs_output, f"{stem}.{ext}")
                    if os.path.exists(src):
                        if actual_output_format == 'flac':
                            dst_filename = f"{original_name_no_ext}_t2s_{stem}.flac"
                            dst = os.path.join(job_output_dir, dst_filename)
                            convert_to_flac(src, dst)
                        else:
                            dst_filename = f"{original_name_no_ext}_t2s_{stem}.{ext}"
                            dst = os.path.join(job_output_dir, dst_filename)
                            shutil.move(src, dst)
                        logger.info(f"Stem saved: {dst}")
                        output_files[stem] = dst
                        break
        
        logger.info(f"Output files collected: {list(output_files.keys())}")
        elapsed = time.time() - start_time
        processing_status[job_id] = {'status': 'processing', 'progress': 95, 'stage': 'Cleaning up', 'elapsed': format_elapsed(elapsed)}
        
        # Clean up demucs directory
        if os.path.exists(demucs_output):
            shutil.rmtree(demucs_output)
        parent_dir = os.path.join(OUTPUT_FOLDER, model)
        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
            os.rmdir(parent_dir)
        
        # Clean up input file
        if os.path.exists(input_path):
            os.remove(input_path)
            logger.info(f"Cleaned up input file: {input_path}")
        
        # Calculate total processing time
        end_time = time.time()
        total_time = end_time - start_time
        minutes = int(total_time // 60)
        seconds = int(total_time % 60)
        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        
        processing_status[job_id] = {'status': 'completed', 'progress': 100, 'stage': 'Complete!', 'elapsed': time_str, 'total_time': time_str}
        logger.info(f"=== Job {job_id} completed successfully with {len(output_files)} stems in {time_str} ===")
        
        # Clean up from active_processes
        with process_lock:
            if job_id in active_processes:
                del active_processes[job_id]
        
        return jsonify({
            'status': 'completed',
            'job_id': job_id,
            'outputs': output_files,
            'format': actual_output_format,
            'processing_time': time_str
        })
    
    except subprocess.TimeoutExpired:
        logger.error("Processing timeout exceeded")
        if job_id:
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': 'Timeout'}
        return jsonify({'error': 'Processing timeout'}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        if job_id:
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': 'Error'}
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
