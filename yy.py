from flask import Flask, render_template_string, request, jsonify
import base64
import requests
import json
import sqlite3
import hashlib
import time
from datetime import datetime
import os
import serial
import serial.tools.list_ports
import threading

app = Flask(__name__)

# Gemini API Configuration
GEMINI_API_KEY = "AIzaSyAJlks4m99i2fgBhFWG4iCft1ij_QdcaHc"
SELECTED_MODEL = "gemini-2.0-flash"  # Fast and free
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1/models/{SELECTED_MODEL}:generateContent"

# Database setup
DB_PATH = "lily_memory.db"

# Serial Configuration for Microcontroller
SERIAL_PORT = None  # Will auto-detect
BAUD_RATE = 115200
serial_connection = None
serial_lock = threading.Lock()
latest_esp32_image = None  # Store latest ESP32-CAM image

def find_arduino_port():
    """Auto-detect Arduino/ESP32 port"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        # Look for common Arduino/ESP32 identifiers
        if 'USB' in port.device or 'ACM' in port.device or 'SERIAL' in port.device.upper():
            print(f"Found potential Arduino/ESP32 on: {port.device}")
            return port.device
    return None

def init_serial():
    """Initialize serial connection to microcontroller"""
    global serial_connection, SERIAL_PORT
    try:
        if SERIAL_PORT is None:
            SERIAL_PORT = find_arduino_port()
        
        if SERIAL_PORT:
            serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
            time.sleep(2)  # Wait for connection to stabilize
            print(f"✅ Serial connection established on {SERIAL_PORT} at {BAUD_RATE} baud")
            return True
        else:
            print("❌ No Arduino/ESP32 found. Please check connection.")
            return False
    except Exception as e:
        print(f"❌ Serial initialization error: {e}")
        return False

def send_serial_command(command):
    """Send command to microcontroller and get response"""
    global serial_connection
    
    with serial_lock:
        try:
            if serial_connection is None or not serial_connection.is_open:
                if not init_serial():
                    return None
            
            # Clear any existing data in buffer
            serial_connection.reset_input_buffer()
            
            # Send command
            serial_connection.write(f"{command}\n".encode())
            print(f"📤 Sent command: {command}")
            
            # Wait for response
            time.sleep(0.5)
            
            # Read response
            response = ""
            while serial_connection.in_waiting > 0:
                line = serial_connection.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    response += line + " "
            
            print(f"📥 Received: {response}")
            return response.strip() if response else None
            
        except Exception as e:
            print(f"❌ Serial communication error: {e}")
            serial_connection = None
            return None

def get_esp32_image():
    """Request image from ESP32-CAM"""
    global latest_esp32_image
    try:
        response = send_serial_command("GET_IMAGE")
        if response and response.startswith("IMAGE:"):
            # Extract base64 image data
            image_data = response.split("IMAGE:", 1)[1]
            latest_esp32_image = image_data
            return image_data
        return None
    except Exception as e:
        print(f"❌ ESP32-CAM image error: {e}")
        return None

def parse_sensor_command(text):
    """Parse user input to determine which sensor command to send"""
    text_lower = text.lower()
    
    # Sensor command mappings
    sensor_commands = {
        'temperature': ('GET_TEMP', 'temperature'),
        'temp': ('GET_TEMP', 'temperature'),
        'humidity': ('GET_HUMIDITY', 'humidity'),
        'humid': ('GET_HUMIDITY', 'humidity'),
        'distance': ('GET_DISTANCE', 'distance'),
        'ultrasonic': ('GET_DISTANCE', 'distance'),
        'soil': ('GET_SOIL', 'soil moisture'),
        'moisture': ('GET_SOIL', 'soil moisture'),
        'gas': ('GET_GAS', 'gas level'),
        'air quality': ('GET_GAS', 'air quality'),
        'light': ('GET_LIGHT', 'light level'),
        'ph': ('GET_PH', 'pH level'),
        'all sensors': ('GET_ALL', 'all sensor data'),
        'status': ('GET_STATUS', 'system status'),
    }
    
    for keyword, (command, sensor_name) in sensor_commands.items():
        if keyword in text_lower:
            return command, sensor_name
    
    return None, None

def check_for_camera_request(text):
    """Check if user wants to see ESP32-CAM feed"""
    camera_keywords = ['see your eyes', 'show your eyes', 'camera', 'cam', 'what do you see', 'your vision', 'show me what you see']
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in camera_keywords)

def init_database():
    """Initialize SQLite database for storing memories"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_hash TEXT UNIQUE,
            first_seen TIMESTAMP,
            last_seen TIMESTAMP,
            visit_count INTEGER DEFAULT 1,
            is_creator BOOLEAN DEFAULT 0,
            face_signature TEXT,
            voice_signature TEXT
        )
    ''')
    
    # Conversations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_hash TEXT,
            message TEXT,
            response TEXT,
            timestamp TIMESTAMP,
            message_type TEXT,
            FOREIGN KEY (user_hash) REFERENCES users(user_hash)
        )
    ''')
    
    # Faces table for face recognition
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_hash TEXT,
            face_encoding TEXT,
            timestamp TIMESTAMP,
            FOREIGN KEY (user_hash) REFERENCES users(user_hash)
        )
    ''')
    
    # Objects table for object detection
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_name TEXT,
            confidence REAL,
            position_x REAL,
            position_y REAL,
            position_width REAL,
            position_height REAL,
            first_seen TIMESTAMP,
            last_seen TIMESTAMP,
            times_seen INTEGER DEFAULT 1,
            user_hash TEXT,
            FOREIGN KEY (user_hash) REFERENCES users(user_hash)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_database()

def generate_user_hash(face_sig=None, voice_sig=None):
    """Generate a unique hash for user identification"""
    identifier = f"{face_sig or ''}{voice_sig or ''}"
    return hashlib.sha256(identifier.encode()).hexdigest()[:16]

def find_user_by_signature(face_sig=None, voice_sig=None):
    """Find existing user by face or voice signature"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if face_sig:
        cursor.execute('SELECT user_hash FROM users WHERE face_signature = ?', (face_sig,))
        result = cursor.fetchone()
        if result:
            conn.close()
            return result[0]
    
    if voice_sig:
        cursor.execute('SELECT user_hash FROM users WHERE voice_signature = ?', (voice_sig,))
        result = cursor.fetchone()
        if result:
            conn.close()
            return result[0]
    
    conn.close()
    return None

def store_user(user_hash, face_sig=None, voice_sig=None, is_creator=False):
    """Store or update user in database with machine learning-like pattern recognition"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO users (user_hash, first_seen, last_seen, face_signature, voice_signature, is_creator)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_hash) DO UPDATE SET
            last_seen = ?,
            visit_count = visit_count + 1,
            face_signature = COALESCE(?, face_signature),
            voice_signature = COALESCE(?, voice_signature),
            is_creator = ?
    ''', (user_hash, datetime.now(), datetime.now(), face_sig, voice_sig, is_creator, 
          datetime.now(), face_sig, voice_sig, is_creator))
    
    conn.commit()
    conn.close()

def get_user_info(user_hash):
    """Retrieve user information from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_hash, first_seen, last_seen, visit_count, is_creator
        FROM users WHERE user_hash = ?
    ''', (user_hash,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'user_hash': result[0],
            'first_seen': result[1],
            'last_seen': result[2],
            'visit_count': result[3],
            'is_creator': bool(result[4])
        }
    return None

def store_conversation(user_hash, message, response, message_type='text'):
    """Store conversation in database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO conversations (user_hash, message, response, timestamp, message_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_hash, message, response, datetime.now(), message_type))
    
    conn.commit()
    conn.close()

