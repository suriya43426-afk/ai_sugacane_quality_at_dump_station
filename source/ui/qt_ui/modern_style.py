class ModernStyle:
    # Color Palette: Mitr Phol (Clean & Minimal: 70-20-10)
    # 70% White / Neutral (Backgrounds, Cards)
    BG_MAIN = "#F8FAFC"      # Clean Slate White (App BG)
    BG_CARD = "#FFFFFF"      # Pure White (Card BG)
    BORDER  = "#E2E8F0"      # Subtle Border
    
    # 20% Sky Blue (Secondary, Highlights, Backgrounds of active items)
    ACCENT_BG = "#E0F2FE"    # Very Light Sky Blue (Stats BG, Hover)
    ACCENT_FG = "#0EA5E9"    # Sky Blue (Icons, Highlights)
    BTN_BG    = "#F1F5F9"    # Light Grey/Blue for inactive buttons
    
    # 10% Deep Blue (Primary, Text, Headers)
    TEXT_PRI = "#0F172A"     # Dark Navy (Main Text)
    TEXT_SEC = "#475569"     # Slate Grey (Secondary Text)
    PRIMARY  = "#1E40AF"     # Deep Blue (Active Buttons, headers)
    
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
            color: {ModernStyle.ACCENT_FG};
        }}
        
        QPushButton#NavButton:checked {{
            background-color: {ModernStyle.PRIMARY};
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
