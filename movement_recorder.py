# movement_recorder.py
import json
import time
from datetime import datetime
import numpy as np

class MovementRecorder:
    def __init__(self):
        self.movements = []
        self.start_time = time.time()
        
    def record_movement(self, command, position, heading):
        """Record a movement command with timestamp and position"""
        movement = {
            'timestamp': datetime.now().isoformat(),
            'command': command,
            'position': position,
            'heading': heading,
            'time_elapsed': time.time() - self.start_time
        }
        self.movements.append(movement)
        
    def save_to_file(self, filename='movement_log.json'):
        """Save movement history to JSON file"""
        with open(filename, 'w') as f:
            json.dump(self.movements, f, indent=2)
            
    def get_movement_history(self):
        """Return complete movement history"""
        return self.movements
    
    def clear_history(self):
        """Clear movement history"""
        self.movements = []
        self.start_time = time.time()