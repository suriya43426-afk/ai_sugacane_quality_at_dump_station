from PySide6.QtWidgets import (QWidget, QGridLayout, QScrollArea, QVBoxLayout)
from PySide6.QtCore import Qt, Signal
from source.ui.qt_ui.station_card import StationCard

class OverviewView(QWidget):
    station_clicked = Signal(str)
    order_changed = Signal(list)

    def __init__(self, system, sidebar=None, parent=None):
        super().__init__(parent)
        self.system = system
        self.sidebar = sidebar
        self.setAcceptDrops(True)
        
        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(15)
        self.main_layout.addLayout(self.grid_layout)
        
        # Track Custom Order
        self.dump_order = []
        self._init_data()
        self._build_grid()

    def _init_data(self):
        states = self.system.get_processor_states()
        self.dump_order = [s['dump_id'] for s in states]
        self.order_changed.emit(self.dump_order)

    def integrate_sidebar(self, sidebar_widget):
        if not sidebar_widget: return
        self.sidebar = sidebar_widget
        self._build_grid()

    def _build_grid(self):
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget and widget != self.sidebar:
                 widget.setParent(None)
        
        self.cards = {}
        
        # Center Sidebar Implementation
        if self.sidebar:
            self.sidebar.show()
            row_span = (len(self.dump_order) + 1) // 2
            self.grid_layout.addWidget(self.sidebar, 0, 1, max(1, row_span), 1)
        
        for i, d_id in enumerate(self.dump_order):
            card = StationCard(d_id)
            card.clicked.connect(self.station_clicked.emit)
            self.cards[d_id] = card
            
            row = i // 2
            col = 0 if i % 2 == 0 else 2 # Skip col 1 (Sidebar)
            self.grid_layout.addWidget(card, row, col)
            
        # Stretch columns
        self.grid_layout.setColumnStretch(0, 2)
        self.grid_layout.setColumnStretch(1, 0) # Sidebar fits its content
        self.grid_layout.setColumnStretch(2, 2)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        dropped_id = event.mimeData().text()
        if dropped_id not in self.dump_order: return
        
        # Find target position based on mouse coordinate
        pos = event.pos()
        target_idx = -1
        
        # Simple heuristic: find nearest card
        for i, d_id in enumerate(self.dump_order):
            card = self.cards.get(d_id)
            if card and card.geometry().contains(pos):
                target_idx = i
                break
        
        if target_idx != -1:
            # Move dropped_id to target_idx
            self.dump_order.remove(dropped_id)
            self.dump_order.insert(target_idx, dropped_id)
            self._build_grid()
            self.order_changed.emit(self.dump_order)
            event.acceptProposedAction()

    def update_view(self):
        states = self.system.get_processor_states()
        state_map = {s['dump_id']: s for s in states}
        
        for d_id, card in self.cards.items():
            if d_id in state_map:
                card.update_state(state_map[d_id])
                frames = self.system.get_latest_frames(d_id)
                card.update_images(frames)
