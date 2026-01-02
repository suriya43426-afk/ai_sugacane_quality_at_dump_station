from PySide6.QtWidgets import (QWidget, QGridLayout, QScrollArea, QVBoxLayout)
from PySide6.QtCore import Qt
from source.ui.qt_ui.station_card import StationCard

class OverviewView(QWidget):
    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.system = system
        
        # Main Layout (Fill space, no scroll)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10) # Minimal margin
        
        # Grid Layout
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10) # Gap between cards
        self.main_layout.addLayout(self.grid_layout)
        
        # Initial Build
        self.cols = 3 # Fixed 3 cols for 6 stations -> 2 rows
        self._build_grid()

    def resizeEvent(self, event):
        # We enforce 3x2, so no dynamic reflow needed for column COUNT
        # But we let the layout engine handle size
        super().resizeEvent(event)

    def _build_grid(self):
        # Get list of processors/dumps
        states = self.system.get_processor_states()
        
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        
        self.cards = {}
        
        # Assuming 6 stations max for 1 process
        # Force 3 columns
        cols = 3
        
        for i, s in enumerate(states):
            d_id = s['dump_id']
            card = StationCard(d_id)
            self.cards[d_id] = card
            
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(card, row, col)
            
        # Set Stretches to ensure even fill
        # Columns
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
            
        # Rows
        rows = (len(states) + cols - 1) // cols
        for r in range(rows):
            self.grid_layout.setRowStretch(r, 1)

    def update_view(self):
        # 1. Update text states
        states = self.system.get_processor_states()
        for s in states:
            d_id = s['dump_id']
            if d_id in self.cards:
                self.cards[d_id].update_state(s)
                
                # 2. Update images
                # Fetch only if visible? For now fetch all active
                frames = self.system.get_latest_frames(d_id)
                self.cards[d_id].update_images(frames)
