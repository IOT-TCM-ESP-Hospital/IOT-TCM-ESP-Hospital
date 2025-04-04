from flask import Flask, request, jsonify
from datetime import datetime
import os
import json
import threading
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuration
DATA_STORAGE_DIR = "received_data"
PORT = 5000
HOST = "127.0.0.1"  # Listen on all interfaces
ALLOWED_EXTENSIONS = {'mp4'}

# Create data storage directory
os.makedirs(DATA_STORAGE_DIR, exist_ok=True)

# Thread-safe counter
received_count = 0
count_lock = threading.Lock()

@app.route('/check', methods=['GET'])
def status_check():
    """GET endpoint for server status"""
    return jsonify({
        "status": "OK",
        "timestamp": datetime.utcnow().isoformat(),
        "received_requests": received_count,
        "storage_location": os.path.abspath(DATA_STORAGE_DIR)
    })

@app.route('/api/data', methods=['POST'])
def receive_data():
    """POST endpoint to receive JSON data"""
    global received_count
    
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    
    # Validate required fields (customize based on your needs)
    # print(data, data.get('id'),data.get('timestamp'))
    # if not data.get('id') or not data.get('timestamp'):
    #     return jsonify({"error": "Missing required fields"}), 400
    
    try:
        # Save received data to file
        filename = f"data_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.json"
        filepath = os.path.join(DATA_STORAGE_DIR, filename)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Update counter safely
        with count_lock:
            received_count += 1
        
        return jsonify({
            "status": "success",
            "received_count": received_count,
            "saved_as": filename
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
@app.route('/api/upload', methods=['POST'])
def upload_file():
    # Check if the request contains the file with key 'video'
    if 'video' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['video']

    # If no file was selected
    if file.filename == '':
        return jsonify({"error": "No file selected for uploading"}), 400

    # Check file validity and save it
    if file and allowed_file(file.filename):
        # Sanitize the filename to prevent directory traversal attacks
        filename = secure_filename(file.filename)
        save_path = os.path.join(DATA_STORAGE_DIR, filename)
        file.save(save_path)
        return jsonify({"message": "File successfully uploaded", "path": save_path}), 201

    return jsonify({"error": "Allowed file types are mp4"}), 400

if __name__ == '__main__':
    print(f"Starting server on {HOST}:{PORT}")
    print(f"Data storage directory: {os.path.abspath(DATA_STORAGE_DIR)}")
    app.run(host=HOST, port=PORT, threaded=True)