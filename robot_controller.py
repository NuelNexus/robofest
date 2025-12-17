# robot_controller.py
import serial
import time
import threading
from config import Config
from camera_manager import CameraManager
from navigation_system import NavigationSystem
from database_manager import DatabaseManager

class RobotController:
    def __init__(self):
        self.db = DatabaseManager()
        self.camera = CameraManager()
        self.navigator = NavigationSystem(self.camera, self.db)
        
        # Hardware connection
        self.arduino = None
        self.connected = False
        
        # Control parameters
        self.current_speed = Config.BASE_SPEED
        self.battery_level = 100
        self.emergency_stop = False
        
        # Statistics
        self.total_distance = 0
        self.commands_executed = 0
        
        # Threads
        self.monitor_thread = None
        self.running = False
    
    def connect_arduino(self):
        """Connect to Arduino"""
        if Config.SIMULATE_HARDWARE:
            print("SIMULATION MODE: Arduino connection simulated")
            self.connected = True
            return True
        
        try:
            # Auto-detect Arduino port
            ports = self._find_arduino_ports()
            
            if not ports:
                print("No Arduino found")
                return False
            
            for port in ports:
                try:
                    print(f"Trying to connect to {port}...")
                    self.arduino = serial.Serial(
                        port=port,
                        baudrate=Config.ARDUINO_BAUD,
                        timeout=1
                    )
                    
                    # Wait for Arduino to reset
                    time.sleep(2)
                    
                    # Test communication
                    self.arduino.write(b"PING\n")
                    response = self.arduino.readline().decode().strip()
                    
                    if "PONG" in response:
                        print(f"Connected to Arduino on {port}")
                        self.connected = True
                        
                        # Start monitoring thread
                        self.running = True
                        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
                        self.monitor_thread.start()
                        
                        return True
                    else:
                        self.arduino.close()
                        
                except Exception as e:
                    print(f"Failed to connect to {port}: {e}")
                    if self.arduino:
                        self.arduino.close()
            
            print("Failed to connect to any Arduino")
            return False
            
        except Exception as e:
            print(f"Arduino connection error: {e}")
            return False
    
    def _find_arduino_ports(self):
        """Find available Arduino ports"""
        import sys
        
        if sys.platform.startswith('win'):
            # Windows
            ports = [f'COM{i}' for i in range(1, 10)]
        elif sys.platform.startswith('linux'):
            # Linux
            ports = [f'/dev/ttyUSB{i}' for i in range(10)] + [f'/dev/ttyACM{i}' for i in range(10)]
        elif sys.platform.startswith('darwin'):
            # macOS
            ports = [f'/dev/tty.usbmodem{i}' for i in range(10)]
        else:
            ports = []
        
        # Also try configured port
        if Config.ARDUINO_PORT not in ports:
            ports.insert(0, Config.ARDUINO_PORT)
        
        return ports
    
    def _monitor_loop(self):
        """Monitor Arduino communication"""
        while self.running and self.connected and self.arduino:
            try:
                # Read any incoming data
                if self.arduino.in_waiting > 0:
                    data = self.arduino.readline().decode().strip()
                    if data:
                        self._process_arduino_data(data)
                
                time.sleep(0.01)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(1)
    
    def _process_arduino_data(self, data):
        """Process data from Arduino"""
        print(f"Arduino: {data}")
        
        # Handle different message types
        if "BATTERY" in data:
            try:
                self.battery_level = float(data.split(":")[1].strip())
            except:
                pass
        elif "OBSTACLE" in data:
            print("Obstacle detected by sensors!")
        elif "ERROR" in data:
            print(f"Arduino error: {data}")
    
    def send_command(self, command, value=None):
        """Send command to Arduino"""
        if not self.connected:
            print(f"SIMULATED: {command}")
            return True
        
        if self.emergency_stop and command != "STOP":
            print("EMERGENCY STOP ACTIVE - ignoring command")
            return False
        
        try:
            if value is not None:
                full_command = f"{command}:{value}\n"
            else:
                full_command = f"{command}\n"
            
            self.arduino.write(full_command.encode())
            self.commands_executed += 1
            
            # Log command
            self.db.log_movement(
                command=command,
                position=self.navigator.position,
                heading=self.navigator.heading,
                distance=0,
                obstacle=False
            )
            
            return True
            
        except Exception as e:
            print(f"Error sending command: {e}")
            return False
    
    def manual_control(self, command, duration=None):
        """Manual control commands"""
        commands = {
            'forward': 'FORWARD',
            'backward': 'BACKWARD',
            'left': 'TURN_LEFT',
            'right': 'TURN_RIGHT',
            'stop': 'STOP'
        }
        
        if command not in commands:
            print(f"Unknown command: {command}")
            return False
        
        arduino_command = commands[command]
        
        if command == 'stop':
            self.emergency_stop = True
            self.send_command('STOP')
            print("Emergency stop activated")
            return True
        
        # Clear emergency stop if moving
        self.emergency_stop = False
        
        if duration:
            # Start movement
            self.send_command(arduino_command)
            
            # Wait for duration
            time.sleep(duration)
            
            # Stop
            self.send_command('STOP')
        else:
            # Single command
            self.send_command(arduino_command)
        
        return True
    
    def autonomous_navigation(self):
        """Start autonomous navigation"""
        print("Starting autonomous navigation...")
        
        # Run exploration in a separate thread
        nav_thread = threading.Thread(target=self.navigator.autonomous_exploration, args=(50,))
        nav_thread.daemon = True
        nav_thread.start()
        
        return True
    
    def get_camera_frame(self, with_overlay=True):
        """Get current camera frame"""
        if with_overlay:
            # Get environment analysis for overlay
            env = self.navigator.check_environment()
            return self.camera.get_frame_with_overlay(env)
        else:
            return self.camera.capture_frame()
    
    def get_status(self):
        """Get complete robot status"""
        nav_status = self.navigator.get_status()
        
        return {
            'connected': self.connected,
            'camera_type': self.camera.camera_type.value,
            'camera_index': self.camera.camera_index,
            'emergency_stop': self.emergency_stop,
            'battery': self.battery_level,
            'speed': self.current_speed,
            'commands_executed': self.commands_executed,
            'navigation': nav_status,
            'database_stats': {
                'visited_cells': len(self.navigator.visited_cells),
                'obstacles_recorded': len(self.navigator.obstacle_cells)
            }
        }
    
    def get_map_data(self):
        """Get map data for visualization"""
        return self.db.get_exploration_map()
    
    def save_logs(self):
        """Save all logs"""
        print("Saving logs...")
        # Additional logging can be added here
        return True
    
    def shutdown(self):
        """Shutdown robot safely"""
        print("Shutting down robot...")
        
        self.running = False
        self.emergency_stop = True
        
        # Stop motors
        if self.connected:
            self.send_command('STOP')
        
        # Disconnect Arduino
        if self.arduino:
            self.arduino.close()
        
        # Release camera
        self.camera.release()
        
        # Save logs
        self.save_logs()
        
        print("Robot shutdown complete")