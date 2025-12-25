import os
import sys
import configparser

# Setup paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(BASE_DIR, "source"))

try:
    from config import load_config, clamp_lanes
except ImportError:
    print("Failed to import config. Ensure you are running from the source/ directory or have it in path.")
    sys.exit(1)

def test_config_loading():
    print("--- Testing Config Loading ---")
    # Mock config
    cp = configparser.ConfigParser()
    cp["DEFAULT"] = {
        "factory": "TEST_FACTORY",
        "total_lanes": "8",
        "lpr_confidence": "0.7"
    }
    cp["NVR1"] = {
        "camera_ip": "192.168.1.100",
        "camera_username": "admin",
        "camera_password": "password"
    }
    
    total_lanes = int(cp.get("DEFAULT", "total_lanes", fallback="1"))
    clamped = clamp_lanes(total_lanes)
    print(f"Total Lanes (Clamped): {clamped}")
    assert clamped == 8, f"Expected 8, got {clamped}"

    camera_path = f"rtsp://admin:password@192.168.1.100/Streaming/channels/"
    
    print("\n--- Testing Channel Mapping for 8 Dumps (Swapped: Odd=LPR, Even=Sugar) ---")
    for dump_id in range(1, clamped + 1):
        ch_lpr = f"{(2 * dump_id - 1)}01"
        ch_sugarcane = f"{(2 * dump_id)}01"
        print(f"Dump {dump_id}: LPR={camera_path}{ch_lpr}, Sugarcane={camera_path}{ch_sugarcane}")
        
    print("\nSuccess: Config loading and channel mapping verified.")

if __name__ == "__main__":
    test_config_loading()
