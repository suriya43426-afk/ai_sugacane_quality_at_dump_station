import sys
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                               QVBoxLayout, QLabel, QStackedWidget)
from PySide6.QtCore import Qt, QTimer, QDateTime
from PySide6.QtGui import QIcon, QFont, QPalette, QColor

from source.ui.qt_ui.sidebar import Sidebar
from source.ui.qt_ui.overview_view import OverviewView
from source.ui.qt_ui.single_view import SingleStationView
from source.ui.qt_ui.modern_style import ModernStyle
from source.services.cloud_sync import CloudSyncWorker
from PySide6.QtCore import QThread

class QtMainWindow(QMainWindow):
    def __init__(self, system, title="AI Sugarcane Quality Detection"):
        super().__init__()
        self.system = system
        
        # Apply Global Style
        if QApplication.instance():
            QApplication.instance().setStyleSheet(ModernStyle.get_style())
            
        self.setWindowTitle(title)
        self.resize(1920, 1080)
        
        self._setup_theme()
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        self.main_layout = QHBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. Global Sidebar Container (Can be moved)
        self.sidebar_container = QWidget()
        self.sidebar_layout = QVBoxLayout(self.sidebar_container)
        self.sidebar_layout.setContentsMargins(0,0,0,0)
        
        self.sidebar = Sidebar(self)
        self.sidebar.view_selected.connect(self._on_view_selected)
        self.sidebar_layout.addWidget(self.sidebar)
        
        # Initial placement: Let the root layout have it first
        self.main_layout.addWidget(self.sidebar_container)
        
        # 2. Stacked Content
        self.content_stack = QStackedWidget()
        self.main_layout.addWidget(self.content_stack)
        
        # Page 0: Overview
        # We pass self.sidebar_container so Overview can swallow it
        self.overview_view = OverviewView(self.system, sidebar=self.sidebar_container)
        self.overview_view.station_clicked.connect(self._on_view_selected)
        self.overview_view.order_changed.connect(self.sidebar.update_button_order)
        
        # Ensure initial order is synced (Manual trigger after connection)
        self.sidebar.update_button_order(self.overview_view.dump_order)
        
        self.content_stack.addWidget(self.overview_view)
        
        # Page 1: Single Dump View
        self.single_view = SingleStationView(self.system)
        self.content_stack.addWidget(self.single_view)
        
        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_state)
        self.timer.start(100) # 10 FPS
        
        # 3. Cloud Sync Integration (Unified Worker)
        self._init_cloud_service()
        
        # 4. Status Bar (Unified Feedback)
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("System Ready | Cloud Agent: Initializing...")
        self.status_bar.setStyleSheet("color: white; background-color: #2D2D2D;")

    def _on_view_selected(self, view_id):
        if view_id == "overview":
            # Re-insert into Overview Grid
            self.overview_view.integrate_sidebar(self.sidebar_container)
            self.content_stack.setCurrentIndex(0)
        else:
            # Move Sidebar back to Global Left for Single View
            self.main_layout.insertWidget(0, self.sidebar_container)
            self.sidebar_container.show()
            
            # Update Single View
            self.single_view.set_station(view_id)
            self.content_stack.setCurrentIndex(1)

    def _setup_theme(self):
        pass

    def _update_state(self):
        # Update Clock
        now_str = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.sidebar.update_clock(now_str)
        
        # Update Active View Only
        idx = self.content_stack.currentIndex()
        if idx == 0:
            self.overview_view.update_view()
        elif idx == 1:
            self.single_view.update_view()

    def closeEvent(self, event):
        self.system.stop_processors()
        
        # Stop Cloud Worker safely
        if hasattr(self, 'cloud_worker'):
            self.cloud_worker.stop()
            self.cloud_thread.quit()
            self.cloud_thread.wait()
            
        event.accept()

    def _init_cloud_service(self):
        """Initializes the background cloud sync worker in a separate thread."""
        self.cloud_thread = QThread()
        self.cloud_worker = CloudSyncWorker()
        self.cloud_worker.moveToThread(self.cloud_thread)
        
        # Connect Signals
        self.cloud_thread.started.connect(self.cloud_worker.run)
        self.cloud_worker.status_updated.connect(self._on_cloud_status)
        self.cloud_worker.progress_updated.connect(self._on_cloud_progress)
        self.cloud_worker.error_occurred.connect(self._on_cloud_error)
        
        # Start
        self.cloud_thread.start()

    def _on_cloud_status(self, msg):
        self.status_bar.showMessage(f"System Active | Cloud Agent: {msg}")

    def _on_cloud_progress(self, uploaded, deleted):
        self._on_cloud_status(f"Batch Done (Up: {uploaded}, Del: {deleted})")

    def _on_cloud_error(self, err):
        self.status_bar.showMessage(f"System Warning | Cloud Error: {err}")
        self.status_bar.setStyleSheet("color: #FF5555; background-color: #2D2D2D;")

if __name__ == "__main__":
    # Mock System for testing
    class MockSystem:
        def stop_processors(self): pass
        def get_processor_states(self):
            return [
                {'dump_id': 'MDC-A-01', 'status': 'RUNNING', 'state': 'IDLE', 'lpr': 'ABC-1234'},
                {'dump_id': 'MDC-A-02', 'status': 'ERROR', 'state': 'SCANNING', 'lpr': '-'},
                {'dump_id': 'MDC-A-03', 'status': 'RUNNING', 'state': 'IDLE', 'lpr': 'XYZ-9999'},
            ]
        def get_latest_frames(self, dump_id): return {}
        def get_system_info(self): return {'factory': 'Test Factory', 'milling': 'Process X'}
        
        def get_recent_transactions(self, limit=50):
            return [
                ('1001', 'MDC-A-01', True, 'ABC-1234', '12:00:00'),
                ('1002', 'MDC-A-02', False, 'XYZ-9999', '12:05:00'),
                ('1003', 'MDC-A-01', True, 'LPR-5555', '12:10:00'),
            ]
        
        def get_dashboard_charts_data(self):
            return {
                'hourly_trend': [('08:00', 5), ('09:00', 12), ('10:00', 8), ('11:00', 15)],
                'quality_breakdown': {'Clean': 60, 'Dirty': 30, 'Contaminated': 10},
                'process_breakdown': {'A': 50, 'B': 30, 'C': 20}
            }
            
        def get_daily_report(self, date_str):
            return [
                ['Station', 'Time', 'LPR', 'Quality'],
                ['MDC-A-01', '08:00', 'ABC-1234', 'Clean'],
                ['MDC-A-02', '08:05', 'XYZ-9999', 'Dirty']
            ]
            
    app = QApplication(sys.argv)
    window = QtMainWindow(MockSystem())
    window.show()
    sys.exit(app.exec())
