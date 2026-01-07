import os
import sys

# Prioritize TCP for reliability. Remove 'nobuffer' to fix gray artifacts.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000"

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
