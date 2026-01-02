from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame, QSpacerItem, QSizePolicy, QPushButton, QGridLayout)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QFont, QIcon
import os

class Sidebar(QWidget):
    # Signals: 'overview' or 'dump_id'
    view_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240) # Slightly wider for buttons
        self.setObjectName("Sidebar") 
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(15)
        
        # 1. Header Area
        self._build_header()
        
        # 2. Control Panel (Dump Selection)
        self._build_controls()
        
        # Spacer
        self.layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        # 3. Footer
        self.clock_lbl = QLabel("--:--:--")
        self.clock_lbl.setAlignment(Qt.AlignCenter)
        self.clock_lbl.setObjectName("SidebarLabel")
        self.clock_lbl.setStyleSheet("font-family: 'Consolas'; font-size: 18px; font-weight: bold; margin-bottom: 20px; color: #1E3A8A;")
        self.layout.addWidget(self.clock_lbl)

    def _build_header(self):
        header_widget = QWidget()
        h_layout = QVBoxLayout(header_widget)
        h_layout.setContentsMargins(20, 30, 20, 10)
        h_layout.setSpacing(15)
        
        # Logo
        logo_path = "assets/logo.png"
        if os.path.exists(logo_path):
            logo_lbl = QLabel()
            pixmap = QPixmap(logo_path)
            pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pixmap)
            logo_lbl.setAlignment(Qt.AlignCenter)
            h_layout.addWidget(logo_lbl)
        
        # Title
        title = QLabel("AI Sugarcane")
        title.setObjectName("SidebarTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #1E3A8A;")
        h_layout.addWidget(title)
        
        # Info Text (Larger)
        self._add_info_label(h_layout, "Factory", "MDC (Process A)")
        self._add_info_label(h_layout, "Active Dumps", "6 Stations")
        
        self.layout.addWidget(header_widget)

    def _add_info_label(self, layout, title, value):
        # Larger Fonts
        lbl = QLabel(f"<span style='color:#64748B; font-size:14px'>{title}</span> <br> <span style='color:#1E3A8A; font-weight:700; font-size:18px'>{value}</span>")
        lbl.setObjectName("SidebarLabel")
        lbl.setTextFormat(Qt.RichText)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

    def _build_controls(self):
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setContentsMargins(15, 0, 15, 0)
        ctrl_layout.setSpacing(10)
        
        # Label
        lbl = QLabel("VIEW CONTROLS")
        lbl.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        ctrl_layout.addWidget(lbl)
        
        # Grid Button
        btn_grid = QPushButton("SHOW ALL (GRID)")
        btn_grid.setCheckable(True)
        btn_grid.setChecked(True)
        btn_grid.setAutoExclusive(True)
        btn_grid.setCursor(Qt.PointingHandCursor)
        btn_grid.setStyleSheet("""
            QPushButton {
                background-color: #E2E8F0; color: #475569; border-radius: 8px; padding: 12px; font-weight: 700;
            }
            QPushButton:checked {
                background-color: #3B82F6; color: white;
            }
        """)
        btn_grid.clicked.connect(lambda: self.view_selected.emit("overview"))
        self.btn_grid = btn_grid
        ctrl_layout.addWidget(btn_grid)
        
        # Dump Buttons Grid
        dump_grid = QGridLayout()
        dump_grid.setSpacing(8)
        
        # 6 Dumps
        self.dump_btns = []
        for i in range(1, 7):
            d_id = f"MDC-A-0{i}" # Assuming ID format
            label = f"{i}"
            
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(60, 50)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: white; border: 2px solid #E2E8F0; border-radius: 8px; font-size: 18px; font-weight: 700; color: #1E3A8A;
                }
                QPushButton:checked {
                    background-color: #1E3A8A; color: white; border-color: #1E3A8A;
                }
                QPushButton:hover {
                    border-color: #3B82F6;
                }
            """)
            btn.clicked.connect(lambda checked, did=d_id: self.view_selected.emit(did))
            dump_grid.addWidget(btn, (i-1)//2, (i-1)%2)
            self.dump_btns.append(btn)
            
        ctrl_layout.addLayout(dump_grid)
        self.layout.addWidget(ctrl_widget)

    def update_clock(self, time_str):
        self.clock_lbl.setText(time_str)

    def _create_nav_btn(self, text, page_id):
        btn = QPushButton(text)
        btn.setObjectName("NavButton")
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.page_changed.emit(page_id))
        return btn
        
    def set_active_page(self, page_id):
        if page_id == "overview": self.btn_overview.setChecked(True)
        elif page_id == "transactions": self.btn_trans.setChecked(True)
        elif page_id == "dashboard": self.btn_dash.setChecked(True)
        elif page_id == "reports": self.btn_reports.setChecked(True)

    def update_clock(self, time_str):
        self.clock_lbl.setText(time_str)
