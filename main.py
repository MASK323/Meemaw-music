import ctypes
import hashlib
import os
import sys
import time

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import APP_QSS

_APP_ICON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "app",
    "assets",
    "icons",
    "app_icon.ico",
)

_SINGLE_INSTANCE_KEY = "MeemawMusic_{}".format(
    hashlib.sha256(os.environ.get("USERNAME", "default").encode("utf-8")).hexdigest()[:16]
)
_MUTEX_NAME = "Local\\MeemawMusic_{}".format(
    hashlib.sha256(os.environ.get("USERNAME", "default").encode("utf-8")).hexdigest()[:16]
)
_mutex_handle = None


def _acquire_instance_mutex() -> bool:
    """Return True when this process may run as the only Meemaw music instance."""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return False
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _activate_existing_instance(attempts: int = 4) -> bool:
    for _ in range(attempts):
        socket = QLocalSocket()
        socket.connectToServer(_SINGLE_INSTANCE_KEY)
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            socket.close()
            return True
        socket.close()
        time.sleep(0.2)
    return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Meemaw music")
    app.setApplicationDisplayName("Meemaw music")
    app.setOrganizationName("MeemawMusic")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    if os.path.exists(_APP_ICON):
        app.setWindowIcon(QIcon(_APP_ICON))

    server = QLocalServer(app)
    if sys.platform != "win32":
        if not server.listen(_SINGLE_INSTANCE_KEY):
            if _activate_existing_instance():
                return 0
            QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
            if not server.listen(_SINGLE_INSTANCE_KEY):
                return 0
    else:
        if not _acquire_instance_mutex() and _activate_existing_instance():
            return 0
        if not server.listen(_SINGLE_INSTANCE_KEY):
            if _activate_existing_instance():
                return 0
            # A stale mutex/server can remain after a crash. Remove it so the
            # app can still open instead of silently exiting.
            QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
            if not server.listen(_SINGLE_INSTANCE_KEY):
                return 0

    window = MainWindow()
    if os.path.exists(_APP_ICON):
        window.setWindowIcon(QIcon(_APP_ICON))

    def _show_from_client(conn) -> None:
        conn.readyRead.disconnect()
        conn.readAll()
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()
        conn.disconnectFromServer()
        conn.deleteLater()

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda c=conn: _show_from_client(c))

    server.newConnection.connect(_on_new_connection)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