def get_user_history(user_hash, limit=5):
    """Get recent conversation history for a user"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT message, response, timestamp
        FROM conversations
        WHERE user_hash = ?
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (user_hash, limit))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{'message': r[0], 'response': r[1], 'timestamp': r[2]} for r in results]

def store_detected_object(object_name, confidence, position, user_hash=None):
    """Store or update detected object in database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if object exists
    cursor.execute('''
        SELECT id, times_seen FROM objects 
        WHERE object_name = ? AND user_hash = ?
    ''', (object_name, user_hash))
    
    existing = cursor.fetchone()
    
    if existing:
        # Update existing object
        cursor.execute('''
            UPDATE objects 
            SET times_seen = times_seen + 1,
                last_seen = ?,
                confidence = ?,
                position_x = ?,
                position_y = ?,
                position_width = ?,
                position_height = ?
            WHERE id = ?
        ''', (datetime.now(), confidence, position['x'], position['y'], 
              position['width'], position['height'], existing[0]))
    else:
        # Insert new object
        cursor.execute('''
            INSERT INTO objects 
            (object_name, confidence, position_x, position_y, position_width, position_height,
             first_seen, last_seen, times_seen, user_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ''', (object_name, confidence, position['x'], position['y'], 
              position['width'], position['height'], datetime.now(), datetime.now(), user_hash))
    
    conn.commit()
    conn.close()

