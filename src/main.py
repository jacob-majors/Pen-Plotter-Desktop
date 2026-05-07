import sys
from PySide6.QtWidgets import QApplication
from ui.app import PlotterApp

# Adobe Illustrator-inspired dark theme
_STYLESHEET = """
QMainWindow, QDialog {
    background: #1e1e1e;
}

QWidget {
    background: #1e1e1e;
    color: #e0e0e0;
    font-family: -apple-system, "Segoe UI", Arial, sans-serif;
    font-size: 12px;
}

/* ── Top nav ─────────────────────────────────────────── */

QFrame#TopBar {
    background: #2c2c2c;
    border-bottom: 1px solid #111;
}

QPushButton#BtnTopNav {
    background: transparent;
    color: #8e8e8e;
    border: none;
    border-radius: 0;
    padding: 0 18px;
    height: 50px;
    font-size: 12px;
}
QPushButton#BtnTopNav:hover {
    background: #353535;
    color: #d8d8d8;
}
QPushButton#BtnTopNav:checked {
    color: #fff;
    background: #353535;
    border-bottom: 2px solid #2680eb;
}

/* ── Generic buttons ─────────────────────────────────── */

QPushButton {
    background: transparent;
    color: #d0d0d0;
    border: 1px solid #3a3a3a;
    border-radius: 3px;
    padding: 5px 10px;
}
QPushButton:hover {
    background: #333;
    border-color: #4a4a4a;
    color: #f0f0f0;
}
QPushButton:pressed {
    background: #252525;
}
QPushButton:checked {
    background: #1e3a5f;
    border-color: #2680eb;
    color: #fff;
}
QPushButton:disabled {
    color: #484848;
    border-color: #282828;
}

/* ── Inputs ──────────────────────────────────────────── */

QLineEdit, QPlainTextEdit {
    background: #2c2c2c;
    border: 1px solid #191919;
    border-radius: 3px;
    padding: 5px 8px;
    color: #e8e8e8;
    selection-background-color: #1960c4;
}
QLineEdit:focus, QPlainTextEdit:focus { border-color: #2680eb; }

QTextEdit {
    background: #222;
    border: 1px solid #191919;
    border-radius: 3px;
    color: #d8d8d8;
}
QTextEdit:focus { border-color: #2680eb; }

QSpinBox, QDoubleSpinBox {
    background: #2c2c2c;
    border: 1px solid #191919;
    border-radius: 3px;
    padding: 4px 6px;
    color: #e8e8e8;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2680eb; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #383838;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #484848;
}

QComboBox {
    background: #2c2c2c;
    border: 1px solid #191919;
    border-radius: 3px;
    padding: 4px 8px;
    color: #e8e8e8;
    min-width: 60px;
}
QComboBox:hover { border-color: #3a3a3a; }
QComboBox:focus { border-color: #2680eb; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #2c2c2c;
    border: 1px solid #191919;
    selection-background-color: #1960c4;
    outline: none;
    padding: 2px;
}

/* ── Lists ───────────────────────────────────────────── */

QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #1a1a1a;
}
QListWidget::item:selected {
    background: #1a3a5c;
    color: #e8e8e8;
    border-left: 2px solid #2680eb;
}
QListWidget::item:hover:!selected {
    background: #2a2a2a;
}

/* ── Tabs ────────────────────────────────────────────── */

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #252525;
    color: #808080;
    padding: 8px 20px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #e0e0e0;
    background: #2c2c2c;
    border-bottom: 2px solid #2680eb;
}
QTabBar::tab:hover:!selected {
    color: #c0c0c0;
    background: #292929;
}

/* ── Group box ───────────────────────────────────────── */

QGroupBox {
    color: #787878;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1px;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 14px;
    background: transparent;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    background: #1e1e1e;
}

/* ── Progress bar ────────────────────────────────────── */

QProgressBar {
    background: #2a2a2a;
    border: none;
    border-radius: 2px;
    max-height: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2680eb;
    border-radius: 2px;
}

/* ── Scroll bars ─────────────────────────────────────── */

QScrollBar:vertical {
    background: #1e1e1e;
    width: 7px;
    border: none;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a3a3a;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #4a4a4a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1e1e1e;
    height: 7px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #3a3a3a;
    border-radius: 3px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #4a4a4a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── Checkboxes ──────────────────────────────────────── */

QCheckBox { color: #d0d0d0; spacing: 6px; }
QCheckBox::indicator {
    width: 13px; height: 13px;
    border: 1px solid #444;
    border-radius: 2px;
    background: #2c2c2c;
}
QCheckBox::indicator:checked {
    background: #2680eb;
    border-color: #2680eb;
}

/* ── Splitter ────────────────────────────────────────── */

QSplitter::handle { background: #141414; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical   { height: 1px; }

/* ── Tooltips ────────────────────────────────────────── */

QToolTip {
    background: #2c2c2c;
    color: #e0e0e0;
    border: 1px solid #111;
    padding: 4px 8px;
    font-size: 11px;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(_STYLESHEET)

    window = PlotterApp()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
