# app.py
from flask import Flask, render_template, Response, jsonify, request, send_file
from flask_cors import CORS
import time
import json
import threading
import cv2
import base64
from io import BytesIO
from PIL import Image
import numpy as np
import logging

from robot_control import RobotControl
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize robot
robot = RobotControl()

# Global variables for video streaming
streaming_active = True
camera_frame = None
frame_lock = threading.Lock()

def generate_simulated_frame():
    """Generate a simulated frame for testing"""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # Add timestamp
    timestamp = time.strftime("%H:%M:%S")
    cv2.putText(frame, f"SIMULATED - {timestamp}", (150, 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    
    # Add robot status
    status = robot.get_status()
    cv2.putText(frame, f"Pos: ({status['position'][0]:.1f}, {status['position'][1]:.1f})", 
                (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(frame, f"Heading: {status['heading']:.0f}°", 
                (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(frame, f"Speed: {status['speed']}", 
                (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    
    # Add some simulated environment
    cv2.rectangle(frame, (200, 200), (300, 300), (0, 0, 255), -1)  # Red obstacle
    cv2.circle(frame, (400, 300), 50, (0, 255, 0), -1)  # Green path
    cv2.line(frame, (320, 240), (320 + int(100 * np.cos(np.radians(status['heading']))), 
                                240 + int(100 * np.sin(np.radians(status['heading'])))), 
            (255, 255, 0), 3)  # Heading direction
    
    return frame

def camera_stream():
    """Background thread for camera streaming"""
    global camera_frame, streaming_active
    
    while streaming_active:
        try:
            # Get frame from camera navigation
            frame = robot.navigator.get_frame_with_overlay()
            
            if frame is not None:
                with frame_lock:
                    camera_frame = frame.copy()
            
            time.sleep(1 / Config.FRAME_RATE)
            
        except Exception as e:
            logger.error(f"Camera stream error: {e}")
            time.sleep(1)

def generate_frames():
    """Generate frames for video streaming"""
    global camera_frame
    
    while True:
        try:
            with frame_lock:
                if camera_frame is not None:
                    frame = camera_frame
                else:
                    frame = generate_simulated_frame()
            
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # Send a blank frame
                blank_frame = np.zeros((100, 100, 3), dtype=np.uint8)
                ret, buffer = cv2.imencode('.jpg', blank_frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
        except Exception as e:
            logger.error(f"Frame generation error: {e}")
            
        time.sleep(1 / Config.FRAME_RATE)

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    """Get robot status"""
    try:
        status = robot.get_status()
        return jsonify({
            'success': True,
            'status': status,
            'camera_available': robot.navigator.camera_available,
            'arduino_connected': robot.is_connected,
            'timestamp': time.time()
        })
    except Exception as e:
        logger.error(f"Status error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/connect', methods=['POST'])
def connect_robot():
    """Connect to Arduino"""
    try:
        if Config.SIMULATE_ARDUINO:
            robot.is_connected = True
            robot.status = "Simulated Mode"
            return jsonify({'success': True, 'message': 'Connected in simulated mode'})
        
        success = robot.connect_arduino()
        return jsonify({'success': success, 'message': robot.status})
    except Exception as e:
        logger.error(f"Connect error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_robot():
    """Disconnect from Arduino"""
    try:
        robot.disconnect()
        return jsonify({'success': True, 'message': 'Disconnected'})
    except Exception as e:
        logger.error(f"Disconnect error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/command', methods=['POST'])
def send_command():
    """Send movement command to robot"""
    try:
        data = request.json
        command = data.get('command', '')
        duration = data.get('duration', 1.0)
        speed = data.get('speed', None)
        
        if Config.SIMULATE_ARDUINO and not robot.is_connected:
            robot.is_connected = True
            robot.status = "Simulated"
        
        if command == 'forward':
            robot.move_forward(duration)
        elif command == 'backward':
            robot.move_backward(duration)
        elif command == 'left':
            robot.turn_left(duration)
        elif command == 'right':
            robot.turn_right(duration)
        elif command == 'smooth_left':
            robot.smooth_left(duration)
        elif command == 'smooth_right':
            robot.smooth_right(duration)
        elif command == 'stop':
            robot.stop()
        elif command == 'set_speed' and speed is not None:
            robot.set_speed(speed)
            return jsonify({'success': True, 'message': f'Speed set to {speed}'})
        
        return jsonify({'success': True, 'message': f'Command {command} executed'})
    except Exception as e:
        logger.error(f"Command error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/explore', methods=['POST'])
def explore():
    """Start autonomous exploration"""
    try:
        def explore_thread():
            robot.explore_room()
        
        thread = threading.Thread(target=explore_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': 'Exploration started in background'})
    except Exception as e:
        logger.error(f"Explore error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/navigate', methods=['POST'])
def navigate():
    """Navigate using AI"""
    try:
        data = request.json
        target = data.get('target', '')
        
        if not target:
            return jsonify({'success': False, 'message': 'No target specified'})
        
        def navigate_thread():
            result = robot.navigate_to_target(target)
            return result
        
        thread = threading.Thread(target=navigate_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': f'Navigating to: {target}'})
    except Exception as e:
        logger.error(f"Navigate error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/snapshot', methods=['GET'])
def get_snapshot():
    """Get a single snapshot with analysis"""
    try:
        frame = robot.navigator.capture_frame()
        
        if frame is None:
            frame = generate_simulated_frame()
        
        # Analyze frame
        analysis = robot.navigator.analyze_frame(frame)
        
        # Get frame with overlay
        overlay_frame = robot.navigator.get_frame_with_overlay(frame)
        
        # Convert to base64
        _, buffer = cv2.imencode('.jpg', overlay_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'success': True,
            'image': img_str,
            'analysis': analysis,
            'timestamp': time.time(),
            'camera_available': robot.navigator.camera_available
        })
    except Exception as e:
        logger.error(f"Snapshot error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/map', methods=['GET'])
def get_map():
    """Get current map"""
    try:
        # Try to load existing map first
        try:
            with open('robot_map.png', 'rb') as f:
                img_str = base64.b64encode(f.read()).decode('utf-8')
            map_available = True
        except:
            # Generate new map
            robot.generate_map()
            with open('robot_map.png', 'rb') as f:
                img_str = base64.b64encode(f.read()).decode('utf-8')
            map_available = True
        
        return jsonify({
            'success': True,
            'map': img_str,
            'position': robot.current_position,
            'heading': robot.current_heading,
            'map_available': map_available
        })
    except Exception as e:
        logger.error(f"Map error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/map_image')
def get_map_image():
    """Serve map image directly"""
    try:
        return send_file('robot_map.png', mimetype='image/png')
    except:
        # Return empty image
        img = Image.new('RGB', (100, 100), color='gray')
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')

@app.route('/api/movement_log', methods=['GET'])
def get_movement_log():
    """Get movement history"""
    try:
        movements = robot.recorder.get_movement_history()
        return jsonify({
            'success': True, 
            'movements': movements[-50:],  # Last 50 movements
            'total_movements': len(movements)
        })
    except Exception as e:
        logger.error(f"Movement log error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/start_stream', methods=['POST'])
def start_stream():
    """Start camera streaming"""
    global streaming_active
    streaming_active = True
    return jsonify({'success': True, 'message': 'Stream started'})

@app.route('/api/stop_stream', methods=['POST'])
def stop_stream():
    """Stop camera streaming"""
    global streaming_active
    streaming_active = False
    return jsonify({'success': True, 'message': 'Stream stopped'})

@app.route('/api/system_info', methods=['GET'])
def get_system_info():
    """Get system information"""
    try:
        info = {
            'arduino_port': Config.ARDUINO_PORT,
            'camera_resolution': Config.RESOLUTION,
            'frame_rate': Config.FRAME_RATE,
            'base_speed': Config.BASE_SPEED,
            'map_size': Config.MAP_SIZE,
            'grid_size': Config.GRID_SIZE,
            'simulate_camera': Config.SIMULATE_CAMERA,
            'simulate_arduino': Config.SIMULATE_ARDUINO,
            'camera_available': robot.navigator.camera_available,
            'arduino_connected': robot.is_connected,
            'obstacles_count': len(robot.obstacles_detected),
            'total_movements': len(robot.recorder.movements),
            'battery_level': robot.battery_level
        }
        return jsonify({'success': True, 'info': info})
    except Exception as e:
        logger.error(f"System info error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset', methods=['POST'])
def reset_system():
    """Reset robot system"""
    try:
        robot.disconnect()
        robot.recorder.clear_history()
        robot.mapper = map_generator.MapGenerator()
        robot.current_position = (0, 0)
        robot.current_heading = 0
        robot.battery_level = 100
        
        return jsonify({'success': True, 'message': 'System reset'})
    except Exception as e:
        logger.error(f"Reset error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/test_camera', methods=['GET'])
def test_camera():
    """Test camera functionality"""
    try:
        frame = robot.navigator.capture_frame()
        if frame is not None:
            return jsonify({
                'success': True,
                'message': 'Camera working',
                'frame_shape': frame.shape,
                'camera_available': True
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Camera not available',
                'camera_available': False
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Camera error: {str(e)}',
            'camera_available': False
        })

if __name__ == '__main__':
    # Start camera stream thread
    camera_thread = threading.Thread(target=camera_stream, daemon=True)
    camera_thread.start()
    
    print(f"""
    ============================================
    Robot Control Dashboard Starting...
    ============================================
    URL: http://localhost:{Config.PORT}
    
    Configuration:
    - Camera ID: {Config.CAMERA_ID}
    - Simulate Camera: {Config.SIMULATE_CAMERA}
    - Simulate Arduino: {Config.SIMULATE_ARDUINO}
    - Arduino Port: {Config.ARDUINO_PORT}
    
    If you see camera errors, try:
    1. Set SIMULATE_CAMERA = True in config.py
    2. Change CAMERA_ID to 1 or 2
    3. Check camera permissions
    ============================================
    """)
    
    app.run(
        host=Config.HOST, 
        port=Config.PORT, 
        debug=Config.DEBUG, 
        threaded=Config.THREADED,
        use_reloader=False  # Disable reloader to avoid threading issues
    )