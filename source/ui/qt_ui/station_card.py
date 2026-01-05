from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy, QApplication)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QColor

class StationCard(QFrame):
    clicked = Signal(str) # dump_id

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
        
        # State Badge (Top Right)
        self.state_badge = QLabel("IDLE")
        self.state_badge.setStyleSheet("""
            background-color: #F1F5F9; color: #475569; 
            padding: 4px 10px; border-radius: 4px; 
            font-weight: 700; font-size: 11px;
        """)
        header_layout.addWidget(self.state_badge)
        
        self.layout.addLayout(header_layout)

    def _build_images(self):
        self.img_layout = QHBoxLayout()
        self.img_layout.setSpacing(5)
        
        # Image 1 (LPR View)
        self.img_lpr = QLabel()
        self.img_lpr.setAlignment(Qt.AlignCenter)
        self.img_lpr.setStyleSheet("background-color: transparent; border-radius: 4px;") 
        self.img_lpr.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.img_layout.addWidget(self.img_lpr, 1) 
        
        # Image 2 (AI View)
        self.img_ai = QLabel()
        self.img_ai.setAlignment(Qt.AlignCenter)
        self.img_ai.setStyleSheet("background-color: transparent; border-radius: 4px;")
        self.img_ai.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.img_layout.addWidget(self.img_ai, 1)
        
        self.layout.addLayout(self.img_layout, 1)

    def _build_footer(self):
        # Stats Panel (Ultra-Minimal: Split Left/Right)
        stats_widget = QWidget()
        stats_widget.setStyleSheet("background-color: transparent; margin-top: 0px;") 
        self.footer_main_layout = QHBoxLayout(stats_widget)
        self.footer_main_layout.setContentsMargins(5, 0, 5, 5)
        self.footer_main_layout.setSpacing(15)
        
        # --- LEFT COLUMN: LPR & Metadata (Matches Left Image) ---
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        
        self.lbl_lpr_val = QLabel("LPR : -")
        self.lbl_lpr_val.setStyleSheet("color: #0F172A; font-size: 15px; font-weight: 800; font-family: 'Consolas', monospace;")
        
        self.lbl_trans_id = QLabel("Trans : -")
        self.lbl_date_val = QLabel("Date : -")
        for lbl in [self.lbl_trans_id, self.lbl_date_val]:
            lbl.setStyleSheet("color: #475569; font-size: 10px; font-weight: 600; font-family: 'Consolas', monospace;")
        
        left_col.addWidget(self.lbl_lpr_val)
        left_col.addWidget(self.lbl_trans_id)
        left_col.addWidget(self.lbl_date_val)
        left_col.addStretch()
        
        self.footer_main_layout.addLayout(left_col, 1)

        # --- RIGHT COLUMN: AI Results / Trash (Matches Right Image) ---
        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        
        # Trash Header
        trash_header = QHBoxLayout()
        trash_lbl = QLabel("TRASH %")
        trash_lbl.setStyleSheet("color: #64748B; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;")
        self.trash_val_lbl = QLabel("0%")
        self.trash_val_lbl.setStyleSheet("color: #0F172A; font-size: 15px; font-weight: 800;")
        
        trash_header.addWidget(trash_lbl)
        trash_header.addStretch()
        trash_header.addWidget(self.trash_val_lbl)
        right_col.addLayout(trash_header)
        
        # Capsule Bar
        bg_bar = QFrame()
        bg_bar.setFixedHeight(8)
        bg_bar.setStyleSheet("background-color: #F1F5F9; border-radius: 4px;")
        bg_layout = QHBoxLayout(bg_bar)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        
        self.fill_bar = QFrame()
        self.fill_bar.setFixedHeight(8)
        self.fill_bar.setStyleSheet("background-color: #0EA5E9; border-radius: 4px;")
        self.fill_bar.setFixedWidth(0) 
        bg_layout.addWidget(self.fill_bar)
        bg_layout.addStretch()
        
        right_col.addWidget(bg_bar)
        
        # Bottom status in right col or full width? Let's put it in right col for alignment
        self.action_lbl = QLabel("● IDLE")
        self.action_lbl.setStyleSheet("color: #64748B; font-weight: 700; font-size: 11px; margin-top: 5px;")
        right_col.addWidget(self.action_lbl)
        right_col.addStretch()
        
        self.footer_main_layout.addLayout(right_col, 1)
        
        self.layout.addWidget(stats_widget)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)
        # self.clicked.emit(self.dump_id) # DISABLED Navigation via Card Click

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        from PySide6.QtGui import QDrag
        from PySide6.QtCore import QMimeData
        
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(self.dump_id)
        drag.setMimeData(mime_data)
        
        # Draw a preview (optional but better)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.pos())
        
        drag.exec_(Qt.MoveAction)

    def update_state(self, state_data):
        # Update State Badge
        state_text = state_data.get('state', '-')
        
        # Update Header Badge
        is_active = state_text != 'IDLE'
        self.state_badge.setText(state_text)
        if is_active:
            self.state_badge.setStyleSheet("""
                background-color: #DCFCE7; color: #166534; 
                padding: 4px 10px; border-radius: 4px; border: 1px solid #BBF7D0;
                font-weight: 700; font-size: 11px;
            """)
        else:
             self.state_badge.setStyleSheet("""
                background-color: #F1F5F9; color: #64748B; 
                padding: 4px 10px; border-radius: 4px; border: 1px solid #E2E8F0;
                font-weight: 700; font-size: 11px;
            """)

        # REAL Data from AI Engine
        trash = state_data.get('trash_pct', 0)
        lpr_text = state_data.get('lpr', '-')
        trans_id = state_data.get('transaction_id', '-')
        now_str = state_data.get('timestamp', '-')
        
        if is_active:
            self.trash_val_lbl.setText(f"{trash}%")
            
            # Progress Bar Logic
            width = int(trash * 2.5) # Scale factor for card width
            self.fill_bar.setFixedWidth(max(2, width)) # Min 2px for visibility
            color = "#EF4444" if trash > 30 else "#0EA5E9"
            self.fill_bar.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
            
            self.lbl_lpr_val.setText(f"LPR : {lpr_text}")
            self.lbl_trans_id.setText(f"Trans : {trans_id}")
            self.lbl_date_val.setText(f"Date : {now_str}")
            
            self.action_lbl.setText(f"● {state_text}")
            # Map state to color
            if 'RESET' in state_text or 'IDLE' in state_text:
                self.action_lbl.setStyleSheet("color: #64748B; font-weight: 700; font-size: 11px;")
            else:
                self.action_lbl.setStyleSheet("color: #10B981; font-weight: 700; font-size: 11px;")
            
        else:
            self.trash_val_lbl.setText("0%")
            self.fill_bar.setFixedWidth(0)
            self.lbl_lpr_val.setText(f"LPR : {lpr_text}")
            self.lbl_trans_id.setText(f"Trans : {trans_id}")
            self.lbl_date_val.setText(f"Date : {now_str}")
            self.action_lbl.setText("● IDLE")
            self.action_lbl.setStyleSheet("color: #64748B; font-weight: 700; font-size: 11px;")

    def update_images(self, frames):
        if not frames: return
        self._set_image(self.img_lpr, frames.get('LPR'))
        self._set_image(self.img_ai, frames.get('AI'))

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
