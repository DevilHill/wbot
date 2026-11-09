"""Isolated Qt button driver for verify_assistant_updates.py."""
import os
from pathlib import Path
import sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.assistant.qt_app import open_desktop
from app.assistant.qt_ui import AssistantWindow

application = QApplication([])
clicked = False
timer = QTimer()
timer.setInterval(50)


def install_when_ready():
    global clicked
    if clicked:
        return
    window = next((widget for widget in application.topLevelWidgets() if isinstance(widget, AssistantWindow)), None)
    if window is None:
        return
    if window.settings_page is None:
        window.open_settings()
    card = window.settings_page.update_card
    if card._ready and card.action_button.isEnabled():
        clicked = True
        timer.stop()
        card.action_button.click()


timer.timeout.connect(install_when_ready)
timer.start()
QTimer.singleShot(25000, application.quit)
result = open_desktop(Path(sys.argv[1]))
if not clicked:
    raise RuntimeError('Qt update action was not reached')
raise SystemExit(result)
