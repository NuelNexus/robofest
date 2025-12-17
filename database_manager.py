# database_manager.py
import sqlite3
import json
import time
from datetime import datetime
import numpy as np
from config import Config

class DatabaseManager:
    def __init__(self):
        self.db_file = Config.DATABASE_FILE
        self.init_database()
    
    def init_database(self):
        """Initialize database with required tables"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # Visited locations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visited_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grid_x INTEGER,
                grid_y INTEGER,
                visit_count INTEGER DEFAULT 1,
                last_visited TIMESTAMP,
                obstacle_detected BOOLEAN DEFAULT 0,
                distance REAL DEFAULT 999.0
            )
        ''')
        
        # Movement history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movement_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                command TEXT,
                position_x REAL,
                position_y REAL,
                heading REAL,
                distance_measurement REAL,
                obstacle_detected BOOLEAN
            )
        ''')
        
        # Obstacle map table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS obstacle_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grid_x INTEGER,
                grid_y INTEGER,
                confidence REAL,
                detected_time TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def record_visit(self, grid_x, grid_y, obstacle=False, distance=999.0):
        """Record a visit to a grid cell"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, visit_count FROM visited_locations 
            WHERE grid_x = ? AND grid_y = ?
        ''', (grid_x, grid_y))
        
        result = cursor.fetchone()
        
        if result:
            # Update existing record
            new_count = result[1] + 1
            cursor.execute('''
                UPDATE visited_locations 
                SET visit_count = ?, last_visited = ?, 
                    obstacle_detected = ?, distance = ?
                WHERE id = ?
            ''', (new_count, datetime.now(), obstacle, distance, result[0]))
        else:
            # Insert new record
            cursor.execute('''
                INSERT INTO visited_locations 
                (grid_x, grid_y, visit_count, last_visited, obstacle_detected, distance)
                VALUES (?, ?, 1, ?, ?, ?)
            ''', (grid_x, grid_y, datetime.now(), obstacle, distance))
        
        conn.commit()
        conn.close()
    
    def get_visit_count(self, grid_x, grid_y):
        """Get visit count for a grid cell"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT visit_count FROM visited_locations 
            WHERE grid_x = ? AND grid_y = ?
        ''', (grid_x, grid_y))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else 0
    
    def is_overvisited(self, grid_x, grid_y):
        """Check if a cell has been visited too many times"""
        count = self.get_visit_count(grid_x, grid_y)
        return count >= Config.MAX_VISITS_PER_CELL
    
    def get_least_visited_direction(self, current_x, current_y, headings):
        """Find the direction with least visited cells"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        best_direction = None
        min_visits = float('inf')
        
        for heading in headings:
            # Calculate adjacent cell based on heading
            dx, dy = self._heading_to_vector(heading)
            adj_x, adj_y = current_x + dx, current_y + dy
            
            cursor.execute('''
                SELECT visit_count FROM visited_locations 
                WHERE grid_x = ? AND grid_y = ?
            ''', (adj_x, adj_y))
            
            result = cursor.fetchone()
            visits = result[0] if result else 0
            
            if visits < min_visits:
                min_visits = visits
                best_direction = heading
        
        conn.close()
        return best_direction
    
    def _heading_to_vector(self, heading):
        """Convert heading to grid vector"""
        rad = np.radians(heading)
        dx = int(np.cos(rad))
        dy = int(np.sin(rad))
        return dx, dy
    
    def log_movement(self, command, position, heading, distance, obstacle):
        """Log a movement command"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO movement_history 
            (timestamp, command, position_x, position_y, heading, distance_measurement, obstacle_detected)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now(), command, position[0], position[1], heading, distance, obstacle))
        
        conn.commit()
        conn.close()
    
    def record_obstacle(self, grid_x, grid_y, confidence=1.0):
        """Record an obstacle location"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO obstacle_map (grid_x, grid_y, confidence, detected_time)
            VALUES (?, ?, ?, ?)
        ''', (grid_x, grid_y, confidence, datetime.now()))
        
        conn.commit()
        conn.close()
    
    def get_nearby_obstacles(self, grid_x, grid_y, radius=3):
        """Get obstacles within radius"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT grid_x, grid_y, confidence FROM obstacle_map
            WHERE ABS(grid_x - ?) <= ? AND ABS(grid_y - ?) <= ?
        ''', (grid_x, radius, grid_y, radius))
        
        obstacles = cursor.fetchall()
        conn.close()
        
        return obstacles
    
    def get_exploration_map(self):
        """Get complete exploration data"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('SELECT grid_x, grid_y, visit_count FROM visited_locations')
        visited = cursor.fetchall()
        
        cursor.execute('SELECT grid_x, grid_y, confidence FROM obstacle_map')
        obstacles = cursor.fetchall()
        
        conn.close()
        
        return {
            'visited': visited,
            'obstacles': obstacles
        }
    
    def clear_history(self):
        """Clear all history (for testing)"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM visited_locations')
        cursor.execute('DELETE FROM movement_history')
        cursor.execute('DELETE FROM obstacle_map')
        
        conn.commit()
        conn.close()