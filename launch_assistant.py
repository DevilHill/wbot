"""Qt Assistant 的双击入口；无参数时打开桌面窗口。"""
import contextlib
import io
import sys

from app.assistant.__main__ import main


def launch():
    arguments = sys.argv[1:] or ['open']
    if not getattr(sys, 'frozen', False) or sys.stderr is not None:
        return main(arguments)
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        exit_code = main(arguments)
    if exit_code and errors.getvalue():
        from PySide6.QtWidgets import QApplication, QMessageBox
        application = QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None, 'WBot Assistant 启动失败', errors.getvalue().strip())
        application.quit()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(launch())
