# map_generator.py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from config import Config
import json

class MapGenerator:
    def __init__(self):
        self.map_grid = np.zeros(Config.MAP_SIZE, dtype=int)
        self.visited = np.zeros(Config.MAP_SIZE, dtype=bool)
        self.obstacles = []
        self.path = []
        
    def world_to_grid(self, world_coords):
        """Convert world coordinates to grid coordinates"""
        x, y = world_coords
        grid_x = int(x / Config.GRID_SIZE) + Config.MAP_SIZE[0] // 2
        grid_y = int(y / Config.GRID_SIZE) + Config.MAP_SIZE[1] // 2
        
        # Clamp to map bounds
        grid_x = max(0, min(Config.MAP_SIZE[0] - 1, grid_x))
        grid_y = max(0, min(Config.MAP_SIZE[1] - 1, grid_y))
        
        return (grid_x, grid_y)
    
    def update_map(self, position, heading):
        """Update map with current position"""
        grid_pos = self.world_to_grid(position)
        
        # Mark as visited
        self.visited[grid_pos] = True
        self.path.append((grid_pos, heading))
        
        # Mark surrounding cells as free space
        radius = 2
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nx, ny = grid_pos[0] + dx, grid_pos[1] + dy
                if 0 <= nx < Config.MAP_SIZE[0] and 0 <= ny < Config.MAP_SIZE[1]:
                    if self.map_grid[nx, ny] == 0:  # Only mark if not obstacle
                        self.map_grid[nx, ny] = 1  # Free space
    
    def add_obstacle(self, position, size=1):
        """Add an obstacle at the given position"""
        grid_pos = self.world_to_grid(position)
        
        # Mark obstacle cells
        for dx in range(-size, size + 1):
            for dy in range(-size, size + 1):
                nx, ny = grid_pos[0] + dx, grid_pos[1] + dy
                if 0 <= nx < Config.MAP_SIZE[0] and 0 <= ny < Config.MAP_SIZE[1]:
                    self.map_grid[nx, ny] = 2  # Obstacle
                    self.obstacles.append((nx, ny))
    
    def generate_map(self):
        """Generate visualization of the map"""
        fig, ax = plt.subplots(figsize=(10, 10))
        
        # Create colormap: 0=unknown, 1=free, 2=obstacle
        cmap = plt.cm.colors.ListedColormap(['gray', 'white', 'black'])
        bounds = [0, 1, 2, 3]
        norm = plt.cm.colors.BoundaryNorm(bounds, cmap.N)
        
        # Plot grid
        ax.imshow(self.map_grid.T, cmap=cmap, norm=norm, 
                 origin='lower', interpolation='none')
        
        # Plot path
        if self.path:
            path_x = [pos[0][0] for pos in self.path]
            path_y = [pos[0][1] for pos in self.path]
            ax.plot(path_x, path_y, 'b-', linewidth=2, alpha=0.7)
            
            # Plot arrows for heading
            for (x, y), heading in self.path[-10:]:  # Last 10 positions
                dx = 2 * np.cos(np.radians(heading))
                dy = 2 * np.sin(np.radians(heading))
                ax.arrow(x, y, dx, dy, head_width=1, head_length=1, fc='red', ec='red')
        
        # Add grid lines
        ax.set_xticks(np.arange(-0.5, Config.MAP_SIZE[0], 1), minor=True)
        ax.set_yticks(np.arange(-0.5, Config.MAP_SIZE[1], 1), minor=True)
        ax.grid(which='minor', color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
        
        # Labels and title
        ax.set_xlabel('X (grid cells)')
        ax.set_ylabel('Y (grid cells)')
        ax.set_title('Robot Exploration Map')
        
        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='gray', edgecolor='black', label='Unknown'),
            Patch(facecolor='white', edgecolor='black', label='Free Space'),
            Patch(facecolor='black', edgecolor='black', label='Obstacle'),
            Patch(facecolor='blue', edgecolor='blue', label='Robot Path'),
            Patch(facecolor='red', edgecolor='red', label='Heading')
        ]
        ax.legend(handles=legend_elements, loc='upper right')
        
        plt.tight_layout()
        
    def save_map(self, filename='robot_map.png'):
        """Save map to file"""
        self.generate_map()
        plt.savefig(filename, dpi=150)
        plt.close()
        
        # Also save map data
        map_data = {
            'grid': self.map_grid.tolist(),
            'visited': self.visited.tolist(),
            'obstacles': self.obstacles,
            'path': self.path
        }
        
        with open('map_data.json', 'w') as f:
            json.dump(map_data, f)
    
    def load_map(self, filename='map_data.json'):
        """Load map from file"""
        with open(filename, 'r') as f:
            map_data = json.load(f)
            
        self.map_grid = np.array(map_data['grid'])
        self.visited = np.array(map_data['visited'])
        self.obstacles = map_data['obstacles']
        self.path = map_data['path']