import os
import subprocess
import logging
import traceback
import threading
import time
import re
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import shutil

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

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """Get processing status for a job"""
    if job_id in processing_status:
        return jsonify(processing_status[job_id])
    return jsonify({'status': 'unknown', 'progress': 0})

@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_job(job_id):
    """Cancel a running job by killing its subprocess"""
    logger.info(f"Cancel request received for job: {job_id}")
    
    with process_lock:
        if job_id in active_processes:
            proc_info = active_processes[job_id]
            process = proc_info.get('process')
            stop_event = proc_info.get('stop_event')
            
            if stop_event:
                stop_event.set()
            
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
            job_output_dir = os.path.join(OUTPUT_FOLDER, job_id)
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
        output_format = request.form.get('output_format', 'mp3').lower()  # mp3 or wav
        stem_mode = request.form.get('stem_mode', 'all')  # 'all' or 'isolate'
        isolate_stem = request.form.get('isolate_stem', 'vocals')  # which stem to isolate
        logger.info(f"Job ID: {job_id}, Filename: {file.filename}, Format: {output_format}, Mode: {stem_mode}, Isolate: {isolate_stem}")
        
        # Initialize status
        processing_status[job_id] = {'status': 'uploading', 'progress': 5, 'stage': 'Receiving file'}
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            logger.error(f"File type not allowed: {file.filename}")
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Determine output format: WAV only if input is WAV and user requested WAV
        input_is_wav = is_wav_file(file.filename)
        use_wav_output = (output_format == 'wav' and input_is_wav)
        actual_output_format = 'wav' if use_wav_output else 'mp3'
        logger.info(f"Input is WAV: {input_is_wav}, Output format: {actual_output_format}")
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        # The filename from backend includes job_id prefix like "uuid_originalname.mp3"
        # Extract the original filename by removing the job_id prefix if present
        if filename.startswith(job_id + '_'):
            original_filename = filename[len(job_id) + 1:]
        else:
            original_filename = filename
        
        input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{original_filename}")
        logger.info(f"Saving file to: {input_path}")
        logger.info(f"Original filename: {original_filename}")
        file.save(input_path)
        
        file_size = os.path.getsize(input_path)
        logger.info(f"File saved successfully. Size: {file_size / (1024*1024):.2f} MB")
        
        processing_status[job_id] = {'status': 'processing', 'progress': 10, 'stage': 'File saved, starting separation'}
        
        # Create output directory for this job
        job_output_dir = os.path.join(OUTPUT_FOLDER, job_id)
        os.makedirs(job_output_dir, exist_ok=True)
        logger.info(f"Output directory created: {job_output_dir}")
        
        # Run Demucs separation
        processing_status[job_id] = {'status': 'processing', 'progress': 15, 'stage': 'Loading AI model (htdemucs_6s)'}
        logger.info("Starting Demucs separation with htdemucs_6s model (6 stems)...")
        
        # Using htdemucs_6s model for 6 stems: vocals, drums, bass, guitar, piano, other
        # We'll expose 5 main stems: vocals, drums, guitar, bass, other (piano optional)
        cmd = [
            'python', '-m', 'demucs',
            '-o', OUTPUT_FOLDER,
            '-n', 'htdemucs_6s',  # 6 stems model for guitar separation
        ]
        
        # Add format-specific options
        if not use_wav_output:
            cmd.extend([
                '--mp3',
                '--mp3-bitrate', '320',  # Highest quality MP3 (320 kbps)
            ])
        # For WAV output, demucs outputs WAV by default (no --mp3 flag)
        
        cmd.append(input_path)
        
        logger.info(f"Running command: {' '.join(cmd)}")
        processing_status[job_id] = {'status': 'processing', 'progress': 10, 'stage': 'Starting AI separation...'}
        
        # Run with real-time logging using Popen
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout for unified logging
            text=True,
            bufsize=1,  # Line buffered
            env={**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'PYTHONUNBUFFERED': '1'}
        )
        
        # Store process reference for cancellation
        stop_estimation = threading.Event()
        with process_lock:
            active_processes[job_id] = {
                'process': process,
                'stop_event': stop_estimation
            }
        
        # Read output in real-time and update progress
        output_lines = []
        last_progress = 10
        
        def format_elapsed(seconds):
            """Format elapsed time as Xm Ys"""
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        # Regex patterns to match tqdm progress output
        # Pattern 1: "  0%|          | 0/100 [00:00<?, ?it/s]"
        # Pattern 2: " 50%|█████     | 50/100 [00:30<00:30, 1.67it/s]"
        # Pattern 3: "100%|██████████| 100/100 [01:00<00:00, 1.67it/s]"
        progress_pattern = re.compile(r'(\d+)%\|')
        # Also match fraction format: "50/100" or progress like "Separating track 1/6"
        fraction_pattern = re.compile(r'(\d+)/(\d+)')
        
        def read_output():
            nonlocal last_progress
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    output_lines.append(line)
                    logger.info(f"[Demucs] {line}")
                    
                    # Try to parse progress from tqdm output
                    progress_match = progress_pattern.search(line)
                    if progress_match:
                        try:
                            pct = int(progress_match.group(1))
                            # Demucs separation is 10-90% of total progress (80% of the bar)
                            # Map demucs 0-100% to our 10-90%
                            mapped_progress = 10 + int(pct * 0.80)
                            if mapped_progress > last_progress:
                                last_progress = mapped_progress
                                elapsed = time.time() - start_time
                                processing_status[job_id] = {
                                    'status': 'processing', 
                                    'progress': mapped_progress, 
                                    'stage': f'Separating audio stems... {pct}%',
                                    'elapsed': format_elapsed(elapsed)
                                }
                                logger.info(f"Progress update: {pct}% -> mapped to {mapped_progress}%")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Failed to parse progress: {e}")
                    else:
                        # Try fraction pattern for stem processing
                        frac_match = fraction_pattern.search(line)
                        if frac_match and ('Separating' in line or 'track' in line.lower()):
                            try:
                                current = int(frac_match.group(1))
                                total = int(frac_match.group(2))
                                if total > 0:
                                    pct = int((current / total) * 100)
                                    mapped_progress = 10 + int(pct * 0.80)
                                    if mapped_progress > last_progress:
                                        last_progress = mapped_progress
                                        elapsed = time.time() - start_time
                                        processing_status[job_id] = {
                                            'status': 'processing',
                                            'progress': mapped_progress,
                                            'stage': f'Processing stem {current}/{total}...',
                                            'elapsed': format_elapsed(elapsed)
                                        }
                            except (ValueError, ZeroDivisionError):
                                pass
                        # Check for loading/model messages
                        elif 'loading' in line.lower() or 'model' in line.lower():
                            elapsed = time.time() - start_time
                            processing_status[job_id] = {
                                'status': 'processing',
                                'progress': max(last_progress, 12),
                                'stage': 'Loading AI model...',
                                'elapsed': format_elapsed(elapsed)
                            }
        
        # Read output in a thread to avoid blocking
        output_thread = threading.Thread(target=read_output)
        output_thread.start()
        
        # Also run a time-based progress estimator as fallback
        # Typical processing takes 3-10 minutes, so we estimate based on time
        # stop_estimation event is already created above when storing in active_processes
        
        def estimate_progress():
            """Fallback progress estimation based on elapsed time"""
            # Assume typical processing takes about 5 minutes (300 seconds)
            # We use this to provide smooth progress updates when demucs doesn't output
            estimated_duration = 300  # 5 minutes baseline
            
            while not stop_estimation.is_set():
                time.sleep(5)  # Update every 5 seconds
                if stop_estimation.is_set():
                    break
                    
                elapsed = time.time() - start_time
                # Only update if we haven't gotten real progress updates
                current_status = processing_status.get(job_id, {})
                current_progress = current_status.get('progress', 10)
                
                # Time-based estimate: start at 10%, go up to 85% over estimated_duration
                time_based_progress = 10 + min(75, int((elapsed / estimated_duration) * 75))
                
                # Only use time-based if it's higher than current and we're still processing
                if (time_based_progress > current_progress and 
                    current_status.get('status') == 'processing' and
                    current_progress < 85):
                    processing_status[job_id] = {
                        'status': 'processing',
                        'progress': time_based_progress,
                        'stage': current_status.get('stage', 'Processing audio...'),
                        'elapsed': format_elapsed(elapsed)
                    }
        
        estimation_thread = threading.Thread(target=estimate_progress)
        estimation_thread.start()
        
        # Wait for process to complete (with timeout)
        try:
            return_code = process.wait(timeout=1800)  # 30 min timeout
        except subprocess.TimeoutExpired:
            process.kill()
            stop_estimation.set()
            output_thread.join(timeout=5)
            estimation_thread.join(timeout=2)
            # Clean up from active_processes
            with process_lock:
                if job_id in active_processes:
                    del active_processes[job_id]
            raise subprocess.TimeoutExpired(cmd, 1800)
        
        stop_estimation.set()
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
        
        # Demucs creates: OUTPUT_FOLDER/htdemucs_6s/filename_without_ext/stem.mp3 (or .wav)
        filename_no_ext = os.path.splitext(f"{job_id}_{filename}")[0]
        demucs_output = os.path.join(OUTPUT_FOLDER, 'htdemucs_6s', filename_no_ext)
        
        logger.info(f"Looking for output in: {demucs_output}")
        
        if not os.path.exists(demucs_output):
            # Try alternate paths for htdemucs_6s
            alt_path = os.path.join(OUTPUT_FOLDER, 'htdemucs_6s', os.path.splitext(filename)[0])
            logger.info(f"Trying alternate path: {alt_path}")
            if os.path.exists(alt_path):
                demucs_output = alt_path
            else:
                # List what's actually there
                htdemucs_dir = os.path.join(OUTPUT_FOLDER, 'htdemucs_6s')
                if os.path.exists(htdemucs_dir):
                    contents = os.listdir(htdemucs_dir)
                    logger.info(f"Contents of htdemucs_6s dir: {contents}")
                    if contents:
                        demucs_output = os.path.join(htdemucs_dir, contents[0])
                        logger.info(f"Using first directory: {demucs_output}")
        
        # Move files to job output directory and collect paths
        output_files = {}
        # htdemucs_6s produces 6 stems: vocals, drums, bass, guitar, piano, other
        all_stems = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other']
        output_ext = 'wav' if use_wav_output else 'mp3'
        
        # Get original filename without extension for naming output files
        original_name_no_ext = os.path.splitext(original_filename)[0]
        
        if stem_mode == 'isolate':
            # Isolate mode: output the isolated stem + combined "other" track
            logger.info(f"Isolate mode: extracting {isolate_stem} and combining the rest")
            
            # First, get the isolated stem
            for ext in [output_ext, 'mp3', 'wav']:
                src = os.path.join(demucs_output, f"{isolate_stem}.{ext}")
                if os.path.exists(src):
                    dst_filename = f"{original_name_no_ext}_t2s_{isolate_stem}.{ext}"
                    dst = os.path.join(job_output_dir, dst_filename)
                    logger.info(f"Moving isolated stem {src} to {dst}")
                    shutil.move(src, dst)
                    output_files[isolate_stem] = dst
                    break
            
            # Now combine all other stems into "instrumental" or "backing"
            # We'll use ffmpeg to mix them
            other_stems = [s for s in all_stems if s != isolate_stem]
            stem_files = []
            for stem in other_stems:
                for ext in [output_ext, 'mp3', 'wav']:
                    src = os.path.join(demucs_output, f"{stem}.{ext}")
                    if os.path.exists(src):
                        stem_files.append(src)
                        break
            
            if stem_files:
                # Use ffmpeg to mix the remaining stems
                backing_name = "instrumental" if isolate_stem == "vocals" else "backing"
                dst_filename = f"{original_name_no_ext}_t2s_{backing_name}.{output_ext}"
                dst = os.path.join(job_output_dir, dst_filename)
                
                # Build ffmpeg command to mix multiple audio files
                ffmpeg_cmd = ['ffmpeg', '-y']
                for f in stem_files:
                    ffmpeg_cmd.extend(['-i', f])
                
                # Create filter to mix all inputs
                filter_complex = f"amix=inputs={len(stem_files)}:duration=longest:normalize=0"
                ffmpeg_cmd.extend(['-filter_complex', filter_complex])
                
                # Output settings
                if output_ext == 'mp3':
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
            # All stems mode: output all 6 stems
            for stem in all_stems:
                for ext in [output_ext, 'mp3', 'wav']:
                    src = os.path.join(demucs_output, f"{stem}.{ext}")
                    if os.path.exists(src):
                        dst_filename = f"{original_name_no_ext}_t2s_{stem}.{ext}"
                        dst = os.path.join(job_output_dir, dst_filename)
                        logger.info(f"Moving {src} to {dst}")
                        shutil.move(src, dst)
                        output_files[stem] = dst
                        break
        
        logger.info(f"Output files collected: {list(output_files.keys())}")
        elapsed = time.time() - start_time
        processing_status[job_id] = {'status': 'processing', 'progress': 95, 'stage': 'Cleaning up', 'elapsed': format_elapsed(elapsed)}
        
        # Clean up demucs directory
        if os.path.exists(demucs_output):
            shutil.rmtree(demucs_output)
        parent_dir = os.path.join(OUTPUT_FOLDER, 'htdemucs_6s')
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
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': f'Error: {str(e)}'}
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
