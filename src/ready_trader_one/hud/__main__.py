import configparser
import os
import pathlib
import string
import sys
import time

from PySide2 import QtGui, QtWidgets
from PySide2.QtCore import Qt

from .event_source import EventSource, LiveEventSource, RecordedEventSource
from .main_window.main_window import MainWindow


HERE: pathlib.Path = pathlib.Path(__file__).parent


def __create_application() -> QtWidgets.QApplication:
    if sys.platform == "darwin":
        os.environ["QT_MAC_WANTS_LAYER"] = "1"
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle(QtWidgets.QStyleFactory.create("Fusion"))
    with (HERE.joinpath("style/style.qss")).open("r") as theme:
        with (HERE.joinpath("style/settings.ini")).open("r") as settings:
            parser = configparser.ConfigParser()
            parser.read_file(settings)
            template = string.Template(theme.read())
            app.setStyleSheet(template.substitute(parser["default"]))
    return app


def __show_splash() -> QtWidgets.QSplashScreen:
    splash = QtWidgets.QSplashScreen(QtGui.QPixmap(str(HERE.joinpath("images/splash.jpg"))))
    splash.show()
    return splash


def __show_main_window(splash: QtWidgets.QSplashScreen, event_source: EventSource) -> MainWindow:
    splash.showMessage("Creating main window...", Qt.AlignBottom, QtGui.QColor("#F0F0F0"))
    icon = QtGui.QIcon(str(HERE.joinpath("images/icon.png")))
    window = MainWindow(icon, event_source)
    window.show()
    splash.finish(window)
    return window


def replay(path: pathlib.Path):
    app = __create_application()
    splash = __show_splash()
    splash.showMessage("Processing %s..." % str(path), Qt.AlignBottom, QtGui.QColor("#F0F0F0"))
    with path.open("r", newline="") as csv_file:
        event_source = RecordedEventSource.from_csv(csv_file)
    window = __show_main_window(splash, event_source)
    return app.exec_()


def main(host: str, port: int):
    app = __create_application()
    splash = __show_splash()
    time.sleep(1)
    event_source = LiveEventSource(host, port)
    window = __show_main_window(splash, event_source)
    return app.exec_()
