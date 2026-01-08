import os
import sys

# Max Quality: TCP, Large Buffer, High Latency Allowed (5s)
# Max Quality: TCP, Large Buffer, High Latency Allowed (5s) -> Optimized for Low Latency
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"

# Add project root to path for absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

from source.core.system import SugarcaneSystem
from source.ui.qt_main import QtMainWindow
from PySide6.QtWidgets import QApplication

if __name__ == "__main__":
    # 1. Initialize Core System
    system = SugarcaneSystem()
    system.start_processors()
    
    # 2. Launch GUI (Qt)
    app = QApplication(sys.argv)
    
    # Apply global stylesheet if needed (e.g. font)
    font = app.font()
    font.setFamily("Segoe UI")
    app.setFont(font)
    
    window = QtMainWindow(system)
    window.show()
    
    sys.exit(app.exec())
