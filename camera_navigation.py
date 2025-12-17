# camera_navigation.py
import cv2
import numpy as np
import google.generativeai as genai
import base64
from PIL import Image
import io
import time
import threading
from config import Config

class CameraNavigation:
    def __init__(self):
        # Initialize Gemini AI
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-pro-vision')
        
        # Initialize camera with error handling
        self.cap = None
        self.camera_available = False
        self.frame_lock = threading.Lock()
        self.current_frame = None
        self.camera_thread = None
        self.running = False
        
        self.initialize_camera()
        
    def initialize_camera(self):
        """Initialize camera with different backends"""
        if Config.SIMULATE_CAMERA:
            print("Camera: Simulated mode")
            self.camera_available = True
            self.current_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(self.current_frame, "SIMULATED CAMERA", (100, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            return
        
        try:
            # Try different camera backends
            backends = [
                cv2.CAP_DSHOW,  # DirectShow (usually works on Windows)
                cv2.CAP_MSMF,   # Microsoft Media Foundation
                cv2.CAP_ANY     # Auto-detect
            ]
            
            for backend in backends:
                try:
                    print(f"Trying camera backend: {backend}")
                    self.cap = cv2.VideoCapture(Config.CAMERA_ID, backend)
                    
                    if self.cap.isOpened():
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.RESOLUTION[0])
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.RESOLUTION[1])
                        self.cap.set(cv2.CAP_PROP_FPS, Config.FRAME_RATE)
                        
                        # Test capture
                        ret, test_frame = self.cap.read()
                        if ret:
                            print(f"Camera initialized successfully with backend {backend}")
                            self.camera_available = True
                            self.start_camera_thread()
                            return
                        else:
                            self.cap.release()
                except Exception as e:
                    print(f"Backend {backend} failed: {e}")
                    if self.cap:
                        self.cap.release()
            
            # If no backend works, create simulated camera
            print("No physical camera found, using simulated camera")
            self.camera_available = True
            self.current_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(self.current_frame, "SIMULATED CAMERA FEED", 
                       (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            
        except Exception as e:
            print(f"Camera initialization error: {e}")
            self.camera_available = False
    
    def start_camera_thread(self):
        """Start background thread for camera capture"""
        self.running = True
        self.camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self.camera_thread.start()
    
    def _camera_loop(self):
        """Background thread to continuously capture frames"""
        while self.running and self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if ret:
                    with self.frame_lock:
                        self.current_frame = frame.copy()
                else:
                    # Try to reinitialize camera
                    time.sleep(0.1)
                    if not self.cap.isOpened():
                        self.initialize_camera()
            except Exception as e:
                print(f"Camera capture error: {e}")
                time.sleep(0.1)
    
    def capture_frame(self):
        """Capture a frame from the camera"""
        if Config.SIMULATE_CAMERA:
            # Generate simulated frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, f"SIMULATED FRAME - Time: {time.time()}", 
                       (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Add some simulated obstacles
            cv2.rectangle(frame, (200, 200), (300, 300), (0, 0, 255), -1)  # Red obstacle
            cv2.circle(frame, (400, 300), 50, (0, 255, 0), -1)  # Green path
            
            return frame
        
        if not self.camera_available:
            return None
        
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        
        return None
    
    def preprocess_frame(self, frame):
        """Preprocess frame for analysis"""
        if frame is None:
            return None
        
        # Resize
        frame = cv2.resize(frame, (320, 240))
        
        # Convert to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        return frame_rgb
    
    def analyze_frame(self, frame):
        """Analyze frame for obstacles and navigation"""
        if frame is None:
            return {
                'left_obstacle': False,
                'center_obstacle': False,
                'right_obstacle': False,
                'error': 'No frame available'
            }
        
        try:
            # Edge detection for obstacle detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(gray, 30, 100)
            
            # Check for obstacles in the path
            height, width = edges.shape
            
            # Focus on lower half of image (path ahead)
            lower_half = height // 2
            middle_section = edges[lower_half:, :]
            
            # Split into left, center, and right sections
            section_width = width // 3
            left_section = middle_section[:, :section_width]
            center_section = middle_section[:, section_width:2*section_width]
            right_section = middle_section[:, 2*section_width:]
            
            # Calculate edge density
            left_density = np.sum(left_section) / left_section.size
            center_density = np.sum(center_section) / center_section.size
            right_density = np.sum(right_section) / right_section.size
            
            # Threshold for obstacle detection
            threshold = 0.05
            
            return {
                'left_obstacle': left_density > threshold,
                'center_obstacle': center_density > threshold,
                'right_obstacle': right_density > threshold,
                'left_density': float(left_density),
                'center_density': float(center_density),
                'right_density': float(right_density)
            }
        except Exception as e:
            return {
                'left_obstacle': False,
                'center_obstacle': False,
                'right_obstacle': False,
                'error': str(e)
            }
    
    def get_navigation_instruction(self, target_description, frame=None):
        """Get navigation instruction from Gemini AI"""
        if frame is None:
            frame = self.capture_frame()
            if frame is None:
                return "Cannot capture image from camera"
        
        # Preprocess frame
        processed_frame = self.preprocess_frame(frame)
        
        if processed_frame is None:
            return "Failed to process camera image"
        
        # Convert to PIL Image
        pil_image = Image.fromarray(processed_frame)
        
        # Prepare prompt
        prompt = f"""
        You are a robot navigation assistant. Analyze this image from a robot's perspective.
        
        The robot needs to: {target_description}
        
        Provide a single, clear navigation command. Choose from:
        - MOVE_FORWARD: Move forward carefully
        - TURN_LEFT: Turn left
        - TURN_RIGHT: Turn right
        - MOVE_BACKWARD: Move backward
        - STOP: Stop immediately
        
        Format your response as: COMMAND: [command] | REASON: [brief explanation]
        
        Example: COMMAND: MOVE_FORWARD | REASON: Clear path ahead visible in the center of the image.
        """
        
        try:
            # Get response from Gemini
            response = self.model.generate_content([prompt, pil_image])
            return response.text
        except Exception as e:
            return f"AI Navigation Error: {e}"
    
    def detect_path(self, frame):
        """Simple path detection using color thresholding"""
        if frame is None:
            return "No frame available"
        
        try:
            # Convert to HSV
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            
            # Define range for path color (adjust based on your environment)
            # This detects bright areas (potential path)
            lower_bound = np.array([0, 0, 100])
            upper_bound = np.array([180, 50, 255])
            
            # Create mask
            mask = cv2.inRange(hsv, lower_bound, upper_bound)
            
            # Apply morphology to clean up
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                # Find largest contour
                largest_contour = max(contours, key=cv2.contourArea)
                
                # Get center of contour
                M = cv2.moments(largest_contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    # Determine direction based on contour position
                    width = frame.shape[1]
                    if cx < width * 0.4:
                        return "Turn left to follow path"
                    elif cx > width * 0.6:
                        return "Turn right to follow path"
                    else:
                        return "Move forward on path"
            
            return "No clear path detected"
        except Exception as e:
            return f"Path detection error: {e}"
    
    def get_frame_with_overlay(self, frame=None):
        """Get frame with analysis overlay"""
        if frame is None:
            frame = self.capture_frame()
        
        if frame is None:
            # Create error frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "NO CAMERA FEED", (150, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
            return frame
        
        # Create a copy for overlay
        overlay = frame.copy()
        
        try:
            # Get analysis
            analysis = self.analyze_frame(frame)
            
            # Draw sections
            height, width = frame.shape[:2]
            lower_half = height // 2
            
            # Draw grid lines
            cv2.line(overlay, (width//3, lower_half), (width//3, height), (0, 255, 255), 2)
            cv2.line(overlay, (2*width//3, lower_half), (2*width//3, height), (0, 255, 255), 2)
            cv2.line(overlay, (0, lower_half), (width, lower_half), (0, 255, 255), 2)
            
            # Color sections based on obstacle detection
            colors = {
                'left': (0, 0, 255) if analysis.get('left_obstacle', False) else (0, 255, 0),
                'center': (0, 0, 255) if analysis.get('center_obstacle', False) else (0, 255, 0),
                'right': (0, 0, 255) if analysis.get('right_obstacle', False) else (0, 255, 0)
            }
            
            # Draw section backgrounds with transparency
            alpha = 0.3
            overlay[lower_half:, :width//3] = cv2.addWeighted(
                overlay[lower_half:, :width//3], 1 - alpha,
                np.full((height - lower_half, width//3, 3), colors['left']), alpha, 0
            )
            
            overlay[lower_half:, width//3:2*width//3] = cv2.addWeighted(
                overlay[lower_half:, width//3:2*width//3], 1 - alpha,
                np.full((height - lower_half, width//3, 3), colors['center']), alpha, 0
            )
            
            overlay[lower_half:, 2*width//3:] = cv2.addWeighted(
                overlay[lower_half:, 2*width//3:], 1 - alpha,
                np.full((height - lower_half, width - 2*width//3, 3), colors['right']), alpha, 0
            )
            
            # Add text
            cv2.putText(overlay, f"L: {analysis.get('left_density', 0):.3f}", 
                       (10, lower_half + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(overlay, f"C: {analysis.get('center_density', 0):.3f}", 
                       (width//3 + 10, lower_half + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(overlay, f"R: {analysis.get('right_density', 0):.3f}", 
                       (2*width//3 + 10, lower_half + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Add timestamp
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(overlay, timestamp, (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
        except Exception as e:
            cv2.putText(overlay, f"Analysis error: {str(e)[:30]}", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        return overlay
    
    def release(self):
        """Release camera resources"""
        self.running = False
        if self.camera_thread:
            self.camera_thread.join(timeout=1.0)
        
        if self.cap:
            self.cap.release()
            self.cap = None