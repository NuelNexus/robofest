# camera_manager.py
import cv2
import numpy as np
import threading
import time
from enum import Enum
from config import Config

class CameraType(Enum):
    INTERNAL = "internal"
    USB = "usb"
    SIMULATED = "simulated"

class CameraManager:
    def __init__(self):
        self.camera = None
        self.camera_type = None
        self.camera_index = -1
        self.frame_lock = threading.Lock()
        self.current_frame = None
        self.running = False
        self.camera_thread = None
        self.available_cameras = []
        
        self.initialize_camera()
    
    def scan_cameras(self):
        """Scan for available cameras and identify USB vs Internal"""
        available = []
        
        # Try indices 0-10
        for idx in Config.CAMERA_INDICES:
            for backend in Config.CAMERA_BACKENDS:
                try:
                    cap = cv2.VideoCapture(idx, self._get_backend_code(backend))
                    if cap.isOpened():
                        # Try to get camera properties to identify type
                        backend_name = str(cap.getBackendName())
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        
                        # Guess camera type based on backend and properties
                        camera_type = self._guess_camera_type(idx, backend_name)
                        
                        available.append({
                            'index': idx,
                            'backend': backend,
                            'type': camera_type,
                            'resolution': (width, height),
                            'cap': cap
                        })
                        
                        cap.release()
                except:
                    pass
        
        return available
    
    def _get_backend_code(self, backend_name):
        """Convert backend name to OpenCV code"""
        backends = {
            'DSHOW': cv2.CAP_DSHOW,
            'MSMF': cv2.CAP_MSMF,
            'V4L2': cv2.CAP_V4L2,
            'ANY': cv2.CAP_ANY
        }
        return backends.get(backend_name, cv2.CAP_ANY)
    
    def _guess_camera_type(self, index, backend_name):
        """Guess if camera is USB or internal"""
        # Windows: DSHOW often means USB, MSMF often means internal
        # Linux: V4L2 could be either
        if "DSHOW" in backend_name.upper() or index > 0:
            return CameraType.USB
        elif "MSMF" in backend_name.upper() and index == 0:
            return CameraType.INTERNAL
        else:
            # Default assumption
            return CameraType.USB if index > 0 else CameraType.INTERNAL
    
    def select_best_camera(self, available_cameras):
        """Select the best camera based on preferences"""
        if not available_cameras:
            return None
        
        # Sort by preference: USB > Internal > others
        if Config.PREFER_USB_CAMERA:
            usb_cams = [c for c in available_cameras if c['type'] == CameraType.USB]
            if usb_cams:
                return usb_cams[0]  # First USB camera
        
        # Return first available camera
        return available_cameras[0]
    
    def initialize_camera(self):
        """Initialize the best available camera"""
        if Config.SIMULATE_HARDWARE:
            print("Using simulated camera")
            self.camera_type = CameraType.SIMULATED
            self._start_simulated_camera()
            return
        
        print("Scanning for available cameras...")
        self.available_cameras = self.scan_cameras()
        
        if not self.available_cameras:
            print("No cameras found, using simulated camera")
            self.camera_type = CameraType.SIMULATED
            self._start_simulated_camera()
            return
        
        print(f"Found {len(self.available_cameras)} camera(s):")
        for cam in self.available_cameras:
            print(f"  Index {cam['index']}: {cam['type'].value} ({cam['backend']})")
        
        selected = self.select_best_camera(self.available_cameras)
        
        if selected:
            print(f"Selected camera {selected['index']} ({selected['type'].value})")
            self.camera_index = selected['index']
            self.camera_type = selected['type']
            self._initialize_physical_camera(selected['index'], selected['backend'])
        else:
            print("Failed to select camera, using simulated")
            self.camera_type = CameraType.SIMULATED
            self._start_simulated_camera()
    
    def _initialize_physical_camera(self, index, backend):
        """Initialize physical camera"""
        try:
            self.camera = cv2.VideoCapture(index, self._get_backend_code(backend))
            
            if not self.camera.isOpened():
                raise Exception(f"Failed to open camera {index}")
            
            # Set camera properties
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, Config.RESOLUTION[0])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.RESOLUTION[1])
            self.camera.set(cv2.CAP_PROP_FPS, Config.FRAME_RATE)
            
            # Test capture
            ret, test_frame = self.camera.read()
            if not ret:
                raise Exception("Failed to capture test frame")
            
            print(f"Camera {index} initialized successfully")
            self._start_camera_thread()
            
        except Exception as e:
            print(f"Camera initialization error: {e}")
            self.camera_type = CameraType.SIMULATED
            self._start_simulated_camera()
    
    def _start_simulated_camera(self):
        """Start simulated camera thread"""
        self.running = True
        self.camera_thread = threading.Thread(target=self._simulated_camera_loop, daemon=True)
        self.camera_thread.start()
    
    def _start_camera_thread(self):
        """Start camera capture thread"""
        self.running = True
        self.camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self.camera_thread.start()
    
    def _camera_loop(self):
        """Camera capture loop for physical camera"""
        while self.running and self.camera and self.camera.isOpened():
            try:
                ret, frame = self.camera.read()
                if ret:
                    with self.frame_lock:
                        self.current_frame = frame.copy()
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"Camera error: {e}")
                time.sleep(0.1)
    
    def _simulated_camera_loop(self):
        """Simulated camera with obstacles"""
        while self.running:
            frame = np.zeros((Config.RESOLUTION[1], Config.RESOLUTION[0], 3), dtype=np.uint8)
            
            # Draw grid
            for i in range(0, frame.shape[1], 50):
                cv2.line(frame, (i, 0), (i, frame.shape[0]), (50, 50, 50), 1)
            for i in range(0, frame.shape[0], 50):
                cv2.line(frame, (0, i), (frame.shape[1], i), (50, 50, 50), 1)
            
            # Add simulated obstacles
            if Config.SIMULATE_OBSTACLES:
                # Random obstacles that change over time
                t = time.time()
                obstacle_x = int(320 + 100 * np.sin(t))
                obstacle_y = 240
                obstacle_size = 30 + int(20 * np.sin(t * 0.5))
                
                cv2.circle(frame, (obstacle_x, obstacle_y), obstacle_size, (0, 0, 255), -1)
                cv2.putText(frame, f"OBSTACLE", (obstacle_x-40, obstacle_y-40), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Add info overlay
            cv2.putText(frame, f"SIMULATED CAMERA - {self.camera_type.value.upper()}", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Time: {time.strftime('%H:%M:%S')}", 
                       (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            with self.frame_lock:
                self.current_frame = frame
            
            time.sleep(1 / Config.FRAME_RATE)
    
    def capture_frame(self):
        """Capture current frame"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        
        # Return black frame if no camera
        return np.zeros((Config.RESOLUTION[1], Config.RESOLUTION[0], 3), dtype=np.uint8)
    
    def calculate_distance(self, frame):
        """Calculate distance to nearest object using monocular vision"""
        if frame is None or frame.size == 0:
            return float('inf'), None
        
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Apply edge detection
        edges = cv2.Canny(gray, 50, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return float('inf'), None
        
        # Find largest contour (likely closest object)
        largest_contour = max(contours, key=cv2.contourArea)
        
        # Get bounding box
        x, y, w, h = cv2.boundingRect(largest_contour)
        
        # Calculate distance using visual size (simplified)
        # Based on the principle: farther objects appear smaller
        image_width = frame.shape[1]
        
        # Calculate apparent size ratio
        size_ratio = w / image_width
        
        # Calculate approximate distance (in cm)
        # This is a simplified calculation - would need calibration for real use
        if size_ratio > 0:
            distance = (Config.KNOWN_OBJECT_WIDTH * Config.FOCAL_LENGTH) / (w * 0.1)
            distance = max(5, min(500, distance))  # Clamp to reasonable range
        else:
            distance = float('inf')
        
        # Calculate direction (left/center/right)
        center_x = x + w // 2
        frame_center = frame.shape[1] // 2
        frame_third = frame.shape[1] // 3
        
        if center_x < frame_third:
            direction = "left"
        elif center_x > 2 * frame_third:
            direction = "right"
        else:
            direction = "center"
        
        return distance, direction
    
    def analyze_frame_for_navigation(self, frame):
        """Analyze frame for navigation decisions"""
        if frame is None:
            return {
                'safe_to_move': False,
                'closest_distance': float('inf'),
                'closest_direction': None,
                'left_distance': float('inf'),
                'center_distance': float('inf'),
                'right_distance': float('inf'),
                'recommended_action': 'STOP'
            }
        
        # Split frame into left, center, right sections
        height, width = frame.shape[:2]
        section_width = width // 3
        
        sections = {
            'left': frame[:, :section_width],
            'center': frame[:, section_width:2*section_width],
            'right': frame[:, 2*section_width:]
        }
        
        results = {}
        
        # Calculate distance for each section
        for section_name, section_frame in sections.items():
            distance, _ = self.calculate_distance(section_frame)
            results[f'{section_name}_distance'] = distance
        
        # Find closest distance and direction
        closest_distance = min(results['left_distance'], 
                              results['center_distance'], 
                              results['right_distance'])
        
        # Determine which direction has closest object
        if closest_distance == results['left_distance']:
            closest_direction = 'left'
        elif closest_distance == results['center_distance']:
            closest_direction = 'center'
        else:
            closest_direction = 'right'
        
        # Determine if safe to move
        safe_to_move = closest_distance > Config.SAFE_DISTANCE
        
        # Recommend action
        if closest_distance <= Config.MIN_DISTANCE_THRESHOLD:
            recommended_action = 'STOP'
        elif closest_direction == 'center':
            if results['left_distance'] > results['right_distance']:
                recommended_action = 'TURN_LEFT'
            else:
                recommended_action = 'TURN_RIGHT'
        elif closest_direction == 'left':
            recommended_action = 'TURN_RIGHT'
        else:  # right
            recommended_action = 'TURN_LEFT'
        
        return {
            'safe_to_move': safe_to_move,
            'closest_distance': closest_distance,
            'closest_direction': closest_direction,
            'left_distance': results['left_distance'],
            'center_distance': results['center_distance'],
            'right_distance': results['right_distance'],
            'recommended_action': recommended_action
        }
    
    def get_frame_with_overlay(self, analysis=None):
        """Get frame with distance overlay"""
        frame = self.capture_frame()
        
        if frame is None:
            return None
        
        overlay = frame.copy()
        
        # Draw section dividers
        height, width = overlay.shape[:2]
        section_width = width // 3
        
        cv2.line(overlay, (section_width, 0), (section_width, height), (0, 255, 255), 2)
        cv2.line(overlay, (2*section_width, 0), (2*section_width, height), (0, 255, 255), 2)
        
        # Draw distance information
        if analysis:
            distances = [
                ("LEFT", analysis['left_distance'], 10),
                ("CENTER", analysis['center_distance'], section_width + 10),
                ("RIGHT", analysis['right_distance'], 2*section_width + 10)
            ]
            
            for label, distance, x_pos in distances:
                color = (0, 255, 0) if distance > Config.SAFE_DISTANCE else (0, 0, 255)
                text = f"{label}: {distance:.1f}cm"
                if distance <= Config.MIN_DISTANCE_THRESHOLD:
                    text += " (STOP!)"
                
                cv2.putText(overlay, text, (x_pos, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # Draw closest object warning
            if analysis['closest_distance'] <= Config.MIN_DISTANCE_THRESHOLD:
                cv2.putText(overlay, "OBJECT TOO CLOSE!", (width//2 - 100, height//2), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
        
        # Add camera info
        camera_info = f"Camera: {self.camera_type.value} (Index: {self.camera_index})"
        cv2.putText(overlay, camera_info, (10, height - 20), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        
        return overlay
    
    def release(self):
        """Release camera resources"""
        self.running = False
        
        if self.camera_thread:
            self.camera_thread.join(timeout=1.0)
        
        if self.camera:
            self.camera.release()
            self.camera = None