import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.app import PlotterApp

import os

def main():
    app = QApplication(sys.argv)
    
    # Robust icon loading
    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(script_dir, "assets", "logo.png")
    app_icon = QIcon(icon_path)
    app.setWindowIcon(app_icon)
    
    app.setStyle("Fusion")
    
    app.setStyleSheet("""
        QMainWindow { background-color: #0f172a; }
        QWidget {
            font-family: 'Inter', -apple-system, sans-serif;
            color: #f1f5f9;
            font-size: 13px;
        }
        
        /* SIDEBARS & PANELS */
        QFrame#TopBar { background-color: #1e293b; border-bottom: 1px solid #334155; }
        QFrame#LeftSidebar, QFrame#RightSidebar { 
            background-color: #1e293b; 
            border: 1px solid #334155;
            border-radius: 8px;
            margin: 5px;
        }
        
        /* BUTTONS */
        QPushButton {
            background-color: #334155;
            color: #f1f5f9;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:hover { background-color: #475569; border-color: #64748b; }
        QPushButton:pressed { background-color: #1e293b; }
        
        QPushButton#BtnTopNav { 
            background-color: transparent;
            border: none;
            border-radius: 0px;
            padding: 0 20px;
            height: 50px;
            font-weight: 600;
        }
        QPushButton#BtnTopNav:hover { background-color: #334155; }
        QPushButton#BtnTopNav:checked { 
            color: #3b82f6; 
            border-bottom: 3px solid #3b82f6;
        }
        
        /* PRIMARY ACTION BUTTONS */
        QPushButton#btnPrimary {
            background-color: #2563eb;
            color: white;
            border: 1px solid #1d4ed8;
        }
        QPushButton#btnPrimary:hover { background-color: #3b82f6; }
        
        QPushButton#btnSuccess {
            background-color: #059669;
            color: white;
            border: 1px solid #047857;
        }
        QPushButton#btnSuccess:hover { background-color: #10b981; }
        
        QPushButton#btnDanger {
            background-color: #dc2626;
            color: white;
            border: 1px solid #b91c1c;
        }
        QPushButton#btnDanger:hover { background-color: #ef4444; }

        /* INPUTS */
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 6px;
            color: #f8fafc;
        }
        QLineEdit:focus, QComboBox:focus { border-color: #3b82f6; }
        
        /* LISTS */
        QListWidget {
            background-color: transparent;
            border: 1px solid #334155;
            border-radius: 4px;
        }
        QListWidget::item {
            padding: 12px;
            border-bottom: 1px solid #334155;
        }
        QListWidget::item:selected {
            background-color: #334155;
            color: #3b82f6;
            font-weight: bold;
        }
        
        /* LABELS */
        QLabel#HeaderLabel {
            font-size: 11px;
            font-weight: 800;
            color: #94a3b8;
            letter-spacing: 1px;
            text-transform: uppercase;
            margin-top: 10px;
            margin-bottom: 5px;
        }
        
        QProgressBar {
            border: 1px solid #334155;
            border-radius: 4px;
            text-align: center;
            background-color: #0f172a;
        }
        QProgressBar::chunk {
            background-color: #3b82f6;
            width: 20px;
        }
    """)

    window = PlotterApp()
    window.setWindowIcon(app_icon)
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
