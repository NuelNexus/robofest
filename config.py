# config.py
import math

class Config:
    # Arduino Serial Configuration
    ARDUINO_PORT = 'COM11'  # Change to your port (e.g., '/dev/ttyUSB0' for Linux)
    ARDUINO_BAUD = 9600
    
    # Motor Pins Configuration (Update with your actual pin mappings)
    MOTOR_PINS = {
        'left_front': {'enable': 2, 'input1': 3, 'input2': 4},
        'left_mid': {'enable': 5, 'input1': 6, 'input2': 7},
        'left_rear': {'enable': 8, 'input1': 9, 'input2': 10},
        'right_front': {'enable': 11, 'input1': 12, 'input2': 13},
        'right_mid': {'enable': 14, 'input1': 15, 'input2': 16},
        'right_rear': {'enable': 17, 'input1': 18, 'input2': 19}
    }
    
    # Gemini API Configuration
    GEMINI_API_KEY = 'AIzaSyBAeu1AH6dSZXGAR_arC7azcUVBpRSA7l8'
    
    # Camera Configuration
    CAMERA_ID = 0  # Try 0, 1, or -1 for default camera
    RESOLUTION = (640, 480)
    FRAME_RATE = 15  # Reduced for stability
    
    # Camera backend override for Windows (try different ones)
    CAMERA_BACKEND = 'DIRECTSHOW'  # Options: 'MSMF', 'DIRECTSHOW', 'ANY'
    
    # Movement Parameters
    BASE_SPEED = 150  # PWM value (0-255)
    TURN_SPEED = 100
    
    # Mapping Configuration
    GRID_SIZE = 0.1  # meters per grid cell
    MAP_SIZE = (100, 100)  # grid cells
    
    # Web Server Configuration
    HOST = '0.0.0.0'
    PORT = 5000
    DEBUG = True
    THREADED = True
    
    # Simulated mode for testing (if no camera/arduino available)
    SIMULATE_CAMERA = False
    SIMULATE_ARDUINO = False