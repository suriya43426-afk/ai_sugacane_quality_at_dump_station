from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QColor

class StationCard(QFrame):
    def __init__(self, dump_id, parent=None):
        super().__init__(parent)
        self.dump_id = dump_id
        
        # Style
        self.setObjectName("StationCard")
        # Reduced padding for compact realtime view
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8) 
        self.layout.setSpacing(5)
        
        # 1. Header
        self._build_header()
        
        # 2. Images (Expandable)
        self._build_images()
        
        # 3. Footer
        self._build_footer()

    def _build_header(self):
        header_layout = QHBoxLayout()
        header_layout.setSpacing(5)
        
        # Station Title
        self.title_lbl = QLabel(self.dump_id)
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 14px; color: #1E3A8A;")
        header_layout.addWidget(self.title_lbl)
        
        header_layout.addStretch()
        
        # Status Dot
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("font-size: 14px; color: #CBD5E1;")
        header_layout.addWidget(self.status_dot)
        
        self.layout.addLayout(header_layout)

    def _build_images(self):
        # Image 1 (LPR View)
        self.img_lpr = QLabel()
        self.img_lpr.setAlignment(Qt.AlignCenter)
        self.img_lpr.setStyleSheet("background-color: transparent; border-radius: 4px;") 
        self.img_lpr.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        # self.img_lpr.setScaledContents(True) # Disable to control Aspect Ratio manually
        self.layout.addWidget(self.img_lpr, 1) 
        
        # Image 2 (AI View)
        self.img_ai = QLabel()
        self.img_ai.setAlignment(Qt.AlignCenter)
        self.img_ai.setStyleSheet("background-color: transparent; border-radius: 4px;")
        self.img_ai.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        # self.img_ai.setScaledContents(True)
        self.layout.addWidget(self.img_ai, 1)

    def _build_footer(self):
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(5)
        
        # State Badge
        self.state_lbl = QLabel("IDLE")
        self.state_lbl.setStyleSheet("background-color: #E2E8F0; color: #64748B; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;")
        footer_layout.addWidget(self.state_lbl)
        
        footer_layout.addStretch()
        
        # LPR Text
        self.lpr_lbl = QLabel("-")
        self.lpr_lbl.setStyleSheet("font-weight: bold; color: #1E3A8A; font-size: 14px;")
        footer_layout.addWidget(self.lpr_lbl)
        
        self.layout.addLayout(footer_layout)

    def update_state(self, state_data):
        # Update Status Dot
        status = state_data.get('status')
        is_running = status == 'RUNNING'
        color = "#22C55E" if is_running else "#EF4444" 
        self.status_dot.setStyleSheet(f"font-size: 14px; color: {color};")
        
        # Update State Badge
        state_text = state_data.get('state', '-')
        self.state_lbl.setText(state_text)
        
        # Update LPR
        self.lpr_lbl.setText(f"{state_data.get('lpr', '-')}")

    def update_images(self, frames):
        if not frames: return
        self._set_image(self.img_lpr, frames.get('CH101'))
        self._set_image(self.img_ai, frames.get('CH201'))

    def _set_image(self, label, cv_frame):
        if cv_frame is None: return
        
        # 1. Resize to Low Res 16:9 (640x360) to reduce load & enforce ratio source
        import cv2
        resized = cv2.resize(cv_frame, (640, 360), interpolation=cv2.INTER_AREA)
        
        height, width, channel = resized.shape
        bytes_per_line = 3 * width
        q_img = QImage(resized.data, width, height, bytes_per_line, QImage.Format_BGR888)
        
        # 2. Convert to Pixmap
        pixmap = QPixmap.fromImage(q_img)
        
        # 3. Scale to Label Size with Aspect Ratio
        if not label.size().isEmpty():
            pixmap = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
        label.setPixmap(pixmap)
