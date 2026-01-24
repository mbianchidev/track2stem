import os
import subprocess
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import shutil

app = Flask(__name__)

UPLOAD_FOLDER = '/app/uploads'
OUTPUT_FOLDER = '/app/outputs'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/process', methods=['POST'])
def process_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    job_id = request.form.get('job_id', 'unknown')
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Save uploaded file
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{filename}")
    file.save(input_path)
    
    # Create output directory for this job
    job_output_dir = os.path.join(OUTPUT_FOLDER, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    
    try:
        # Run Demucs separation
        # Using htdemucs model which separates into: drums, bass, other, vocals
        cmd = [
            'python', '-m', 'demucs',
            '-o', OUTPUT_FOLDER,
            '-n', 'htdemucs',
            input_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)  # 30 min timeout
        
        if result.returncode != 0:
            return jsonify({
                'error': 'Processing failed',
                'details': result.stderr
            }), 500
        
        # Demucs creates: OUTPUT_FOLDER/htdemucs/filename_without_ext/stem.wav
        filename_no_ext = os.path.splitext(f"{job_id}_{filename}")[0]
        demucs_output = os.path.join(OUTPUT_FOLDER, 'htdemucs', filename_no_ext)
        
        # Move files to job output directory and collect paths
        output_files = {}
        stems = ['drums', 'bass', 'other', 'vocals']
        
        for stem in stems:
            src = os.path.join(demucs_output, f"{stem}.wav")
            if os.path.exists(src):
                dst = os.path.join(job_output_dir, f"{stem}.wav")
                shutil.move(src, dst)
                output_files[stem] = dst
        
        # Clean up demucs directory
        if os.path.exists(demucs_output):
            shutil.rmtree(demucs_output)
        parent_dir = os.path.join(OUTPUT_FOLDER, 'htdemucs')
        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
            os.rmdir(parent_dir)
        
        # Clean up input file
        if os.path.exists(input_path):
            os.remove(input_path)
        
        return jsonify({
            'status': 'completed',
            'job_id': job_id,
            'outputs': output_files
        })
    
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Processing timeout'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
