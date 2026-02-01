import os
import subprocess
import logging
import traceback
import threading
import time
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
        
        # Read output in real-time and update progress
        output_lines = []
        last_progress = 10
        
        def format_elapsed(seconds):
            """Format elapsed time as Xm Ys"""
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        def read_output():
            nonlocal last_progress
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    output_lines.append(line)
                    logger.info(f"[Demucs] {line}")
                    
                    # Parse progress from demucs output (looks for percentage)
                    if '%|' in line:
                        try:
                            # Extract percentage from progress bar like "50%|████"
                            pct_str = line.split('%|')[0].strip().split()[-1]
                            pct = int(float(pct_str))
                            # Demucs separation is 10-90% of total progress (80% of the bar)
                            # When demucs is at 50%, we should be at 50% total
                            # Map demucs 0-100% to our 10-90%
                            mapped_progress = 10 + int(pct * 0.80)
                            if mapped_progress > last_progress:
                                last_progress = mapped_progress
                                elapsed = time.time() - start_time
                                # Show progress with elapsed time
                                processing_status[job_id] = {
                                    'status': 'processing', 
                                    'progress': mapped_progress, 
                                    'stage': 'Separating audio stems...',
                                    'elapsed': format_elapsed(elapsed)
                                }
                        except (ValueError, IndexError):
                            pass
        
        # Read output in a thread to avoid blocking
        output_thread = threading.Thread(target=read_output)
        output_thread.start()
        
        # Wait for process to complete (with timeout)
        try:
            return_code = process.wait(timeout=1800)  # 30 min timeout
        except subprocess.TimeoutExpired:
            process.kill()
            output_thread.join(timeout=5)
            raise subprocess.TimeoutExpired(cmd, 1800)
        
        output_thread.join(timeout=10)
        
        full_output = '\n'.join(output_lines)
        
        if return_code != 0:
            logger.error(f"Demucs failed with return code {return_code}")
            logger.error(f"Output: {full_output}")
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': 'Processing failed'}
            return jsonify({
                'error': 'Processing failed',
                'details': full_output
            }), 500
        
        elapsed = time.time() - start_time
        processing_status[job_id] = {'status': 'processing', 'progress': 80, 'stage': 'Organizing output files', 'elapsed': format_elapsed(elapsed)}
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
