# robot_control.py
import serial
import time
import threading
from datetime import datetime
import json
import math
from config import Config
import movement_recorder
import map_generator
from camera_navigation import CameraNavigation

class RobotControl:
    def __init__(self):
        self.serial_conn = None
        self.recorder = movement_recorder.MovementRecorder()
        self.mapper = map_generator.MapGenerator()
        self.navigator = CameraNavigation()
        self.is_connected = False
        self.current_position = (0, 0)
        self.current_heading = 0  # Degrees
        self.current_speed = Config.BASE_SPEED
        self.status = "Disconnected"
        self.last_command = None
        self.obstacles_detected = []
        self.battery_level = 100  # Simulated battery
        
    def connect_arduino(self):
        """Establish connection with Arduino"""
        try:
            self.serial_conn = serial.Serial(
                Config.ARDUINO_PORT,
                Config.ARDUINO_BAUD,
                timeout=1
            )
            time.sleep(2)  # Wait for Arduino to reset
            print("Connected to Arduino")
            self.is_connected = True
            self.status = "Connected"
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.status = f"Connection Error: {e}"
            return False
    
    def send_command(self, command):
        """Send command to Arduino"""
        if self.is_connected and self.serial_conn:
            try:
                self.serial_conn.write(f"{command}\n".encode())
                self.last_command = command
                
                # Record the movement
                self.recorder.record_movement(command, self.current_position, self.current_heading)
                
                # Update position based on movement
                self._update_position(command)
                
                # Update status
                self.status = f"Executing: {command}"
                
                return True
            except Exception as e:
                print(f"Error sending command: {e}")
                self.status = f"Command Error: {e}"
                return False
        return False
    
    def _update_position(self, command):
        """Update robot's estimated position"""
        distance_per_second = 0.1  # meters per second at base speed
        turn_per_second = 45  # degrees per second
        
        if "FORWARD" in command:
            dx = distance_per_second * math.cos(math.radians(self.current_heading))
            dy = distance_per_second * math.sin(math.radians(self.current_heading))
            self.current_position = (
                self.current_position[0] + dx,
                self.current_position[1] + dy
            )
        elif "BACKWARD" in command:
            dx = -distance_per_second * math.cos(math.radians(self.current_heading))
            dy = -distance_per_second * math.sin(math.radians(self.current_heading))
            self.current_position = (
                self.current_position[0] + dx,
                self.current_position[1] + dy
            )
        elif "TURN_LEFT" in command or "SMOOTH_LEFT" in command:
            if "TURN" in command:
                self.current_heading = (self.current_heading + turn_per_second) % 360
            else:
                self.current_heading = (self.current_heading + turn_per_second/2) % 360
        elif "TURN_RIGHT" in command or "SMOOTH_RIGHT" in command:
            if "TURN" in command:
                self.current_heading = (self.current_heading - turn_per_second) % 360
            else:
                self.current_heading = (self.current_heading - turn_per_second/2) % 360
            
        # Update map
        self.mapper.update_map(self.current_position, self.current_heading)
        
        # Simulate battery drain
        if command != "STOP":
            self.battery_level = max(0, self.battery_level - 0.1)
    
    def move_forward(self, duration=1.0):
        self.send_command("FORWARD")
        time.sleep(duration)
        self.send_command("STOP")
    
    def move_backward(self, duration=1.0):
        self.send_command("BACKWARD")
        time.sleep(duration)
        self.send_command("STOP")
    
    def turn_left(self, duration=0.5):
        self.send_command("TURN_LEFT")
        time.sleep(duration)
        self.send_command("STOP")
    
    def turn_right(self, duration=0.5):
        self.send_command("TURN_RIGHT")
        time.sleep(duration)
        self.send_command("STOP")
    
    def smooth_left(self, duration=1.0):
        self.send_command("SMOOTH_LEFT")
        time.sleep(duration)
        self.send_command("STOP")
    
    def smooth_right(self, duration=1.0):
        self.send_command("SMOOTH_RIGHT")
        time.sleep(duration)
        self.send_command("STOP")
    
    def stop(self):
        self.send_command("STOP")
        self.status = "Stopped"
    
    def set_speed(self, speed):
        """Set motor speed (0-255)"""
        speed = max(0, min(255, speed))
        self.current_speed = speed
        self.send_command(f"SPEED:{int(speed)}")
    
    def navigate_to_target(self, target_description):
        """Use AI to navigate to a target based on description"""
        print(f"Navigating to: {target_description}")
        
        # Get navigation instruction from Gemini AI
        frame = self.navigator.capture_frame()
        if frame is not None:
            instruction = self.navigator.get_navigation_instruction(target_description, frame)
            print(f"AI Instruction: {instruction}")
            
            # Extract movement from instruction
            instruction_lower = instruction.lower()
            if "forward" in instruction_lower:
                self.move_forward(2)
            elif "backward" in instruction_lower:
                self.move_backward(1)
            elif "left" in instruction_lower:
                self.turn_left()
            elif "right" in instruction_lower:
                self.turn_right()
            elif "stop" in instruction_lower:
                self.stop()
            
            return instruction
        return "No camera feed available"
    
    def explore_room(self):
        """Autonomous room exploration"""
        print("Starting room exploration...")
        self.status = "Exploring room"
        
        # Simple exploration pattern
        movements = [
            ("FORWARD", 2),
            ("TURN_LEFT", 0.5),
            ("FORWARD", 1),
            ("TURN_RIGHT", 0.5),
            ("FORWARD", 2),
            ("TURN_RIGHT", 0.5),
        ]
        
        for move, duration in movements:
            self.send_command(move)
            time.sleep(duration)
            self.stop()
            
            # Capture and analyze environment
            frame = self.navigator.capture_frame()
            if frame is not None:
                obstacle_info = self.navigator.analyze_frame(frame)
                if any(obstacle_info.values()):
                    self.obstacles_detected.append({
                        'position': self.current_position,
                        'type': 'obstacle',
                        'timestamp': datetime.now().isoformat()
                    })
                    self.mapper.add_obstacle(self.current_position)
        
        self.stop()
        self.status = "Exploration complete"
        print("Exploration complete")
    
    def get_status(self):
        """Get current robot status"""
        return {
            'connected': self.is_connected,
            'status': self.status,
            'position': self.current_position,
            'heading': self.current_heading,
            'speed': self.current_speed,
            'battery': self.battery_level,
            'last_command': self.last_command,
            'obstacles_detected': len(self.obstacles_detected),
            'movements_recorded': len(self.recorder.movements)
        }
    
    def save_movement_log(self):
        """Save movement history to file"""
        self.recorder.save_to_file()
        print("Movement log saved")
    
    def generate_map(self):
        """Generate and save the map"""
        self.mapper.generate_map()
        self.mapper.save_map()
        print("Map generated and saved")
    
    def disconnect(self):
        """Clean shutdown"""
        self.stop()
        if self.serial_conn:
            self.serial_conn.close()
        self.save_movement_log()
        self.generate_map()
        self.status = "Disconnected"
        self.is_connected = False
        print("Robot disconnected")