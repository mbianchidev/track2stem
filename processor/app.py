import os
import subprocess
import logging
import traceback
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

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Track processing progress
processing_status = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    
    try:
        if 'file' not in request.files:
            logger.error("No file in request")
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        job_id = request.form.get('job_id', 'unknown')
        logger.info(f"Job ID: {job_id}, Filename: {file.filename}")
        
        # Initialize status
        processing_status[job_id] = {'status': 'uploading', 'progress': 5, 'stage': 'Receiving file'}
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            logger.error(f"File type not allowed: {file.filename}")
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{filename}")
        logger.info(f"Saving file to: {input_path}")
        file.save(input_path)
        
        file_size = os.path.getsize(input_path)
        logger.info(f"File saved successfully. Size: {file_size / (1024*1024):.2f} MB")
        
        processing_status[job_id] = {'status': 'processing', 'progress': 10, 'stage': 'File saved, starting separation'}
        
        # Create output directory for this job
        job_output_dir = os.path.join(OUTPUT_FOLDER, job_id)
        os.makedirs(job_output_dir, exist_ok=True)
        logger.info(f"Output directory created: {job_output_dir}")
        
        # Run Demucs separation
        processing_status[job_id] = {'status': 'processing', 'progress': 15, 'stage': 'Loading AI model'}
        logger.info("Starting Demucs separation...")
        
        # Using htdemucs model (4 stems: vocals, drums, bass, other)
        # htdemucs_6s requires more GPU memory, fallback to htdemucs
        cmd = [
            'python', '-m', 'demucs',
            '-o', OUTPUT_FOLDER,
            '-n', 'htdemucs',
            '--mp3',  # Output as MP3 to save space
            input_path
        ]
        
        logger.info(f"Running command: {' '.join(cmd)}")
        processing_status[job_id] = {'status': 'processing', 'progress': 20, 'stage': 'Separating audio stems (this takes a while)'}
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=1800,  # 30 min timeout
            env={**os.environ, 'CUDA_VISIBLE_DEVICES': ''}  # Force CPU mode
        )
        
        logger.info(f"Demucs stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"Demucs stderr: {result.stderr}")
        
        if result.returncode != 0:
            logger.error(f"Demucs failed with return code {result.returncode}")
            logger.error(f"Stderr: {result.stderr}")
            processing_status[job_id] = {'status': 'failed', 'progress': 0, 'stage': 'Processing failed'}
            return jsonify({
                'error': 'Processing failed',
                'details': result.stderr
            }), 500
        
        processing_status[job_id] = {'status': 'processing', 'progress': 80, 'stage': 'Organizing output files'}
        logger.info("Demucs completed successfully, organizing output files...")
        
        # Demucs creates: OUTPUT_FOLDER/htdemucs/filename_without_ext/stem.mp3
        filename_no_ext = os.path.splitext(f"{job_id}_{filename}")[0]
        demucs_output = os.path.join(OUTPUT_FOLDER, 'htdemucs', filename_no_ext)
        
        logger.info(f"Looking for output in: {demucs_output}")
        
        if not os.path.exists(demucs_output):
            # Try without job_id prefix
            alt_path = os.path.join(OUTPUT_FOLDER, 'htdemucs', os.path.splitext(filename)[0])
            logger.info(f"Trying alternate path: {alt_path}")
            if os.path.exists(alt_path):
                demucs_output = alt_path
            else:
                # List what's actually there
                htdemucs_dir = os.path.join(OUTPUT_FOLDER, 'htdemucs')
                if os.path.exists(htdemucs_dir):
                    contents = os.listdir(htdemucs_dir)
                    logger.info(f"Contents of htdemucs dir: {contents}")
                    if contents:
                        demucs_output = os.path.join(htdemucs_dir, contents[0])
                        logger.info(f"Using first directory: {demucs_output}")
        
        # Move files to job output directory and collect paths
        output_files = {}
        stems = ['vocals', 'drums', 'bass', 'other']  # htdemucs produces 4 stems
        
        for stem in stems:
            # Check for both mp3 and wav
            for ext in ['mp3', 'wav']:
                src = os.path.join(demucs_output, f"{stem}.{ext}")
                if os.path.exists(src):
                    dst = os.path.join(job_output_dir, f"{stem}.{ext}")
                    logger.info(f"Moving {src} to {dst}")
                    shutil.move(src, dst)
                    output_files[stem] = dst
                    break
        
        logger.info(f"Output files collected: {list(output_files.keys())}")
        processing_status[job_id] = {'status': 'processing', 'progress': 90, 'stage': 'Cleaning up'}
        
        # Clean up demucs directory
        if os.path.exists(demucs_output):
            shutil.rmtree(demucs_output)
        parent_dir = os.path.join(OUTPUT_FOLDER, 'htdemucs')
        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
            os.rmdir(parent_dir)
        
        # Clean up input file
        if os.path.exists(input_path):
            os.remove(input_path)
            logger.info(f"Cleaned up input file: {input_path}")
        
        processing_status[job_id] = {'status': 'completed', 'progress': 100, 'stage': 'Done'}
        logger.info(f"=== Job {job_id} completed successfully ===")
        
        return jsonify({
            'status': 'completed',
            'job_id': job_id,
            'outputs': output_files
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
