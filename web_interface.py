# web_interface.py
from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS
import cv2
import threading
import time
import base64
import json
from io import BytesIO
from PIL import Image
import numpy as np

from config import Config
from robot_controller import RobotController

app = Flask(__name__)
CORS(app)

# Initialize robot
robot = RobotController()

# Global variables for streaming
streaming_active = True
current_frame = None
frame_lock = threading.Lock()

def camera_stream_loop():
    """Background thread for camera streaming"""
    global current_frame, streaming_active
    
    while streaming_active:
        try:
            frame = robot.get_camera_frame(with_overlay=True)
            
            if frame is not None:
                with frame_lock:
                    current_frame = frame.copy()
            
            time.sleep(1 / Config.FRAME_RATE)
            
        except Exception as e:
            print(f"Stream error: {e}")
            time.sleep(0.5)

def generate_frames():
    """Generate video frames for streaming"""
    global current_frame
    
    while True:
        try:
            with frame_lock:
                if current_frame is not None:
                    frame = current_frame
                else:
                    # Create placeholder frame
                    frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(frame, "NO CAMERA FEED", (150, 240), 
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            
            # Encode as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
        except Exception as e:
            print(f"Frame generation error: {e}")
            time.sleep(0.1)

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming endpoint"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    """Get robot status"""
    try:
        status = robot.get_status()
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/connect', methods=['POST'])
def connect():
    """Connect to robot hardware"""
    try:
        success = robot.connect_arduino()
        return jsonify({'success': success, 'message': 'Connected' if success else 'Failed to connect'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/control', methods=['POST'])
def control():
    """Send control command"""
    try:
        data = request.json
        command = data.get('command')
        duration = data.get('duration', 1.0)
        
        if not command:
            return jsonify({'success': False, 'error': 'No command specified'})
        
        success = robot.manual_control(command, duration)
        return jsonify({'success': success, 'message': f'Command {command} executed'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/explore', methods=['POST'])
def explore():
    """Start autonomous exploration"""
    try:
        success = robot.autonomous_navigation()
        return jsonify({'success': success, 'message': 'Exploration started'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/map')
def get_map():
    """Get exploration map data"""
    try:
        map_data = robot.get_map_data()
        return jsonify({'success': True, 'data': map_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/snapshot')
def snapshot():
    """Get single snapshot with analysis"""
    try:
        frame = robot.get_camera_frame(with_overlay=True)
        
        if frame is None:
            return jsonify({'success': False, 'error': 'No camera feed'})
        
        # Encode as base64
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        # Get current analysis
        env = robot.navigator.check_environment()
        
        return jsonify({
            'success': True,
            'image': img_str,
            'analysis': env,
            'timestamp': time.time()
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/camera_info')
def camera_info():
    """Get camera information"""
    try:
        cameras = robot.camera.available_cameras
        camera_list = []
        
        for cam in cameras:
            camera_list.append({
                'index': cam['index'],
                'type': cam['type'].value,
                'backend': cam['backend'],
                'resolution': cam['resolution']
            })
        
        return jsonify({
            'success': True,
            'current_camera': robot.camera.camera_index,
            'current_type': robot.camera.camera_type.value,
            'available_cameras': camera_list
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/switch_camera', methods=['POST'])
def switch_camera():
    """Switch to different camera"""
    try:
        data = request.json
        camera_index = data.get('index', 0)
        
        # This would require reinitialization
        # For now, return info about current camera
        return jsonify({
            'success': True,
            'message': f'Camera switching not implemented in this version. Current camera: {robot.camera.camera_index}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/emergency_stop', methods=['POST'])
def emergency_stop():
    """Emergency stop"""
    try:
        robot.emergency_stop = True
        robot.send_command('STOP')
        return jsonify({'success': True, 'message': 'Emergency stop activated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset_emergency', methods=['POST'])
def reset_emergency():
    """Reset emergency stop"""
    try:
        robot.emergency_stop = False
        return jsonify({'success': True, 'message': 'Emergency stop reset'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """Shutdown robot"""
    try:
        robot.shutdown()
        return jsonify({'success': True, 'message': 'Robot shutdown initiated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/logs')
def get_logs():
    """Get movement logs"""
    try:
        # This would query the database
        return jsonify({
            'success': True,
            'message': 'Log retrieval not fully implemented in this version'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # Start camera streaming thread
    stream_thread = threading.Thread(target=camera_stream_loop, daemon=True)
    stream_thread.start()
    
    print(f"""
    ============================================
    Advanced Robot Navigation System
    ============================================
    Web Interface: http://localhost:{Config.PORT}
    
    Features:
    - Distance calculation (stops at 10cm)
    - Obstacle avoidance with memory
    - Path tracking with database
    - Multi-camera support (USB prioritized)
    - Autonomous exploration
    - Real-time mapping
    
    Camera Status: {robot.camera.camera_type.value}
    Database: {Config.DATABASE_FILE}
    ============================================
    """)
    
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True, use_reloader=False)