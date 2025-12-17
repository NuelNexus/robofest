# navigation_system.py
import numpy as np
import time
from enum import Enum
from config import Config
from database_manager import DatabaseManager

class NavigationState(Enum):
    EXPLORING = "exploring"
    AVOIDING = "avoiding"
    RETURNING = "returning"
    STOPPED = "stopped"

class NavigationSystem:
    def __init__(self, camera_manager, database_manager):
        self.camera = camera_manager
        self.db = database_manager
        self.state = NavigationState.EXPLORING
        
        # Current position and heading
        self.position = (Config.MAP_SIZE[0] // 2, Config.MAP_SIZE[1] // 2)  # Start in center
        self.heading = 0  # Degrees, 0 = East, 90 = North
        
        # Navigation parameters
        self.visited_cells = set()
        self.obstacle_cells = set()
        self.path_history = []
        
        # Statistics
        self.total_distance = 0
        self.obstacles_avoided = 0
        self.start_time = time.time()
    
    def world_to_grid(self, world_x, world_y):
        """Convert world coordinates to grid coordinates"""
        grid_x = int(world_x / Config.GRID_SIZE)
        grid_y = int(world_y / Config.GRID_SIZE)
        
        # Ensure within bounds
        grid_x = max(0, min(Config.MAP_SIZE[0] - 1, grid_x))
        grid_y = max(0, min(Config.MAP_SIZE[1] - 1, grid_y))
        
        return grid_x, grid_y
    
    def update_position(self, distance_moved, direction_change=0):
        """Update robot position based on movement"""
        # Update heading
        self.heading = (self.heading + direction_change) % 360
        
        # Convert heading to radians
        heading_rad = np.radians(self.heading)
        
        # Calculate movement in grid units
        dx = distance_moved * np.cos(heading_rad) / Config.GRID_SIZE
        dy = distance_moved * np.sin(heading_rad) / Config.GRID_SIZE
        
        # Update position
        self.position = (
            self.position[0] + dx,
            self.position[1] + dy
        )
        
        # Ensure within bounds
        self.position = (
            max(0, min(Config.MAP_SIZE[0] - 1, self.position[0])),
            max(0, min(Config.MAP_SIZE[1] - 1, self.position[1]))
        )
        
        # Record visit
        grid_x, grid_y = int(self.position[0]), int(self.position[1])
        self.visited_cells.add((grid_x, grid_y))
        self.path_history.append((grid_x, grid_y, self.heading))
        
        # Record in database
        self.db.record_visit(grid_x, grid_y, obstacle=False)
        
        return grid_x, grid_y
    
    def check_environment(self):
        """Check environment and calculate distances"""
        frame = self.camera.capture_frame()
        if frame is None:
            return None
        
        analysis = self.camera.analyze_frame_for_navigation(frame)
        
        # Get current grid position
        grid_x, grid_y = int(self.position[0]), int(self.position[1])
        
        # Check if current cell is overvisited
        if self.db.is_overvisited(grid_x, grid_y):
            analysis['cell_overvisited'] = True
        else:
            analysis['cell_overvisited'] = False
        
        # Check for nearby obstacles in database
        nearby_obstacles = self.db.get_nearby_obstacles(grid_x, grid_y, radius=2)
        analysis['database_obstacles'] = len(nearby_obstacles)
        
        # If obstacle detected, record it
        if analysis['closest_distance'] <= Config.MIN_DISTANCE_THRESHOLD:
            # Calculate obstacle position in grid
            obstacle_distance = analysis['closest_distance'] / 100.0  # Convert to meters
            obstacle_direction = analysis['closest_direction']
            
            # Estimate obstacle grid position
            obstacle_grid_x, obstacle_grid_y = self._estimate_obstacle_position(
                grid_x, grid_y, obstacle_distance, obstacle_direction
            )
            
            # Record obstacle in database
            if 0 <= obstacle_grid_x < Config.MAP_SIZE[0] and 0 <= obstacle_grid_y < Config.MAP_SIZE[1]:
                self.db.record_obstacle(obstacle_grid_x, obstacle_grid_y, confidence=0.8)
                self.obstacle_cells.add((obstacle_grid_x, obstacle_grid_y))
                self.obstacles_avoided += 1
        
        return analysis
    
    def _estimate_obstacle_position(self, robot_x, robot_y, distance, direction):
        """Estimate obstacle position in grid"""
        # Convert direction to angle offset
        if direction == 'center':
            angle_offset = 0
        elif direction == 'left':
            angle_offset = -30  # 30 degrees left
        else:  # right
            angle_offset = 30   # 30 degrees right
        
        # Calculate obstacle position
        obstacle_angle = (self.heading + angle_offset) % 360
        obstacle_angle_rad = np.radians(obstacle_angle)
        
        # Convert distance to grid units
        grid_distance = distance * 100 / Config.GRID_SIZE  # Convert cm to grid cells
        
        # Calculate obstacle grid coordinates
        obstacle_x = robot_x + grid_distance * np.cos(obstacle_angle_rad)
        obstacle_y = robot_y + grid_distance * np.sin(obstacle_angle_rad)
        
        return int(obstacle_x), int(obstacle_y)
    
    def decide_next_move(self, environment_analysis):
        """Decide next move based on environment analysis"""
        if environment_analysis is None:
            return 'STOP', "No environment data"
        
        grid_x, grid_y = int(self.position[0]), int(self.position[1])
        
        # Emergency stop if object too close
        if environment_analysis['closest_distance'] <= Config.MIN_DISTANCE_THRESHOLD:
            self.state = NavigationState.AVOIDING
            return 'STOP', f"Object too close: {environment_analysis['closest_distance']:.1f}cm"
        
        # Check if current cell is overvisited
        if environment_analysis['cell_overvisited']:
            # Find least visited adjacent cell
            headings = [0, 90, 180, 270]  # East, North, West, South
            best_heading = self.db.get_least_visited_direction(grid_x, grid_y, headings)
            
            if best_heading is not None:
                turn_amount = self._calculate_turn_amount(self.heading, best_heading)
                if turn_amount > 0:
                    return 'TURN_LEFT', f"Avoiding overvisited cell (turn {turn_amount}°)"
                else:
                    return 'TURN_RIGHT', f"Avoiding overvisited cell (turn {-turn_amount}°)"
        
        # Normal navigation based on camera analysis
        action = environment_analysis['recommended_action']
        
        if action == 'TURN_LEFT':
            reason = f"Clear path left ({environment_analysis['left_distance']:.1f}cm)"
        elif action == 'TURN_RIGHT':
            reason = f"Clear path right ({environment_analysis['right_distance']:.1f}cm)"
        else:  # MOVE_FORWARD
            reason = f"Clear path ahead ({environment_analysis['center_distance']:.1f}cm)"
        
        return action, reason
    
    def _calculate_turn_amount(self, current_heading, target_heading):
        """Calculate minimum turn amount to target heading"""
        diff = (target_heading - current_heading) % 360
        if diff > 180:
            diff -= 360
        return diff
    
    def execute_move(self, action, duration=Config.MOVEMENT_DURATION):
        """Execute a movement command"""
        grid_x, grid_y = int(self.position[0]), int(self.position[1])
        
        if action == 'MOVE_FORWARD':
            # Simulate moving forward (grid cells)
            distance_moved = 2  # Approximately 2 grid cells
            self.update_position(distance_moved)
            command = "FORWARD"
            
        elif action == 'TURN_LEFT':
            # Simulate turning left 30 degrees
            self.update_position(0, direction_change=30)
            command = "TURN_LEFT"
            
        elif action == 'TURN_RIGHT':
            # Simulate turning right 30 degrees
            self.update_position(0, direction_change=-30)
            command = "TURN_RIGHT"
            
        elif action == 'STOP':
            command = "STOP"
            return command
        
        else:
            command = "STOP"
            return command
        
        # Log the movement
        self.db.log_movement(
            command=command,
            position=self.position,
            heading=self.heading,
            distance=0,  # Would be actual distance in real implementation
            obstacle=False
        )
        
        return command
    
    def autonomous_exploration(self, max_steps=100):
        """Perform autonomous exploration"""
        print("Starting autonomous exploration...")
        self.state = NavigationState.EXPLORING
        
        for step in range(max_steps):
            print(f"\nStep {step + 1}/{max_steps}")
            print(f"Position: ({self.position[0]:.1f}, {self.position[1]:.1f})")
            print(f"Heading: {self.heading:.0f}°")
            
            # Check environment
            env = self.check_environment()
            if env:
                print(f"Closest object: {env['closest_distance']:.1f}cm {env['closest_direction']}")
            
            # Decide next move
            action, reason = self.decide_next_move(env)
            print(f"Decision: {action} - {reason}")
            
            # Execute move
            command = self.execute_move(action)
            print(f"Executed: {command}")
            
            # Update state
            if action == 'STOP':
                print("Stopping exploration due to obstacle")
                break
            
            time.sleep(0.5)  # Simulate movement time
        
        print(f"\nExploration complete!")
        print(f"Visited {len(self.visited_cells)} unique cells")
        print(f"Avoided {self.obstacles_avoided} obstacles")
        print(f"Total path length: {len(self.path_history)} steps")
        
        self.state = NavigationState.STOPPED
    
    def get_status(self):
        """Get current navigation status"""
        return {
            'state': self.state.value,
            'position': self.position,
            'heading': self.heading,
            'visited_cells': len(self.visited_cells),
            'obstacle_cells': len(self.obstacle_cells),
            'path_length': len(self.path_history),
            'obstacles_avoided': self.obstacles_avoided,
            'exploration_time': time.time() - self.start_time
        }