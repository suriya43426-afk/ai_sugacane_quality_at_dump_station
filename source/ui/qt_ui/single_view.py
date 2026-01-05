from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage

class SingleStationView(QWidget):
    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.system = system
        self.dump_id = None
        
        # Main Layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 15, 15)
        self.layout.setSpacing(20)
        
        # --- LEFT COLUMN: Video Feeds (VStack) ---
        self.video_col = QVBoxLayout()
        self.video_col.setSpacing(10)
        
        # LPR Camera
        self.frame_lpr = self._create_video_frame("FRONT CAMERA (LPR)")
        self.img_lpr = self.frame_lpr.findChild(QLabel, "video_label")
        self.video_col.addWidget(self.frame_lpr, 1)
        
        # AI Camera
        self.frame_ai = self._create_video_frame("TOP CAMERA (AI)")
        self.img_ai = self.frame_ai.findChild(QLabel, "video_label")
        self.video_col.addWidget(self.frame_ai, 1)
        
        self.layout.addLayout(self.video_col, 2) # Video takes more space
        
        # --- RIGHT COLUMN: Info Panel ---
        self.info_col = QVBoxLayout()
        self.info_col.setSpacing(15)
        
        # Header Info
        self.header_panel = QFrame()
        self.header_panel.setStyleSheet("background-color: white; border-radius: 12px; padding: 10px;")
        hp_layout = QVBoxLayout(self.header_panel)
        
        self.title_lbl = QLabel("STATION : -")
        self.title_lbl.setStyleSheet("font-size: 24px; font-weight: 800; color: #1E3A8A;")
        hp_layout.addWidget(self.title_lbl)
        
        self.state_lbl = QLabel("STATE : IDLE")
        self.state_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #64748B;")
        hp_layout.addWidget(self.state_lbl)
        
        self.info_col.addWidget(self.header_panel)
        
        # Data Panel
        self.data_panel = QFrame()
        self.data_panel.setStyleSheet("background-color: white; border-radius: 12px; padding: 20px;")
        dp_layout = QVBoxLayout(self.data_panel)
        dp_layout.setSpacing(20)
        
        # Metrics
        self.trash_val = self._add_info_row(dp_layout, "TRASH DETECTED", "0%", "#0EA5E9", large=True)
        self.lpr_val = self._add_info_row(dp_layout, "PLATE NUMBER", "-", "#0F172A")
        self.trans_val = self._add_info_row(dp_layout, "TRANSACTION ID", "-", "#0F172A")
        self.time_val = self._add_info_row(dp_layout, "LAST UPDATE", "-", "#64748B")
        
        dp_layout.addStretch()
        self.info_col.addWidget(self.data_panel)
        
        self.layout.addLayout(self.info_col, 1)

    def _create_video_frame(self, title):
        frame = QFrame()
        frame.setStyleSheet("background-color: #0F172A; border-radius: 8px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: white; font-size: 10px; font-weight: 700; background: rgba(0,0,0,0.5); padding: 2px 8px; border-radius: 4px;")
        layout.addWidget(title_lbl, 0, Qt.AlignLeft | Qt.AlignTop)
        
        lbl = QLabel()
        lbl.setObjectName("video_label")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        layout.addWidget(lbl, 1)
        return frame

    def _add_info_row(self, layout, label, value, color, large=False):
        row = QVBoxLayout()
        row.setSpacing(2)
        
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        row.addWidget(lbl)
        
        val = QLabel(value)
        font_size = "32px" if large else "18px"
        val.setStyleSheet(f"color: {color}; font-size: {font_size}; font-weight: 800; font-family: 'Consolas', monospace;")
        row.addWidget(val)
        
        layout.addLayout(row)
        return val

    def set_station(self, dump_id):
        self.dump_id = dump_id
        self.title_lbl.setText(f"STATION : {dump_id}")

    def update_view(self):
        if not self.dump_id: return
        
        # Get State
        states = self.system.get_processor_states()
        state = next((s for s in states if s['dump_id'] == self.dump_id), None)
        
        if state:
            self.state_lbl.setText(f"STATE : {state.get('state', '-')}")
            self.trash_val.setText(f"{state.get('trash_pct', 0)}%")
            self.lpr_val.setText(state.get('lpr', '-'))
            self.trans_val.setText(state.get('transaction_id', '-'))
            self.time_val.setText(state.get('timestamp', '-'))
            
            # Color coding
            trash = state.get('trash_pct', 0)
            color = "#EF4444" if trash > 30 else "#0EA5E9"
            self.trash_val.setStyleSheet(f"color: {color}; font-size: 32px; font-weight: 800;")

        # Get Frames
        frames = self.system.get_latest_frames(self.dump_id)
        if frames:
            self._set_image(self.img_lpr, frames.get('LPR'))
            self._set_image(self.img_ai, frames.get('AI'))

    def _set_image(self, label, cv_frame):
        if cv_frame is None: return
        
        import cv2
        height, width, channel = cv_frame.shape
        bytes_per_line = 3 * width
        q_img = QImage(cv_frame.data, width, height, bytes_per_line, QImage.Format_BGR888)
        
        if not label.size().isEmpty():
            pixmap = QPixmap.fromImage(q_img).scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
