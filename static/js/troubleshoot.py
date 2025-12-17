# troubleshoot.py
import cv2
import sys

def test_cameras():
    """Test all available cameras"""
    print("Testing available cameras...")
    
    for camera_id in range(0, 5):  # Test cameras 0-4
        print(f"\nTrying camera {camera_id}...")
        
        # Try different backends
        backends = [
            ('DShow', cv2.CAP_DSHOW),
            ('MSMF', cv2.CAP_MSMF),
            ('V4L2', cv2.CAP_V4L2),
            ('ANY', cv2.CAP_ANY)
        ]
        
        for backend_name, backend in backends:
            try:
                print(f"  Backend: {backend_name}...", end=' ')
                cap = cv2.VideoCapture(camera_id, backend)
                
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        print(f"SUCCESS - Resolution: {frame.shape[1]}x{frame.shape[0]}")
                        cap.release()
                        return camera_id, backend_name
                    else:
                        print("FAILED - Can't read frame")
                    cap.release()
                else:
                    print("FAILED - Can't open")
            except Exception as e:
                print(f"ERROR - {str(e)[:50]}")
    
    print("\nNo cameras found. Using simulated mode.")
    return None, None

if __name__ == '__main__':
    camera_id, backend = test_cameras()
    
    if camera_id is not None:
        print(f"\nRecommended configuration:")
        print(f"CAMERA_ID = {camera_id}")
        print(f"# Use backend: {backend}")
    else:
        print("\nSet SIMULATE_CAMERA = True in config.py")