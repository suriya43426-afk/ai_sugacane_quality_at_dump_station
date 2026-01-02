class ModernStyle:
    # Color Palette: Mitr Phol (60-30-10)
    # 60% Primary
    BG_MAIN = "#F4F7FE"      # Ice Blue White (Background)
    BG_CARD = "#FFFFFF"      # Pure White (Cards)
    
    # 30% Secondary
    ACCENT  = "#3B82F6"      # Vivid Blue (Active States, Highlights)
    BTN_BG  = "#E3F2FD"      # Very Light Blue (Button Base)
    
    # 10% Tertiary
    TEXT_PRI = "#1E3A8A"     # Deep Blue (Headers)
    TEXT_SEC = "#64748B"     # Slate Grey (Body)
    
    @staticmethod
    def get_style():
        return f"""
        /* Global Reset */
        QWidget {{
            font-family: 'Segoe UI', 'Kanit', sans-serif;
            font-size: 14px;
            color: {ModernStyle.TEXT_SEC};
        }}
        
        /* Main Window & Backgrounds */
        QMainWindow, QWidget#CentralWidget {{
            background-color: {ModernStyle.BG_MAIN};
        }}
        
        QStackedWidget {{
            background-color: {ModernStyle.BG_MAIN};
        }}
        
        /* Cards */
        QFrame#StationCard {{
            background-color: {ModernStyle.BG_CARD};
            border-radius: 16px;
            border: 1px solid #E2E8F0;
        }}
        
        /* Cards: Hover Effect (If using QFrame as button, but generic here) */
        
        /* Sidebar */
        QWidget#Sidebar {{
            background-color: {ModernStyle.BG_CARD};
            border-right: 1px solid #E2E8F0;
        }}
        
        QLabel#SidebarTitle {{
            color: {ModernStyle.TEXT_PRI};
            font-size: 18px;
            font-weight: bold;
        }}
        
        QLabel#SidebarLabel {{
            color: {ModernStyle.TEXT_SEC};
            font-size: 12px;
        }}
        
        /* Navigation Buttons */
        QPushButton#NavButton {{
            background-color: transparent;
            color: {ModernStyle.TEXT_SEC};
            border: none;
            border-radius: 12px;
            text-align: left;
            padding: 12px 20px;
            font-weight: 600;
        }}
        
        QPushButton#NavButton:hover {{
            background-color: {ModernStyle.BTN_BG};
            color: {ModernStyle.ACCENT};
        }}
        
        QPushButton#NavButton:checked {{
            background-color: {ModernStyle.ACCENT};
            color: white;
        }}
        
        /* Tables */
        QTableWidget {{
            background-color: {ModernStyle.BG_CARD};
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            gridline-color: #F1F5F9;
        }}
        
        QHeaderView::section {{
            background-color: {ModernStyle.BTN_BG};
            color: {ModernStyle.TEXT_PRI};
            padding: 8px;
            border: none;
            font-weight: bold;
        }}
        
        /* Scrollbars */
        QScrollBar:vertical {{
            border: none;
            background: #F1F5F9;
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: #CBD5E1;
            border-radius: 4px;
        }}
        """
