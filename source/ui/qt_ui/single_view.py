from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
import cv2

class SingleStationView(QWidget):
    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.system = system
        self.dump_id = None # Set when showing
        
        # Style
        self.setObjectName("SingleStationView")
        
        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        # 1. Header
        self._build_header()
        
        # 2. Main Content (Images)
        self._build_image_area()
        
        # 3. Footer / Details
        self._build_footer()
        
        # Placeholder State
        self.update_state({'dump_id': '-', 'state': 'SELECT STATION', 'status': 'IDLE', 'lpr': '-'})

    def set_station(self, dump_id):
        self.dump_id = dump_id
        self.title_lbl.setText(dump_id)
        # Trigger immediate update if possible
        self.update_view()

    def _build_header(self):
        header_widget = QWidget()
        h_layout = QHBoxLayout(header_widget)
        h_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title
        self.title_lbl = QLabel("SELECT STATION")
        self.title_lbl.setStyleSheet("font-size: 32px; font-weight: 800; color: #1E3A8A;")
        h_layout.addWidget(self.title_lbl)
        
        h_layout.addStretch()
        
        # Status
        self.status_lbl = QLabel("● IDLE")
        self.status_lbl.setStyleSheet("font-size: 24px; font-weight: 700; color: #64748B;")
        h_layout.addWidget(self.status_lbl)
        
        self.main_layout.addWidget(header_widget)

    def _build_image_area(self):
        # We want 2 images. On 1080p (16:9), if we stack them vertically, we get two 1920x540 strips (32:9).
        # Camera is 16:9.
        # If we fill width 1700px -> Height = 1700 * 9 / 16 = 956px.
        # Two images height = 1912px > 1080px.
        # So Vertical Stack WILL SCROLL or SCALE DOWN.
        # If we do Horizontal Stack: Width 850px -> Height 478px.
        # 478px is less than screen height. Fits well.
        # Decision: Side-by-Side for Fullscreen Single View to maximize 16:9 coverage?
        # OR Grid User asked for "Full Screen".
        # Let's try Vertical but allow scaling (Downsizing to fit height).
        
        self.img_container = QWidget()
        self.img_layout = QVBoxLayout(self.img_container) # Stacked Vertical usually preferred for surveillance
        
        # Img 1
        self.img_lpr = QLabel()
        self.img_lpr.setAlignment(Qt.AlignCenter)
        self.img_lpr.setStyleSheet("background-color: transparent; border-radius: 8px;")
        self.img_lpr.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.img_layout.addWidget(self.img_lpr, 1)
        
        # Img 2
        self.img_ai = QLabel()
        self.img_ai.setAlignment(Qt.AlignCenter)
        self.img_ai.setStyleSheet("background-color: transparent; border-radius: 8px;")
        self.img_ai.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.img_layout.addWidget(self.img_ai, 1)
        
        self.main_layout.addWidget(self.img_container, 1) # Expand

    def _build_footer(self):
        f_widget = QWidget()
        f_layout = QHBoxLayout(f_widget)
        
        self.info_lbl = QLabel("LPR Result: -")
        self.info_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E3A8A;")
        f_layout.addWidget(self.info_lbl)
        
        self.main_layout.addWidget(f_widget)

    def update_view(self):
        if not self.dump_id: return
        
        # Fetch State
        # In a real app, maybe get single state from system
        states = self.system.get_processor_states()
        target = next((s for s in states if s['dump_id'] == self.dump_id), None)
        
        if target:
            self.update_state(target)
            
        # Fetch Frames
        frames = self.system.get_latest_frames(self.dump_id)
        if frames:
            self.update_images(frames)

    def update_state(self, state_data):
        # Header
        self.title_lbl.setText(state_data.get('dump_id', '-'))
        
        status = state_data.get('status')
        state = state_data.get('state')
        
        color = "#22C55E" if status == 'RUNNING' else "#EF4444"
        self.status_lbl.setText(f"● {state}")
        self.status_lbl.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {color};")
        
        # Footer
        self.info_lbl.setText(f"LPR: {state_data.get('lpr', '-')}")

    def update_images(self, frames):
        self._set_image(self.img_lpr, frames.get('CH101'))
        self._set_image(self.img_ai, frames.get('CH201'))

    def _set_image(self, label, cv_frame):
        if cv_frame is None: return
        
        # Keep high res for single view? Or 720p?
        # Let's go 720p (1280x720) for better quality on full screen
        resized = cv2.resize(cv_frame, (1280, 720), interpolation=cv2.INTER_AREA)
        
        height, width, channel = resized.shape
        bytes_per_line = 3 * width
        q_img = QImage(resized.data, width, height, bytes_per_line, QImage.Format_BGR888)
        
        pixmap = QPixmap.fromImage(q_img)
        
        if not label.size().isEmpty():
            pixmap = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
        label.setPixmap(pixmap)
