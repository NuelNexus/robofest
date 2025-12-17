# main.py
import time
import sys
from robot_control import RobotControl

def main():
    # Initialize robot
    robot = RobotControl()
    
    # Connect to Arduino
    if not robot.connect_arduino():
        print("Failed to connect to Arduino. Please check:")
        print("1. Arduino is connected via USB")
        print("2. Correct COM port in config.py")
        print("3. Arduino code is uploaded")
        sys.exit(1)
    
    try:
        print("Robot Control System Ready")
        print("Commands: forward, backward, left, right, smooth_left, smooth_right, stop")
        print("Special commands: explore, navigate <target>, map, exit")
        
        while True:
            command = input("Enter command: ").strip().lower()
            
            if command == "exit":
                break
            elif command == "forward":
                robot.move_forward()
            elif command == "backward":
                robot.move_backward()
            elif command == "left":
                robot.turn_left()
            elif command == "right":
                robot.turn_right()
            elif command == "smooth_left":
                robot.smooth_left()
            elif command == "smooth_right":
                robot.smooth_right()
            elif command == "stop":
                robot.stop()
            elif command == "explore":
                robot.explore_room()
            elif command.startswith("navigate"):
                target = command[9:]  # Get text after "navigate "
                if target:
                    robot.navigate_to_target(target)
                else:
                    print("Please specify a target, e.g., 'navigate to the red chair'")
            elif command == "map":
                robot.generate_map()
                print("Map generated as 'robot_map.png'")
            elif command.startswith("speed"):
                try:
                    speed = int(command.split()[1])
                    robot.set_speed(speed)
                    print(f"Speed set to {speed}")
                except:
                    print("Usage: speed <0-255>")
            else:
                print("Unknown command")
                
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        robot.disconnect()
        print("System shutdown complete")

if __name__ == "__main__":
    main()