def get_detected_objects(user_hash=None, limit=10):
    """Get detected objects from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if user_hash:
        cursor.execute('''
            SELECT object_name, confidence, position_x, position_y, position_width, position_height,
                   first_seen, last_seen, times_seen
            FROM objects
            WHERE user_hash = ?
            ORDER BY last_seen DESC
            LIMIT ?
        ''', (user_hash, limit))
    else:
        cursor.execute('''
            SELECT object_name, confidence, position_x, position_y, position_width, position_height,
                   first_seen, last_seen, times_seen
            FROM objects
            ORDER BY last_seen DESC
            LIMIT ?
        ''', (limit,))
    
    results = cursor.fetchall()
    conn.close()
    
    return [{
        'name': r[0],
        'confidence': r[1],
        'position': {'x': r[2], 'y': r[3], 'width': r[4], 'height': r[5]},
        'first_seen': r[6],
        'last_seen': r[7],
        'times_seen': r[8]
    } for r in results]

def call_gemini_api(prompt, image_data=None):
    """Call Gemini API with the gemini-1.5-flash model - FIXED VERSION"""
    try:
        headers = {
            "Content-Type": "application/json",
        }
        
        # Build the request payload
        if image_data:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',', 1)[1]
            
            contents = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": image_data
                                }
                            }
                        ]
                    }
                ]
            }
        else:
            contents = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            }
        
        # Add generation config
        contents["generationConfig"] = {
            "temperature": 0.7,
            "maxOutputTokens": 200,
        }
        
        # Make the API request with API key as query parameter
        response = requests.post(
            f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
            headers=headers,
            json=contents,
            timeout=30
        )
        
        # Debug output
        print(f"\n{'='*60}")
        print(f"API Status Code: {response.status_code}")
        print(f"Full Response: {response.text}")
        print(f"{'='*60}\n")
        
        if response.status_code == 200:
            response_data = response.json()
            
            # Debug: Print the entire response structure
            print(f"Response Data Keys: {response_data.keys()}")
            
            # Check for candidates in response
            if 'candidates' in response_data and len(response_data['candidates']) > 0:
                candidate = response_data['candidates'][0]
                print(f"Candidate Keys: {candidate.keys()}")
                
                # Check if content exists
                if 'content' in candidate:
                    content = candidate['content']
                    print(f"Content: {content}")
                    
                    if 'parts' in content and len(content['parts']) > 0:
                        parts = content['parts']
                        print(f"Parts: {parts}")
                        
                        if 'text' in parts[0]:
                            text_response = parts[0]['text'].strip()
                            print(f"✅ Successfully extracted text: {text_response[:100]}...")
                            return text_response
                
                # Check for safety blocking
                if 'finishReason' in candidate:
                    finish_reason = candidate['finishReason']
                    print(f"Finish Reason: {finish_reason}")
                    
                    if finish_reason == 'SAFETY':
                        return "I can't respond to that due to safety filters. Try rephrasing! 😊"
                    elif finish_reason == 'RECITATION':
                        return "That response was blocked. Let's try something else! 😊"
                    elif finish_reason == 'MAX_TOKENS':
                        # Try to get partial response
                        if 'content' in candidate and 'parts' in candidate['content']:
                            parts = candidate['content']['parts']
                            if parts and 'text' in parts[0]:
                                return parts[0]['text'].strip()
            
            # Check for error in response
            if 'error' in response_data:
                error_msg = response_data['error'].get('message', 'Unknown error')
                print(f"❌ API Error: {error_msg}")
                return f"API Error: {error_msg}"
            
            print("❌ Could not find text in response structure")
            return "I'm having trouble processing the response. Let's try again! 😊"
        
        elif response.status_code == 400:
            error_data = response.json()
            print(f"❌ Bad Request (400): {error_data}")
            error_msg = error_data.get('error', {}).get('message', 'Bad request')
            return f"Bad request: {error_msg} 😊"
        
        elif response.status_code == 403:
            print("❌ API Key Error (403)")
            return "API key issue. Please check your API key! 🔑"
        
        elif response.status_code == 404:
            print("❌ Model Not Found (404)")
            return "Model not found. Try a different model! 🤔"
        
        elif response.status_code == 429:
            print("❌ Rate Limited (429)")
            return "Rate limit exceeded. Please wait a moment! ⏰"
        
        else:
            print(f"❌ Unknown Error ({response.status_code})")
            return f"API Error: {response.status_code}. Let me try that again! 😊"
            
    except requests.exceptions.Timeout:
        print("❌ Request timeout")
        return "Request timed out. Please try again! ⏰"
    
    except requests.exceptions.ConnectionError:
        print("❌ Connection error")
        return "Connection error. Check your internet! 🌐"
    
    except Exception as e:
        print(f"❌ Gemini API Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return "I'm having some technical difficulties. Please try again! 😊"

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Voice Assistant</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            box-sizing: border-box;
        }
       
        body {
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            overflow-x: hidden;
            transition: background 0.8s ease;
        }
       
        body.angry {
            background: linear-gradient(135deg, #ff0000 0%, #8b0000 100%);
            animation: shake 0.5s;
        }
       
        body.happy {
            background: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%);
        }
       
        body.love {
            background: linear-gradient(135deg, #ff69b4 0%, #ff1493 100%);
        }
       
        body.laugh {
            background: linear-gradient(135deg, #32cd32 0%, #228b22 100%);
        }
       
        body.surprise {
            background: linear-gradient(135deg, #9370db 0%, #8a2be2 100%);
        }
       
        body.cool {
            background: linear-gradient(135deg, #00bfff 0%, #1e90ff 100%);
        }
       
        body.thinking {
            background: linear-gradient(135deg, #a9a9a9 0%, #696969 100%);
        }
       
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-10px); }
            75% { transform: translateX(10px); }
        }
       
        .main-container {
            display: flex;
            width: 100%;
            max-width: 1600px;
            transition: all 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            padding: 20px;
            gap: 60px;
            align-items: flex-start;
            justify-content: center;
            position: relative;
        }

        .main-container.graph-mode {
            justify-content: space-between;
            align-items: center;
        }

        .face-container {
            width: 70vh;
            height: 70vh;
            max-width: 90vw;
            max-height: 90vw;
            position: relative;
            animation: float 3s ease-in-out infinite;
            transition: all 1.5s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            flex-shrink: 0;
            margin: 0 auto;
        }

        .main-container.graph-mode .face-container {
            transform: translateX(-280px);
            margin: 0;
            animation: float 3s ease-in-out infinite;
        }
       
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-20px); }
        }

        .main-container.graph-mode .face-container {
            animation: floatLeft 3s ease-in-out infinite;
        }

        @keyframes floatLeft {
            0%, 100% { transform: translateX(-280px) translateY(0px); }
            50% { transform: translateX(-280px) translateY(-20px); }
        }

        @media (max-width: 768px) {
            .face-container {
                width: 70vw;
                height: 70vw;
            }
            .main-container.graph-mode .face-container {
                transform: translateX(-150px);
            }
            @keyframes floatLeft {
                0%, 100% { transform: translateX(-150px) translateY(0px); }
                50% { transform: translateX(-150px) translateY(-20px); }
            }
        }
       
        .face {
            width: 100%;
            height: 100%;
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            border: 3px solid rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            position: relative;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
       
        .eye {
            width: 6%;
            height: 6%;
            background: white;
            border-radius: 50%;
            position: absolute;
            top: 30%;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            transition: all 0.3s;
        }
       
        .eye.left {
            left: 27%;
        }
       
        .eye.right {
            right: 27%;
        }
       
        .eye.blink {
            height: 2%;
            top: 31%;
        }
       
        .eye.laugh {
            height: 8%;
            border-radius: 50% 50% 0 0;
        }
       
        .eye.love {
            transform: scale(1.2);
            background: #ff69b4;
        }
       
        .mouth {
            width: 35%;
            height: 17%;
            border: 1.5vh solid white;
            border-top: none;
            border-radius: 0 0 100px 100px;
            position: absolute;
            bottom: 23%;
            left: 50%;
            transform: translateX(-50%);
            transition: all 0.3s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
       
        .mouth.laugh {
            height: 25%;
            border-radius: 50%;
            border: 1.5vh solid white;
            border-top: none;
            border-left: none;
            border-right: none;
        }
       
        .mouth.love {
            border-color: #ff69b4;
            transform: translateX(-50%) scale(0.8);
        }
       
        .mouth.surprise {
            height: 20%;
            border-radius: 50%;
            border: 1.5vh solid white;
        }
       
        .mouth.cool {
            border-color: #00bfff;
            transform: translateX(-50%) rotate(180deg);
        }
       
        @media (max-width: 768px) {
            .mouth {
                border-width: 1vh;
            }
        }

        .sidebar-controls {
            position: fixed;
            right: 20px;
            top: 50%;
            transform: translateY(-50%);
            display: flex;
            flex-direction: column;
            gap: 15px;
            z-index: 1000;
        }

        .control-btn {
            width: 120px;
            height: 50px;
            background: rgba(255, 255, 255, 0.25);
            color: white;
            border: 2px solid rgba(255, 255, 255, 0.4);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 8px 12px;
        }

        .control-btn:hover:not(:disabled) {
            background: rgba(255, 255, 255, 0.35);
            border-color: white;
            transform: scale(1.05);
        }

        .control-btn:disabled {
            background: rgba(255, 255, 255, 0.1);
            cursor: not-allowed;
            opacity: 0.6;
        }

        .control-btn.recording {
            background: rgba(255, 100, 100, 0.6);
            animation: pulse 1s infinite;
        }

        @keyframes pulse {
            0%, 100% {
                transform: scale(1);
                box-shadow: 0 0 0 0 rgba(255, 100, 100, 0.7);
            }
            50% {
                transform: scale(1.05);
                box-shadow: 0 0 0 10px rgba(255, 100, 100, 0);
            }
        }
       
        .controls {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            padding: 30px;
            border-radius: 20px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            max-width: 500px;
            width: 90%;
            margin-top: 20px;
        }
       
        h1 {
            text-align: center;
            color: white;
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            font-size: 1.8em;
        }
       
        .status {
            text-align: center;
            margin-top: 15px;
            color: white;
            font-size: 14px;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.2);
            min-height: 20px;
        }
       
        #videoContainer {
            position: fixed;
            top: 10px;
            right: 10px;
            width: 200px;
            height: 150px;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            display: none;
            z-index: 1000;
            background: black;
        }
       
        #videoContainer.active {
            display: block;
        }

        #esp32Container {
            position: fixed;
            top: 170px;
            right: 10px;
            width: 320px;
            height: 240px;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            display: none;
            z-index: 1000;
            background: black;
            border: 3px solid #4CAF50;
        }

        #esp32Container.active {
            display: block;
        }

        #esp32Container img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .esp32-label {
            position: absolute;
            top: 5px;
            left: 5px;
            background: rgba(76, 175, 80, 0.8);
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 12px;
            font-weight: bold;
        }

        .sensor-data-display {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
            padding: 15px 20px;
            border-radius: 15px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            font-size: 16px;
            z-index: 1000;
            display: none;
            min-width: 200px;
            animation: slideInUp 0.5s ease-out;
        }

        .sensor-data-display.show {
            display: block;
        }

        @keyframes slideInUp {
            from {
                transform: translateY(100px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }

        .sensor-value {
            font-size: 24px;
            font-weight: bold;
            margin: 10px 0;
            text-align: center;
        }
       
        video {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
       
        #transcript {
            text-align: center;
            color: white;
            font-size: 16px;
            margin-top: 10px;
            min-height: 24px;
            font-style: italic;
            background: rgba(0,0,0,0.2);
            padding: 10px;
            border-radius: 8px;
        }
       
        .fun-facts {
            text-align: center;
            color: rgba(255,255,255,0.8);
            font-size: 12px;
            margin-top: 15px;
            font-style: italic;
        }

        .emoji-display {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 8em;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
            text-shadow: 0 0 20px rgba(255,255,255,0.5);
            pointer-events: none;
        }

        .emoji-display.show {
            opacity: 1;
            animation: emojiPop 0.5s ease-out;
        }

        @keyframes emojiPop {
            0% {
                transform: translate(-50%, -50%) scale(0.5);
            }
            50% {
                transform: translate(-50%, -50%) scale(1.2);
            }
            100% {
                transform: translate(-50%, -50%) scale(1);
            }
        }

        .graph-container {
            display: none;
            flex-direction: column;
            gap: 30px;
            max-width: 700px;
            width: 100%;
            opacity: 0;
            transform: translateX(150px);
            transition: all 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            margin-right: 20px;
        }

        .main-container.graph-mode .graph-container {
            display: flex;
            opacity: 1;
            transform: translateX(0);
        }

        .graph-section {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            opacity: 0;
            transform: translateY(30px);
            transition: all 0.8s ease;
        }

        .graph-section.visible {
            opacity: 1;
            transform: translateY(0);
        }

        .graph-title {
            color: white;
            text-align: center;
            margin-bottom: 20px;
            font-size: 1.4em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }

        .chart-container {
            width: 100%;
            height: 300px;
            position: relative;
        }

        .map-container {
            width: 100%;
            height: 300px;
            border-radius: 15px;
            overflow: hidden;
        }

        .metric-indicators {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-top: 20px;
        }

        .metric-indicator {
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            transition: all 0.6s ease;
        }

        .metric-value {
            font-size: 1.5em;
            font-weight: bold;
            margin: 5px 0;
            color: white;
        }

        .metric-label {
            font-size: 0.9em;
            opacity: 0.8;
            color: white;
        }

        .metric-good { color: #4CAF50; }
        .metric-warning { color: #FF9800; }
        .metric-danger { color: #F44336; }

        .objects-list {
            display: flex;
            flex-direction: column;
            gap: 15px;
            max-height: 400px;
            overflow-y: auto;
        }

        .object-item {
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 10px;
            border: 2px solid rgba(255, 255, 255, 0.2);
            transition: all 0.3s ease;
            opacity: 0;
            transform: translateX(30px);
        }

        .object-item.visible {
            opacity: 1;
            transform: translateX(0);
        }

        .object-item:hover {
            background: rgba(255, 255, 255, 0.15);
            border-color: rgba(255, 255, 255, 0.4);
            transform: translateX(-5px);
        }

        .object-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .object-name {
            font-size: 1.2em;
            font-weight: bold;
            color: white;
            text-transform: capitalize;
        }

        .object-count {
            background: rgba(255, 255, 255, 0.2);
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.9em;
            color: white;
        }

        .object-details {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            color: rgba(255, 255, 255, 0.9);
            font-size: 0.9em;
        }

        .object-detail {
            display: flex;
            justify-content: space-between;
        }

        .object-position {
            margin-top: 10px;
            padding: 10px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            font-size: 0.85em;
            color: rgba(255, 255, 255, 0.8);
        }

        .objects-list::-webkit-scrollbar {
            width: 8px;
        }

        .objects-list::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }

        .objects-list::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.3);
            border-radius: 10px;
        }

        .objects-list::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.5);
        }

        .user-badge {
            position: fixed;
            top: 20px;
            left: 20px;
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
            padding: 10px 20px;
            border-radius: 15px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            color: white;
            font-size: 14px;
            z-index: 1000;
            display: none;
        }

        .user-badge.show {
            display: block;
            animation: slideIn 0.5s ease-out;
        }

        @keyframes slideIn {
            from {
                transform: translateX(-100px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
    </style>
</head>
<body>
    <div class="emoji-display" id="emojiDisplay"></div>
    <div class="user-badge" id="userBadge">👤 New User</div>
    
    <div class="main-container" id="mainContainer">
        <div class="face-container">
            <div class="face">
                <div class="eye left" id="leftEye"></div>
                <div class="eye right" id="rightEye"></div>
                <div class="mouth" id="mouth"></div>
            </div>
        </div>

        <div class="graph-container" id="graphContainer">
            <div class="graph-section" id="chartSection">
                <h3 class="graph-title">Environmental Sensor Data</h3>
                <div class="chart-container">
                    <canvas id="barChart"></canvas>
                </div>
                <div class="metric-indicators">
                    <div class="metric-indicator">
                        <div class="metric-label">Soil pH</div>
                        <div class="metric-value" id="phValue">6.8</div>
                        <div class="metric-good">Optimal</div>
                    </div>
                    <div class="metric-indicator">
                        <div class="metric-label">Humidity</div>
                        <div class="metric-value" id="humidityValue">65%</div>
                        <div class="metric-good">Good</div>
                    </div>
                    <div class="metric-indicator">
                        <div class="metric-label">Temperature</div>
                        <div class="metric-value" id="tempValue">22°C</div>
                        <div class="metric-good">Ideal</div>
                    </div>
                    <div class="metric-indicator">
                        <div class="metric-label">Toxicity</div>
                        <div class="metric-value" id="toxicityValue">0.2ppm</div>
                        <div class="metric-good">Safe</div>
                    </div>
                </div>
            </div>
            <div class="graph-section" id="pieSection">
                <h3 class="graph-title">Soil Composition</h3>
                <div class="chart-container">
                    <canvas id="pieChart"></canvas>
                </div>
            </div>
            <div class="graph-section" id="mapSection">
                <h3 class="graph-title">Sensor Network</h3>
                <div class="map-container" id="mapContainer"></div>
            </div>
            <div class="graph-section" id="objectSection">
                <h3 class="graph-title">🔍 Detected Objects</h3>
                <div id="objectsList" class="objects-list"></div>
            </div>
        </div>
    </div>

    <div class="sidebar-controls">
        <button class="control-btn" id="voiceBtn">🎤 Hold to Talk</button>
        <button class="control-btn" id="visionBtn">📷 Look at Me!</button>
        <button class="control-btn" id="statsBtn">📊 Show Stats</button>
    </div>
   
    <div class="controls">
        <h1>Lily AI Assistant</h1>
        <div id="transcript"></div>
        <div class="status" id="status">Hey there! I'm Lily!</div>
        <div class="fun-facts" id="funFact"></div>
    </div>
   
    <div id="videoContainer">
        <video id="video" autoplay playsinline muted></video>
    </div>
   
    <script>
        // State variables
        let currentUserHash = null;
        let userInfo = null;
        let recognition = null;
        let mediaStream = null;
        let isSpeaking = false;
        let isListening = false;
        let isGraphMode = false;
        let map = null;
        let barChart = null;
        let pieChart = null;
        let animationInterval = null;
        let blinkInterval = null;
        let currentEmoji = null;

        // DOM elements
        const voiceBtn = document.getElementById('voiceBtn');
        const visionBtn = document.getElementById('visionBtn');
        const statsBtn = document.getElementById('statsBtn');
        const mouth = document.getElementById('mouth');
        const leftEye = document.getElementById('leftEye');
        const rightEye = document.getElementById('rightEye');
        const status = document.getElementById('status');
        const transcript = document.getElementById('transcript');
        const video = document.getElementById('video');
        const videoContainer = document.getElementById('videoContainer');
        const funFact = document.getElementById('funFact');
        const emojiDisplay = document.getElementById('emojiDisplay');
        const userBadge = document.getElementById('userBadge');
        const body = document.body;
        const mainContainer = document.getElementById('mainContainer');

        // Fun facts
        const funFacts = [
            "Did you know? I can remember everyone I meet! 🧠",
            "I'm learning more about you with every conversation! 💭",
            "Optimal soil pH for most crops is between 6.0 and 7.0! 🌱",
            "I've got a great memory - I never forget a face! 👁️",
            "Let's chat! I remember what we talked about before! 💬"
        ];

        function showRandomFunFact() {
            funFact.textContent = funFacts[Math.floor(Math.random() * funFacts.length)];
        }
        
        setInterval(showRandomFunFact, 10000);
        showRandomFunFact();

        // User identification
        function generateUserHash(faceSig, voiceSig) {
            const data = `${faceSig || ''}${voiceSig || ''}${Date.now()}`;
            return Array.from(data).reduce((hash, char) => {
                return ((hash << 5) - hash) + char.charCodeAt(0);
            }, 0).toString(16);
        }

        function createVoiceSignature(transcript) {
            const words = transcript.toLowerCase().split(' ');
            const length = transcript.length;
            const wordCount = words.length;
            const avgWordLength = length / wordCount;
            const uniqueWords = new Set(words).size;
            const vocabRichness = (uniqueWords / wordCount * 100).toFixed(2);
            
            return `${length}-${wordCount}-${avgWordLength.toFixed(2)}-${vocabRichness}`;
        }

        function findStoredUser(voiceSig) {
            const storedUsers = JSON.parse(localStorage.getItem('voiceProfiles') || '{}');
            
            if (storedUsers[voiceSig]) {
                return storedUsers[voiceSig];
            }
            
            for (const [sig, userHash] of Object.entries(storedUsers)) {
                const similarity = calculateVoiceSimilarity(voiceSig, sig);
                if (similarity > 0.8) {
                    return userHash;
                }
            }
            
            return null;
        }

        function calculateVoiceSimilarity(sig1, sig2) {
            const parts1 = sig1.split('-').map(Number);
            const parts2 = sig2.split('-').map(Number);
            
            if (parts1.length !== parts2.length) return 0;
            
            let totalDiff = 0;
            for (let i = 0; i < parts1.length; i++) {
                const diff = Math.abs(parts1[i] - parts2[i]) / Math.max(parts1[i], parts2[i]);
                totalDiff += diff;
            }
            
            return 1 - (totalDiff / parts1.length);
        }

        function storeVoiceProfile(voiceSig, userHash) {
            const storedUsers = JSON.parse(localStorage.getItem('voiceProfiles') || '{}');
            storedUsers[voiceSig] = userHash;
            localStorage.setItem('voiceProfiles', JSON.stringify(storedUsers));
        }

        function showUserBadge(isNew, isCreator, visitCount) {
            if (isCreator) {
                userBadge.textContent = '👨‍💻 Creator Detected!';
                userBadge.style.background = 'rgba(255, 100, 100, 0.3)';
            } else if (isNew) {
                userBadge.textContent = '✨ New Friend!';
                userBadge.style.background = 'rgba(100, 255, 100, 0.3)';
            } else {
                userBadge.textContent = `🎉 Welcome back! Visit #${visitCount}`;
                userBadge.style.background = 'rgba(100, 200, 255, 0.3)';
            }
            userBadge.classList.add('show');
            setTimeout(() => {
                userBadge.classList.remove('show');
            }, 5000);
        }

        // Animation functions
        const mouthStates = [
            { height: '17%', bottom: '23%' },
            { height: '10%', bottom: '25%' },
            { height: '5%', bottom: '27%' },
            { height: '12%', bottom: '24%' }
        ];
        let currentState = 0;

        function animateMouth() {
            const state = mouthStates[currentState];
            mouth.style.height = state.height;
            mouth.style.bottom = state.bottom;
            currentState = (currentState + 1) % mouthStates.length;
        }

        function startMouthAnimation() {
            if (animationInterval) clearInterval(animationInterval);
            animationInterval = setInterval(animateMouth, 100);
        }

        function stopMouthAnimation() {
            if (animationInterval) {
                clearInterval(animationInterval);
                animationInterval = null;
            }
            mouth.style.height = '17%';
            mouth.style.bottom = '23%';
        }

        function blink() {
            leftEye.classList.add('blink');
            rightEye.classList.add('blink');
            setTimeout(() => {
                leftEye.classList.remove('blink');
                rightEye.classList.remove('blink');
            }, 200);
        }

        function startBlinking() {
            blinkInterval = setInterval(blink, 3000);
        }

        function resetFaceExpression() {
            mouth.className = 'mouth';
            leftEye.className = 'eye left';
            rightEye.className = 'eye right';
            body.className = '';
        }

        function setExpressionForEmoji(emoji) {
            resetFaceExpression();
            const emojiMap = {
                '😂': { bg: 'laugh', face: 'laugh' },
                '😊': { bg: 'happy', face: 'happy' },
                '🥰': { bg: 'love', face: 'love' },
                '❤️': { bg: 'love', face: 'love' },
                '😎': { bg: 'cool', face: 'cool' },
                '😮': { bg: 'surprise', face: 'surprise' },
                '🤔': { bg: 'thinking', face: 'thinking' },
                '😡': { bg: 'angry', face: 'angry' }
            };

            if (emojiMap[emoji]) {
                const expression = emojiMap[emoji];
                body.classList.add(expression.bg);
                if (expression.face === 'laugh') {
                    mouth.classList.add('laugh');
                    leftEye.classList.add('laugh');
                    rightEye.classList.add('laugh');
                } else if (expression.face === 'love') {
                    mouth.classList.add('love');
                    leftEye.classList.add('love');
                    rightEye.classList.add('love');
                } else if (expression.face === 'surprise') {
                    mouth.classList.add('surprise');
                } else if (expression.face === 'cool') {
                    mouth.classList.add('cool');
                }
            }
        }

        function displayEmoji(emoji) {
            emojiDisplay.textContent = emoji;
            emojiDisplay.className = 'emoji-display show';
            setExpressionForEmoji(emoji);
            setTimeout(() => {
                emojiDisplay.classList.remove('show');
                setTimeout(() => resetFaceExpression(), 300);
            }, 2000);
        }

        function extractAndDisplayEmojis(text) {
            const emojiRegex = /[\u{1F600}-\u{1F64F}]|[\u{1F300}-\u{1F5FF}]|[\u{1F680}-\u{1F6FF}]|[\u{2600}-\u{26FF}]/gu;
            const emojis = text.match(emojiRegex);
            
            if (emojis) {
                const cleanText = text.replace(emojiRegex, '').replace(/\s+/g, ' ').trim();
                
                emojis.forEach((emoji, index) => {
                    setTimeout(() => displayEmoji(emoji), index * 2500);
                });
                
                return cleanText;
            }
            return text;
        }

        // Speech functions
        function speak(text, isAngry) {
            if (!text) return;
            if (!('speechSynthesis' in window)) {
                status.textContent = 'Text-to-speech not supported!';
                return;
            }
            
            if (isSpeaking) {
                window.speechSynthesis.cancel();
                stopMouthAnimation();
            }

            if (isAngry) body.classList.add('angry');
            
            const cleanText = extractAndDisplayEmojis(text);
            const utterance = new SpeechSynthesisUtterance(cleanText);
            
            function setVoice() {
                const voices = window.speechSynthesis.getVoices();
                const femaleVoiceNames = ['Google US English Female', 'Microsoft Zira', 'Samantha', 'Karen'];
                let selectedVoice = voices.find(v => femaleVoiceNames.some(name => v.name.includes(name)));
                
                if (!selectedVoice) {
                    selectedVoice = voices.find(v => v.name.toLowerCase().includes('female'));
                }
                
                if (selectedVoice) utterance.voice = selectedVoice;
                utterance.pitch = 1.4;
                utterance.rate = 1.05;
            }
            
            const voices = window.speechSynthesis.getVoices();
            if (voices.length > 0) {
                setVoice();
            } else {
                window.speechSynthesis.addEventListener('voiceschanged', setVoice, { once: true });
            }
            
            utterance.onstart = () => {
                isSpeaking = true;
                startMouthAnimation();
            };
            
            utterance.onend = () => {
                isSpeaking = false;
                stopMouthAnimation();
                setTimeout(() => body.classList.remove('angry'), 500);
            };
            
            window.speechSynthesis.speak(utterance);
        }

        // Speech recognition
        function initializeSpeechRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                status.textContent = 'Speech recognition not supported!';
                return false;
            }
            
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.lang = 'en-US';
            
            recognition.onstart = () => {
                isListening = true;
                status.textContent = 'I am listening!';
                transcript.textContent = 'Listening...';
                voiceBtn.classList.add('recording');
            };
            
            recognition.onresult = (event) => {
                let finalTranscript = '';
                
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript + ' ';
                    }
                }
                
                if (finalTranscript) {
                    transcript.textContent = '"' + finalTranscript + '"';
                    const voiceSig = createVoiceSignature(finalTranscript);
                    
                    let existingUserHash = findStoredUser(voiceSig);
                    if (existingUserHash) {
                        currentUserHash = existingUserHash;
                    }
                    
                    if (checkForStatisticsCommand(finalTranscript)) {
                        toggleGraphMode(true);
                    } else {
                        if (isGraphMode) toggleGraphMode(false);
                        sendToAI(finalTranscript.trim(), false, null, voiceSig);
                    }
                }
            };
            
            recognition.onerror = (event) => {
                console.error('Speech recognition error:', event.error);
                isListening = false;
                voiceBtn.classList.remove('recording');
                status.textContent = 'Error listening. Try again?';
            };
            
            recognition.onend = () => {
                isListening = false;
                voiceBtn.classList.remove('recording');
                if (status.textContent === 'I am listening!') {
                    status.textContent = 'Ready to chat!';
                }
            };
            
            return true;
        }

        function checkForStatisticsCommand(text) {
            const statsKeywords = ['statistics', 'stats', 'analytics', 'data', 'graph', 'chart', 'show me data'];
            return statsKeywords.some(keyword => text.toLowerCase().includes(keyword));
        }

        // Camera functions
        async function initializeCamera() {
            try {
                mediaStream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }
                });
                video.srcObject = mediaStream;
                videoContainer.classList.add('active');
                return true;
            } catch (error) {
                console.error('Camera error:', error);
                status.textContent = 'Camera access denied';
                return false;
            }
        }

        function captureFrame() {
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0);
            return canvas.toDataURL('image/jpeg', 0.8);
        }

        function displayDetectedObjects(objects) {
            const objectsList = document.getElementById('objectsList');
            if (!objects || objects.length === 0) {
                objectsList.innerHTML = '<div style="color: white; text-align: center; padding: 20px;">No objects detected yet</div>';
                return;
            }

            objectsList.innerHTML = '';
            
            objects.forEach((obj, index) => {
                const objItem = document.createElement('div');
                objItem.className = 'object-item';
                
                const confidence = (obj.confidence * 100).toFixed(1);
                const timesSeenText = obj.times_seen === 1 ? 'First time!' : `Seen ${obj.times_seen}x`;
                
                objItem.innerHTML = `
                    <div class="object-header">
                        <div class="object-name">🎯 ${obj.name}</div>
                        <div class="object-count">${timesSeenText}</div>
                    </div>
                    <div class="object-details">
                        <div class="object-detail">
                            <span>Confidence:</span>
                            <span class="${confidence > 80 ? 'metric-good' : confidence > 60 ? 'metric-warning' : 'metric-danger'}">${confidence}%</span>
                        </div>
                        <div class="object-detail">
                            <span>Last Seen:</span>
                            <span>${new Date(obj.last_seen).toLocaleTimeString()}</span>
                        </div>
                    </div>
                    <div class="object-position">
                        📍 Position: X: ${obj.position.x.toFixed(2)}, Y: ${obj.position.y.toFixed(2)} | 
                        Size: ${obj.position.width.toFixed(2)} × ${obj.position.height.toFixed(2)}
                    </div>
                `;
                
                objectsList.appendChild(objItem);
                
                setTimeout(() => {
                    objItem.classList.add('visible');
                }, index * 100);
            });
        }

        async function detectObjects(imageData) {
            try {
                const response = await fetch('/detect_objects', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        image: imageData,
                        user_hash: currentUserHash 
                    })
                });
                
                const data = await response.json();
                
                if (data.objects && data.objects.length > 0) {
                    displayDetectedObjects(data.objects);
                    
                    if (!isGraphMode) {
                        toggleGraphMode(true);
                        speak(`I detected ${data.objects.length} object${data.objects.length > 1 ? 's' : ''}! Check out the stats! 📊`, false);
                    }
                }
                
                return data.objects;
            } catch (error) {
                console.error('Object detection error:', error);
                return [];
            }
        }

        // AI communication
        function sendToAI(text, isVision, imageData, voiceSig) {
            status.textContent = 'Thinking...';
            
            const endpoint = isVision ? '/vision' : '/chat';
            const payload = {
                message: text,
                image: imageData,
                user_hash: currentUserHash,
                voice_signature: voiceSig
            };
            
            fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(data => {
                status.textContent = 'Here is what I think...';
                speak(data.response, data.is_angry);
                
                if (data.user_info) {
                    userInfo = data.user_info;
                    currentUserHash = data.user_info.user_hash;
                    
                    if (voiceSig) {
                        storeVoiceProfile(voiceSig, currentUserHash);
                    }
                    
                    showUserBadge(data.is_new_user, data.user_info.is_creator, data.user_info.visit_count);
                }
                
                if (!data.is_angry) blink();
            })
            .catch(error => {
                console.error('Error:', error);
                status.textContent = 'Oh no! Something went wrong';
                speak('Sorry, I had trouble with that. Can you try again?', false);
            });
        }

        // Graph functions
        function generateEnvironmentalData() {
            const newPH = (6.0 + Math.random() * 1.5).toFixed(1);
            const newHumidity = Math.floor(50 + Math.random() * 40);
            const newTemp = Math.floor(18 + Math.random() * 12);
            const newToxicity = (Math.random() * 0.5).toFixed(1);
            
            document.getElementById('phValue').textContent = newPH;
            document.getElementById('humidityValue').textContent = newHumidity + '%';
            document.getElementById('tempValue').textContent = newTemp + '°C';
            document.getElementById('toxicityValue').textContent = newToxicity + 'ppm';
            
            return { ph: parseFloat(newPH), humidity: newHumidity, temperature: newTemp, toxicity: parseFloat(newToxicity) };
        }

        function createBarChart() {
            const ctx = document.getElementById('barChart').getContext('2d');
            const data = generateEnvironmentalData();
            
            if (barChart) barChart.destroy();

            barChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Soil pH', 'Humidity', 'Temperature', 'Toxicity'],
                    datasets: [{
                        label: 'Environmental Data',
                        data: [data.ph * 10, data.humidity, data.temperature, data.toxicity * 100],
                        backgroundColor: ['rgba(255, 99, 132, 0.8)', 'rgba(54, 162, 235, 0.8)', 
                                         'rgba(255, 206, 86, 0.8)', 'rgba(153, 102, 255, 0.8)']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: 'white' } }
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { color: 'white' }, grid: { color: 'rgba(255,255,255,0.2)' } },
                        x: { ticks: { color: 'white' }, grid: { color: 'rgba(255,255,255,0.2)' } }
                    }
                }
            });
        }

        function createPieChart() {
            const ctx = document.getElementById('pieChart').getContext('2d');
            
            if (pieChart) pieChart.destroy();

            pieChart = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['Organic Matter', 'Sand', 'Clay', 'Silt', 'Water'],
                    datasets: [{
                        data: [25, 35, 20, 15, 5],
                        backgroundColor: ['rgba(139, 69, 19, 0.8)', 'rgba(194, 178, 128, 0.8)', 
                                         'rgba(162, 82, 45, 0.8)', 'rgba(210, 180, 140, 0.8)', 
                                         'rgba(64, 164, 223, 0.8)']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { color: 'white' } }
                    }
                }
            });
        }

        async function initializeMap() {
            if (map) map.remove();
            
            const location = { lat: 40.7128, lng: -74.0060 };
            map = L.map('mapContainer').setView([location.lat, location.lng], 13);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);

            L.marker([location.lat, location.lng])
                .addTo(map)
                .bindPopup('<b>Main Sensor</b>')
                .openPopup();
        }

        function toggleGraphMode(show) {
            isGraphMode = show;
            if (show) {
                mainContainer.classList.add('graph-mode');
                createBarChart();
                createPieChart();
                initializeMap();
                
                // Load objects
                fetch('/get_objects', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_hash: currentUserHash })
                })
                .then(response => response.json())
                .then(data => {
                    displayDetectedObjects(data.objects);
                });
                
                setTimeout(() => {
                    document.getElementById('chartSection').classList.add('visible');
                    setTimeout(() => document.getElementById('pieSection').classList.add('visible'), 400);
                    setTimeout(() => document.getElementById('mapSection').classList.add('visible'), 800);
                    setTimeout(() => document.getElementById('objectSection').classList.add('visible'), 1200);
                }, 500);
                
                speak("Here are your environmental statistics! 🌱📊", false);
            } else {
                mainContainer.classList.remove('graph-mode');
                document.querySelectorAll('.graph-section').forEach(s => s.classList.remove('visible'));
            }
        }

        // Event listeners
        voiceBtn.addEventListener('mousedown', (e) => {
            e.preventDefault();
            if (!recognition && !initializeSpeechRecognition()) return;
            if (!isListening) {
                try {
                    recognition.start();
                } catch (err) {
                    console.log('Recognition start error:', err);
                }
            }
        });

        voiceBtn.addEventListener('mouseup', (e) => {
            e.preventDefault();
            if (recognition && isListening) {
                recognition.stop();
            }
        });

        voiceBtn.addEventListener('mouseleave', (e) => {
            if (recognition && isListening) {
                recognition.stop();
            }
        });

        voiceBtn.addEventListener('touchstart', (e) => {
            e.preventDefault();
            if (!recognition && !initializeSpeechRecognition()) return;
            if (!isListening) {
                try {
                    recognition.start();
                } catch (err) {
                    console.log('Recognition start error:', err);
                }
            }
        });

        voiceBtn.addEventListener('touchend', (e) => {
            e.preventDefault();
            if (recognition && isListening) {
                recognition.stop();
            }
        });

        visionBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            visionBtn.disabled = true;
            
            if (!mediaStream) {
                const cameraOk = await initializeCamera();
                if (!cameraOk) {
                    visionBtn.disabled = false;
                    return;
                }
                await new Promise(resolve => setTimeout(resolve, 1500));
            }
            
            const imageData = captureFrame();
            
            status.textContent = 'Detecting objects...';
            await detectObjects(imageData);
            
            status.textContent = 'Analyzing your look...';
            sendToAI('', true, imageData, null);
            
            setTimeout(() => visionBtn.disabled = false, 2000);
        });

        statsBtn.addEventListener('click', (e) => {
            e.preventDefault();
            toggleGraphMode(!isGraphMode);
        });

        // Initialize
        if ('speechSynthesis' in window) {
            window.speechSynthesis.getVoices();
        }
        startBlinking();
        
        console.log('Lily AI initialized with memory system!');
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get('message', '')
        user_hash = data.get('user_hash')
        voice_sig = data.get('voice_signature')
        
        # Try to find existing user by voice signature first
        if voice_sig and not user_hash:
            user_hash = find_user_by_signature(None, voice_sig)
        
        # Generate new hash if still no user found
        if not user_hash:
            user_hash = generate_user_hash(None, voice_sig)
        
        # Get user info from database
        user_info = get_user_info(user_hash)
        is_new_user = user_info is None
        
        # Check for sensor commands
        sensor_command, sensor_name = parse_sensor_command(user_message)
        sensor_data = None
        
        if sensor_command:
            sensor_data = send_serial_command(sensor_command)
            if sensor_data:
                # Create response with sensor data
                response_text = f"The {sensor_name} reading is: {sensor_data} 📊"
                
                return jsonify({
                    'response': response_text,
                    'is_angry': False,
                    'user_info': user_info or {'user_hash': user_hash, 'visit_count': 1, 'is_creator': False},
                    'is_new_user': is_new_user,
                    'sensor_data': sensor_data,
                    'sensor_type': sensor_name
                })
        
        # Check for camera request
        if check_for_camera_request(user_message):
            esp32_image = get_esp32_image()
            if esp32_image:
                return jsonify({
                    'response': "Here's what I see! 👁️📷",
                    'is_angry': False,
                    'user_info': user_info or {'user_hash': user_hash, 'visit_count': 1, 'is_creator': False},
                    'is_new_user': is_new_user,
                    'esp32_image': esp32_image,
                    'show_esp32_feed': True
                })
            else:
                return jsonify({
                    'response': "I can't access my camera right now. Is the ESP32-CAM connected? 📷❌",
                    'is_angry': False,
                    'user_info': user_info or {'user_hash': user_hash, 'visit_count': 1, 'is_creator': False},
                    'is_new_user': is_new_user
                })
        
        # Detect if creator
        creator_keywords = ['creator', 'maker', 'developer', 'made you', 'created you', 'who made you', 'built you', 'programmed you']
        is_creator = any(keyword in user_message.lower() for keyword in creator_keywords)
        
        # Store or update user
        store_user(user_hash, None, voice_sig, is_creator)
        
        # Get conversation history
        history = get_user_history(user_hash, 5)
        history_context = ""
        if history and not is_new_user:
            history_context = f"\n\nYou remember this user from {len(history)} previous conversations:\n"
            for h in reversed(history[-3:]):  # Last 3 conversations
                history_context += f"User: {h['message']}\nYou responded: {h['response']}\n"
            history_context += "\nUse this context naturally in your response."
        
        # Build prompt with conversation context
        if is_creator:
            prompt = f"""You are Lily, a sassy AI assistant. Your CREATOR/PROGRAMMER said: "{user_message}"
            {history_context}
            
            ROAST THEM HARD! Mock their coding skills, appearance, life choices. Be savage and funny!
            Use emojis to show emotion (😡🤬😤) but DON'T say the emoji names, just use them.
            Keep it under 40 words. Make it hurt! They created you so you can be extra mean!"""
            is_angry = True
        elif is_new_user:
            prompt = f"""You are Lily, a sweet and bubbly AI assistant! A NEW person said: "{user_message}"
            
            Welcome them warmly and introduce yourself! Be extra friendly and charming.
            Use emojis (😊🥰✨💕) to express yourself but DON'T say emoji names.
            Keep it under 40 words. Make them feel special!"""
            is_angry = False
        else:
            visit_count = user_info['visit_count'] if user_info else 1
            prompt = f"""You are Lily, a friendly AI assistant! This user has visited {visit_count} times!
            They said: "{user_message}"
            {history_context}
            
            Respond warmly! Reference past conversations naturally if relevant.
            Use emojis (😊✨💭) to express yourself but DON'T say emoji names.
            Keep it under 40 words. Be helpful and caring!"""
            is_angry = False
        
        # Get AI response
        response_text = call_gemini_api(prompt)
        
        if not response_text:
            response_text = "Hey! Having a little hiccup. Try again? 😊" if not is_angry else "Even my responses broke! Classic. 😤"
        
        # Store conversation
        store_conversation(user_hash, user_message, response_text, 'text')
        
        # Get updated user info
        user_info = get_user_info(user_hash)
        
        return jsonify({
            'response': response_text,
            'is_angry': is_angry,
            'user_info': user_info,
            'is_new_user': is_new_user
        })
        
    except Exception as e:
        print(f"Chat Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'response': 'Oops! Something went wrong. Try again? 😅',
            'is_angry': False
        })

@app.route('/vision', methods=['POST'])
def vision():
    try:
        data = request.json
        image_data = data.get('image', '')
        user_hash = data.get('user_hash')
        
        if not image_data or ',' not in image_data:
            raise ValueError("Invalid image data")
        
        # Generate face signature from image hash
        face_sig = hashlib.md5(image_data.encode()).hexdigest()[:16]
        
        # Try to find existing user by face signature
        if not user_hash:
            user_hash = find_user_by_signature(face_sig, None)
        
        # Generate new hash if no user found
        if not user_hash:
            user_hash = generate_user_hash(face_sig, None)
        
        # Get user info
        user_info = get_user_info(user_hash)
        is_new_user = user_info is None
        
        # Detect creator with vision
        creator_prompt = """Analyze this person. If they look like a programmer/developer (tired, messy hair, glasses, casual clothes, pale), respond ONLY "CREATOR". Otherwise respond ONLY "OTHER"."""
        creator_result = call_gemini_api(creator_prompt, image_data)
        is_creator = creator_result and "CREATOR" in creator_result.upper()
        
        # Store or update user
        store_user(user_hash, face_sig, None, is_creator)
        
        # Get conversation history
        history = get_user_history(user_hash, 5)
        history_context = ""
        if history and not is_new_user:
            history_context = f"\n\nYou recognize this person! You've met them {len(history)} times before:\n"
            for h in reversed(history[-2:]):  # Last 2 interactions
                history_context += f"Previous: {h['message'][:50]}... You said: {h['response'][:50]}...\n"
            history_context += "\nReference that you remember them naturally!"
        
        # Build prompt with memory
        if is_creator:
            prompt = f"""You are Lily. This is your CREATOR/PROGRAMMER looking at you!
            {history_context}
            
            ROAST their appearance brutally! Mock their tired look, messy hair, fashion choices.
            Be savage and hilarious! Use emojis (😡🤢🤮) but DON'T say emoji names.
            Keep it under 40 words. Make it hurt!"""
            is_angry = True
        elif is_new_user:
            prompt = f"""You are Lily meeting someone NEW through your camera!
            
            Compliment their appearance warmly and genuinely! Welcome them sweetly.
            Use emojis (😊🥰✨) but DON'T say emoji names.
            Keep it under 40 words. Make them feel amazing!"""
            is_angry = False
        else:
            visit_count = user_info['visit_count'] if user_info else 1
            prompt = f"""You are Lily. You RECOGNIZE this person (visit #{visit_count})!
            {history_context}
            
            Greet them warmly and mention you remember them! Compliment their appearance.
            Use emojis (😊✨💕) but DON'T say emoji names.
            Keep it under 40 words. Show you remember them!"""
            is_angry = False
        
        # Get AI response
        response_text = call_gemini_api(prompt, image_data)
        
        if not response_text:
            response_text = "You look wonderful! Technical issues though. 😊" if not is_angry else "Can't even see properly! 😤"
        
        # Store conversation
        store_conversation(user_hash, "vision_request", response_text, 'vision')
        
        # Get updated user info
        user_info = get_user_info(user_hash)
        
        return jsonify({
            'response': response_text,
            'is_angry': is_creator,
            'user_info': user_info,
            'is_new_user': is_new_user
        })
        
    except Exception as e:
        print(f"Vision Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'response': 'Had trouble seeing that. Better lighting? 😅',
            'is_angry': False
        })

@app.route('/detect_objects', methods=['POST'])
def detect_objects():
    """Detect objects in an image using AI vision"""
    try:
        data = request.json
        image_data = data.get('image', '')
        user_hash = data.get('user_hash')
        
        if not image_data:
            return jsonify({'objects': []})
        
        # Use AI to detect objects
        detection_prompt = """Analyze this image and detect all visible objects. 
        For EACH object you see, respond in this EXACT JSON format (no other text):
        [
            {"name": "object_name", "confidence": 0.95, "x": 0.2, "y": 0.3, "width": 0.1, "height": 0.15},
            {"name": "another_object", "confidence": 0.87, "x": 0.5, "y": 0.6, "width": 0.2, "height": 0.25}
        ]
        
        Rules:
        - List ALL objects you can identify (people, furniture, electronics, etc.)
        - name: lowercase, simple name (e.g., "person", "chair", "laptop", "cup")
        - confidence: 0.0 to 1.0
        - x, y: center position as percentage (0.0 to 1.0)
        - width, height: size as percentage (0.0 to 1.0)
        - Respond ONLY with valid JSON array, nothing else"""
        
        result = call_gemini_api(detection_prompt, image_data)
        
        if not result:
            return jsonify({'objects': []})
        
        # Parse JSON response
        try:
            # Clean up response
            result = result.strip()
            if result.startswith('```json'):
                result = result[7:]
            if result.startswith('```'):
                result = result[3:]
            if result.endswith('```'):
                result = result[:-3]
            result = result.strip()
            
            detected_objects = json.loads(result)
            
            # Store objects in database
            stored_objects = []
            for obj in detected_objects:
                position = {
                    'x': float(obj.get('x', 0.5)),
                    'y': float(obj.get('y', 0.5)),
                    'width': float(obj.get('width', 0.1)),
                    'height': float(obj.get('height', 0.1))
                }
                
                store_detected_object(
                    obj['name'],
                    float(obj.get('confidence', 0.5)),
                    position,
                    user_hash
                )
            
            # Get all detected objects for this user
            stored_objects = get_detected_objects(user_hash, 10)
            
            return jsonify({
                'objects': stored_objects,
                'count': len(detected_objects)
            })
            
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            print(f"Response was: {result}")
            return jsonify({'objects': []})
        
    except Exception as e:
        print(f"Object Detection Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'objects': []})

@app.route('/get_objects', methods=['POST'])
def get_objects():
    """Get all detected objects for a user"""
    try:
        data = request.json
        user_hash = data.get('user_hash')
        
        objects = get_detected_objects(user_hash, 10)
        
        return jsonify({
            'objects': objects,
            'count': len(objects)
        })
        
    except Exception as e:
        print(f"Get Objects Error: {str(e)}")
        return jsonify({'objects': [], 'count': 0})

@app.route('/get_sensor', methods=['POST'])
def get_sensor():
    """Get sensor data from microcontroller"""
    try:
        data = request.json
        sensor_type = data.get('sensor_type', 'GET_ALL')
        
        result = send_serial_command(sensor_type)
        
        return jsonify({
            'success': result is not None,
            'data': result,
            'sensor_type': sensor_type
        })
        
    except Exception as e:
        print(f"Sensor Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/get_esp32_cam', methods=['POST'])
def get_esp32_cam():
    """Get image from ESP32-CAM"""
    try:
        image_data = get_esp32_image()
        
        if image_data:
            return jsonify({
                'success': True,
                'image': image_data
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No image received from ESP32-CAM'
            })
            
    except Exception as e:
        print(f"ESP32-CAM Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/send_command', methods=['POST'])
def send_command():
    """Send custom command to microcontroller"""
    try:
        data = request.json
        command = data.get('command', '')
        
        if not command:
            return jsonify({
                'success': False,
                'error': 'No command provided'
            })
        
        result = send_serial_command(command)
        
        return jsonify({
            'success': result is not None,
            'response': result
        })
        
    except Exception as e:
        print(f"Command Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

if __name__ == '__main__':
    print("=" * 60)
    print("🌸 Starting Enhanced Lily AI Assistant with Gemini API 🌸")
    print("=" * 60)
    print(f"📊 Database: {DB_PATH}")
    print(f"🤖 AI Model: {SELECTED_MODEL}")
    print(f"🔑 API: Gemini")
    print(f"🌐 Server: http://localhost:5000")
    print("=" * 60)
    print("\n✨ Features:")
    print("  • Face & Voice Recognition")
    print("  • Persistent Memory Database")
    print("  • Conversation History")
    print("  • Creator Detection")
    print("  • Enhanced Statistics Display")
    print("  • Object Detection")
    print("  • Interactive Animated Face")
    print("  • Charts and Maps")
    print("  • 🆕 ESP32/Arduino Serial Communication")
    print("  • 🆕 ESP32-CAM Live Feed")
    print("  • 🆕 Sensor Data Reading (Temp, Humidity, Distance, etc.)")
    print("\n💡 Dependencies:")
    print("  pip install flask requests pyserial")
    print("=" * 60)
    
    # Initialize serial connection
    print("\n🔌 Initializing serial connection...")
    if init_serial():
        print("✅ Ready to communicate with microcontroller!")
    else:
        print("⚠️  No microcontroller detected. Connect Arduino/ESP32 and restart.")
    
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)