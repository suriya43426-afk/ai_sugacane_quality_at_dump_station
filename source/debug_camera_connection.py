import cv2
import os
import time
import configparser
import sys

# Setup paths
# Since this is in source/, BASE_DIR is parent.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(BASE_DIR, "config.txt")

print(f"Loading config from: {CONFIG_PATH}")
if not os.path.exists(CONFIG_PATH):
    print("Config file not found!")
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8-sig")

# Get Config
try:
    NVR = config["NVR1"]
    IP = NVR.get("camera_ip")
    USER = NVR.get("camera_username")
    PASS = NVR.get("camera_password")
except KeyError:
    print("Error: Could not find [NVR1] section or keys in config.")
    # Fallback/Debug Help
    print("Valid sections:", config.sections())
    sys.exit(1)

print(f"Target IP: {IP}")

# 1. Ping Test
print(f"\n[Test 1] Pinging {IP}...")
response = os.system(f"ping -n 1 {IP}")
if response == 0:
    print(">>> Ping Successful!")
else:
    print(">>> Ping Failed! Check network cable or firewall. (If ping is blocked, this might be false negative)")

from urllib.parse import quote

# 2. RTSP Test (Standard)
# URL Encode credentials
safe_user = quote(USER, safe="")
safe_pass = quote(PASS, safe="")

url = f"rtsp://{safe_user}:{safe_pass}@{IP}/Streaming/channels/101"
safe_url_display = url.replace(safe_pass, "****") if PASS else url
print(f"\n[Test 2] Connecting to OpenCV (TCP Forced): {safe_url_display}")

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
cap = cv2.VideoCapture(url)
if cap.isOpened():
    print(">>> Connection Successful!")
    ret, frame = cap.read()
    if ret:
        print(f">>> Read frame successfully: {frame.shape}")
    else:
        print(">>> Opened, but failed to read frame.")
    cap.release()
else:
    print(">>> Connection Failed!")

# 3. RTSP Test (UDP - default)
print(f"\n[Test 3] Connecting to OpenCV (UDP/Default): {safe_url}")
if "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
    del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

cap = cv2.VideoCapture(url)
if cap.isOpened():
    print(">>> Connection Successful (UDP)!")
    cap.release()
else:
    print(">>> Connection Failed (UDP)!")
    
print("\nDone.")
