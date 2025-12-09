#!/usr/bin/env python3
# /anpr/ui/main_window.py
import os
import sys
import cv2
import psutil
from typing import Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from anpr.workers.channel_worker import ChannelWorker
from logging_manager import get_logger
from settings_manager import SettingsManager
from storage import EventDatabase

logger = get_logger(__name__)


class ChannelView(QtWidgets.QWidget):
    """Отображает поток канала с подсказками и индикатором движения."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

        self.video_label = QtWidgets.QLabel("Нет сигнала")
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setStyleSheet("""
            QLabel {
                background-color: #0a0a0a;
                color: #aaa;
                border: 2px solid #1a1a1a;
                border-radius: 4px;
                padding: 8px;
                font-weight: 500;
            }
        """)
        self.video_label.setMinimumSize(220, 170)
        self.video_label.setScaledContents(False)
        self.video_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.video_label)

        # Индикатор движения
        self.motion_indicator = QtWidgets.QLabel("🚨 ДВИЖЕНИЕ")
        self.motion_indicator.setParent(self.video_label)
        self.motion_indicator.setStyleSheet("""
            QLabel {
                background-color: rgba(220, 53, 69, 0.9);
                color: white;
                padding: 4px 10px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 10px;
                border: 1px solid rgba(255,255,255,0.2);
            }
        """)
        self.motion_indicator.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.motion_indicator.hide()

        # Последний распознанный номер
        self.last_plate = QtWidgets.QLabel("—")
        self.last_plate.setParent(self.video_label)
        self.last_plate.setStyleSheet("""
            QLabel {
                background-color: rgba(40, 167, 69, 0.85);
                color: white;
                padding: 6px 12px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid rgba(255,255,255,0.2);
            }
        """)
        self.last_plate.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.last_plate.hide()

        # Статусная подсказка
        self.status_hint = QtWidgets.QLabel("")
        self.status_hint.setParent(self.video_label)
        self.status_hint.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.7);
                color: #00ffff;
                padding: 4px 8px;
                border-radius: 6px;
                font-size: 10px;
                border: 1px solid rgba(0,255,255,0.3);
            }
        """)
        self.status_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.status_hint.hide()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        rect = self.video_label.contentsRect()
        margin = 10
        
        # Позиционирование индикатора движения (верхний правый угол)
        indicator_size = self.motion_indicator.sizeHint()
        self.motion_indicator.move(
            rect.right() - indicator_size.width() - margin,
            rect.top() + margin
        )
        
        # Позиционирование номера (верхний левый угол)
        self.last_plate.move(rect.left() + margin, rect.top() + margin)
        
        # Позиционирование статуса (нижний левый угол)
        status_size = self.status_hint.sizeHint()
        self.status_hint.move(
            rect.left() + margin,
            rect.bottom() - status_size.height() - margin
        )

    def set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        self.video_label.setPixmap(pixmap)

    def set_motion_active(self, active: bool) -> None:
        self.motion_indicator.setVisible(active)

    def set_last_plate(self, plate: str) -> None:
        self.last_plate.setVisible(bool(plate))
        self.last_plate.setText(plate or "—")
        self.last_plate.adjustSize()

    def set_status(self, text: str) -> None:
        self.status_hint.setVisible(bool(text))
        self.status_hint.setText(text)
        if text:
            self.status_hint.adjustSize()


class ROIEditor(QtWidgets.QLabel):
    """Виджет предпросмотра канала с настраиваемой областью распознавания."""

    roi_changed = QtCore.pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__("Нет кадра")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(400, 260)
        self.setStyleSheet("""
            QLabel {
                background-color: #111;
                color: #888;
                border: 2px solid #333;
                border-radius: 4px;
                padding: 8px;
                font-weight: 500;
            }
        """)
        self._roi = {"x": 0, "y": 0, "width": 100, "height": 100}
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._rubber_band = QtWidgets.QRubberBand(
            QtWidgets.QRubberBand.Rectangle, self
        )
        self._rubber_band.setStyleSheet("""
            QRubberBand {
                border: 2px dashed #00ffff;
                background-color: rgba(0, 255, 255, 0.15);
            }
        """)
        self._origin: Optional[QtCore.QPoint] = None

    def set_roi(self, roi: Dict[str, int]) -> None:
        self._roi = {
            "x": int(roi.get("x", 0)),
            "y": int(roi.get("y", 0)),
            "width": int(roi.get("width", 100)),
            "height": int(roi.get("height", 100)),
        }
        self._roi["width"] = min(self._roi["width"], max(1, 100 - self._roi["x"]))
        self._roi["height"] = min(self._roi["height"], max(1, 100 - self._roi["y"]))
        self.update()

    def setPixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        self._pixmap = pixmap
        if pixmap is None:
            super().setPixmap(QtGui.QPixmap())
            self.setText("Нет кадра")
            return
        scaled = self._scaled_pixmap(self.size())
        super().setPixmap(scaled)
        self.setText("")

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._pixmap:
            super().setPixmap(self._scaled_pixmap(event.size()))

    def _scaled_pixmap(self, size: QtCore.QSize) -> QtGui.QPixmap:
        assert self._pixmap is not None
        return self._pixmap.scaled(
            size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )

    def _image_geometry(self) -> Optional[Tuple[QtCore.QPoint, QtCore.QSize]]:
        if self._pixmap is None:
            return None
        pixmap = self._scaled_pixmap(self.size())
        area = self.contentsRect()
        x = area.x() + (area.width() - pixmap.width()) // 2
        y = area.y() + (area.height() - pixmap.height()) // 2
        return QtCore.QPoint(x, y), pixmap.size()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        geom = self._image_geometry()
        if geom is None:
            return
        offset, size = geom
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        # Отрисовка ROI
        roi_rect = QtCore.QRect(
            offset.x() + int(size.width() * self._roi["x"] / 100),
            offset.y() + int(size.height() * self._roi["y"] / 100),
            int(size.width() * self._roi["width"] / 100),
            int(size.height() * self._roi["height"] / 100),
        )
        
        # Градиентная заливка
        gradient = QtGui.QLinearGradient(roi_rect.topLeft(), roi_rect.bottomRight())
        gradient.setColorAt(0, QtGui.QColor(0, 200, 0, 60))
        gradient.setColorAt(1, QtGui.QColor(0, 150, 0, 30))
        painter.setBrush(gradient)
        
        # Контур
        pen = QtGui.QPen(QtGui.QColor(0, 255, 0))
        pen.setWidth(2)
        pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(roi_rect)
        
        # Угловые маркеры
        marker_size = 8
        painter.setBrush(QtGui.QColor(0, 255, 0))
        painter.setPen(QtCore.Qt.NoPen)
        
        corners = [
            roi_rect.topLeft(),
            roi_rect.topRight(),
            roi_rect.bottomRight(),
            roi_rect.bottomLeft()
        ]
        
        for corner in corners:
            painter.drawEllipse(corner, marker_size, marker_size)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        geom = self._image_geometry()
        if geom is None:
            return
        offset, size = geom
        area_rect = QtCore.QRect(offset, size)
        if not area_rect.contains(event.pos()):
            return
        self._origin = event.pos()
        self._rubber_band.setGeometry(QtCore.QRect(self._origin, QtCore.QSize()))
        self._rubber_band.show()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._origin is None:
            return
        rect = QtCore.QRect(self._origin, event.pos()).normalized()
        self._rubber_band.setGeometry(rect)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._origin is None:
            return
        geom = self._image_geometry()
        self._rubber_band.hide()
        if geom is None:
            self._origin = None
            return
            
        offset, size = geom
        selection = self._rubber_band.geometry().intersected(
            QtCore.QRect(offset, size)
        )
        
        if selection.isValid() and selection.width() > 5 and selection.height() > 5:
            x_pct = max(0, min(100, int(
                (selection.left() - offset.x()) * 100 / size.width()
            )))
            y_pct = max(0, min(100, int(
                (selection.top() - offset.y()) * 100 / size.height()
            )))
            w_pct = max(1, min(100 - x_pct, int(
                selection.width() * 100 / size.width()
            )))
            h_pct = max(1, min(100 - y_pct, int(
                selection.height() * 100 / size.height()
            )))
            
            self._roi = {"x": x_pct, "y": y_pct, "width": w_pct, "height": h_pct}
            self.roi_changed.emit(self._roi)
            
        self._origin = None
        self.update()


class EventDetailView(QtWidgets.QWidget):
    """Отображение выбранного события: метаданные, кадр и область номера."""

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet("""
            QGroupBox {
                background-color: #1a1a1a;
                color: #f0f0f0;
                border: 2px solid #2a2a2a;
                border-radius: 6px;
                padding: 12px;
                margin-top: 6px;
                font-weight: 500;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #00ffff;
            }
            QLabel {
                color: #e0e0e0;
                padding: 2px;
            }
            QLabel[cssClass="data"] {
                color: #00ffaa;
                font-weight: bold;
                background-color: rgba(0,0,0,0.3);
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 4, 4, 4)

        # Кадр распознавания
        self.frame_preview = self._build_preview(
            "📸 Кадр распознавания",
            min_height=320,
            keep_aspect=True
        )
        layout.addWidget(self.frame_preview, stretch=3)

        # Нижний ряд: номер и метаданные
        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(12)
        
        # Кадр номера
        self.plate_preview = self._build_preview(
            "🚗 Область номера",
            min_size=QtCore.QSize(240, 150),
            keep_aspect=True
        )
        bottom_row.addWidget(self.plate_preview, 1)

        # Метаданные
        meta_group = QtWidgets.QGroupBox("📊 Данные распознавания")
        meta_layout = QtWidgets.QGridLayout(meta_group)
        meta_layout.setVerticalSpacing(6)
        meta_layout.setHorizontalSpacing(12)
        
        # Время
        time_label = QtWidgets.QLabel("Время:")
        self.time_value = QtWidgets.QLabel("—")
        self.time_value.setProperty("cssClass", "data")
        meta_layout.addWidget(time_label, 0, 0)
        meta_layout.addWidget(self.time_value, 0, 1)
        
        # Канал
        channel_label = QtWidgets.QLabel("Канал:")
        self.channel_value = QtWidgets.QLabel("—")
        self.channel_value.setProperty("cssClass", "data")
        meta_layout.addWidget(channel_label, 1, 0)
        meta_layout.addWidget(self.channel_value, 1, 1)
        
        # Номер
        plate_label = QtWidgets.QLabel("Гос. номер:")
        self.plate_value = QtWidgets.QLabel("—")
        self.plate_value.setProperty("cssClass", "data")
        self.plate_value.setStyleSheet("""
            QLabel {
                color: #ff9900;
                font-size: 14px;
                font-weight: bold;
                background-color: rgba(255,153,0,0.1);
                border: 1px solid rgba(255,153,0,0.3);
            }
        """)
        meta_layout.addWidget(plate_label, 2, 0)
        meta_layout.addWidget(self.plate_value, 2, 1)
        
        # Уверенность
        conf_label = QtWidgets.QLabel("Уверенность:")
        self.conf_value = QtWidgets.QLabel("—")
        self.conf_value.setProperty("cssClass", "data")
        meta_layout.addWidget(conf_label, 3, 0)
        meta_layout.addWidget(self.conf_value, 3, 1)
        
        bottom_row.addWidget(meta_group, 1)
        layout.addLayout(bottom_row, stretch=1)

    def _build_preview(
        self,
        title: str,
        min_height: int = 180,
        min_size: Optional[QtCore.QSize] = None,
        keep_aspect: bool = False,
    ) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        wrapper = QtWidgets.QVBoxLayout(group)
        wrapper.setContentsMargins(4, 4, 4, 4)
        
        label = QtWidgets.QLabel("Нет изображения")
        label.setAlignment(QtCore.Qt.AlignCenter)
        
        if min_size:
            label.setMinimumSize(min_size)
        else:
            label.setMinimumHeight(min_height)
            
        label.setStyleSheet("""
            QLabel {
                background-color: #0a0a0a;
                color: #666;
                border: 2px solid #222;
                border-radius: 4px;
                padding: 20px;
                font-weight: 500;
            }
        """)
        label.setScaledContents(not keep_aspect)
        wrapper.addWidget(label)
        
        group.display_label = label
        return group

    def clear(self) -> None:
        self.time_value.setText("—")
        self.channel_value.setText("—")
        self.plate_value.setText("—")
        self.conf_value.setText("—")
        
        for group in (self.frame_preview, self.plate_preview):
            label = group.display_label
            label.setPixmap(QtGui.QPixmap())
            label.setText("Нет изображения")

    def set_event(
        self,
        event: Optional[Dict],
        frame_image: Optional[QtGui.QImage] = None,
        plate_image: Optional[QtGui.QImage] = None,
    ) -> None:
        if event is None:
            self.clear()
            return

        self.time_value.setText(event.get("timestamp", "—"))
        self.channel_value.setText(event.get("channel", "—"))
        
        plate = event.get("plate") or "—"
        self.plate_value.setText(plate)
        
        conf = event.get("confidence")
        if conf is not None:
            conf_float = float(conf)
            color = "#00ff00" if conf_float > 0.8 else "#ff9900" if conf_float > 0.6 else "#ff3333"
            self.conf_value.setText(f"{conf_float:.2%}")
            self.conf_value.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-weight: bold;
                    background-color: rgba({color[1:3]}, {color[3:5]}, {color[5:7]}, 0.1);
                }}
            """)
        else:
            self.conf_value.setText("—")

        self._set_image(self.frame_preview, frame_image, keep_aspect=True)
        self._set_image(self.plate_preview, plate_image, keep_aspect=True)

    def _set_image(
        self,
        group: QtWidgets.QGroupBox,
        image: Optional[QtGui.QImage],
        keep_aspect: bool = False,
    ) -> None:
        label = group.display_label
        if image is None:
            label.setPixmap(QtGui.QPixmap())
            label.setText("Нет изображения")
            return
            
        label.setText("")
        pixmap = QtGui.QPixmap.fromImage(image)
        
        if keep_aspect:
            pixmap = pixmap.scaled(
                label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            
        label.setPixmap(pixmap)


class MainWindow(QtWidgets.QMainWindow):
    """Главное окно приложения ANPR с вкладками наблюдения, поиска и настроек."""

    GRID_VARIANTS = ["1x1", "1x2", "2x2", "2x3", "3x3"]
    
    # Современные стили
    APP_STYLE = """
        * {
            font-family: 'Segoe UI', 'Arial', sans-serif;
            font-size: 13px;
        }
        
        QMainWindow {
            background-color: #1e1e1e;
        }
        
        QTabWidget::pane {
            border: 1px solid #2a2a2a;
            border-radius: 6px;
            background-color: #252525;
            margin: 4px;
        }
        
        QTabBar::tab {
            background-color: #2a2a2a;
            color: #aaa;
            padding: 10px 20px;
            margin-right: 2px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            border: 1px solid #333;
            border-bottom: none;
            font-weight: 500;
        }
        
        QTabBar::tab:selected {
            background-color: #252525;
            color: #00ffff;
            border-bottom: 2px solid #00ffff;
        }
        
        QTabBar::tab:hover {
            background-color: #303030;
            color: #e0e0e0;
        }
        
        QGroupBox {
            background-color: #2a2a2a;
            color: #f0f0f0;
            border: 2px solid #333;
            border-radius: 8px;
            padding: 12px;
            margin-top: 8px;
            font-weight: 500;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
            color: #00ffff;
            font-weight: 600;
        }
        
        QLabel {
            color: #e0e0e0;
        }
        
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {
            background-color: #1a1a1a;
            color: #f0f0f0;
            border: 2px solid #333;
            border-radius: 4px;
            padding: 6px 8px;
            selection-background-color: #00aaff;
        }
        
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, 
        QComboBox:focus, QDateTimeEdit:focus {
            border-color: #00aaff;
        }
        
        QPushButton {
            background-color: #0088cc;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            min-height: 32px;
        }
        
        QPushButton:hover {
            background-color: #0099ee;
        }
        
        QPushButton:pressed {
            background-color: #0077bb;
        }
        
        QPushButton:disabled {
            background-color: #555;
            color: #888;
        }
        
        QCheckBox {
            color: #e0e0e0;
            spacing: 6px;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #555;
            border-radius: 4px;
            background-color: #2a2a2a;
        }
        
        QCheckBox::indicator:checked {
            background-color: #0088cc;
            border-color: #0088cc;
        }
        
        QComboBox::drop-down {
            border: none;
            background-color: #333;
            border-radius: 0 4px 4px 0;
            width: 24px;
        }
        
        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #aaa;
        }
        
        QSpinBox::up-button, QSpinBox::down-button {
            background-color: #333;
            border: none;
            border-radius: 2px;
            width: 20px;
        }
        
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
            background-color: #333;
            border: none;
            border-radius: 2px;
            width: 20px;
        }
        
        QScrollBar:vertical {
            background-color: #2a2a2a;
            width: 12px;
            border-radius: 6px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #555;
            border-radius: 6px;
            min-height: 20px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #666;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
    """
    
    TABLE_STYLE = """
        QTableWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
            gridline-color: #333;
            border: 1px solid #333;
            border-radius: 4px;
            alternate-background-color: #222;
        }
        
        QHeaderView::section {
            background-color: #2a2a2a;
            color: #00ffff;
            padding: 8px;
            border: none;
            border-right: 1px solid #333;
            font-weight: 600;
        }
        
        QHeaderView::section:last {
            border-right: none;
        }
        
        QTableWidget::item {
            padding: 6px;
            border-bottom: 1px solid #2a2a2a;
        }
        
        QTableWidget::item:selected {
            background-color: #0088cc;
            color: white;
        }
        
        QTableWidget::item:hover {
            background-color: #303030;
        }
    """
    
    LIST_STYLE = """
        QListWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
            border: 2px solid #333;
            border-radius: 6px;
            padding: 4px;
        }
        
        QListWidget::item {
            padding: 8px 12px;
            border-radius: 4px;
            margin: 2px;
        }
        
        QListWidget::item:selected {
            background-color: #0088cc;
            color: white;
        }
        
        QListWidget::item:hover {
            background-color: #303030;
        }
    """

    def __init__(self, settings: Optional[SettingsManager] = None) -> None:
        super().__init__()
        
        # Настройки окна
        self.setWindowTitle("🚗 ANPR Desktop - Система распознавания номеров")
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        
        # Устанавливаем размеры окна с учетом безопасной зоны
        screen_geometry = QtWidgets.QApplication.primaryScreen().availableGeometry()
        window_width = min(1400, screen_geometry.width() - 100)
        window_height = min(900, screen_geometry.height() - 100)
        self.resize(window_width, window_height)
        
        # Центрирование окна
        self.move(
            (screen_geometry.width() - window_width) // 2,
            (screen_geometry.height() - window_height) // 2
        )
        
        # Установка минимального размера
        self.setMinimumSize(1024, 600)
        
        # Настройка поведения окна
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowFullscreenButtonHint
        )
        
        # Применение стилей
        self.setStyleSheet(self.APP_STYLE)
        
        self.settings = settings or SettingsManager()
        self.db = EventDatabase(self.settings.get_db_path())

        self.channel_workers: List[ChannelWorker] = []
        self.channel_labels: Dict[str, ChannelView] = {}
        self.event_images: Dict[int, Tuple[Optional[QtGui.QImage], Optional[QtGui.QImage]]] = {}
        self.event_cache: Dict[int, Dict] = {}

        # Создание вкладок
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QtWidgets.QTabWidget.North)
        
        self.observation_tab = self._build_observation_tab()
        self.search_tab = self._build_search_tab()
        self.settings_tab = self._build_settings_tab()

        self.tabs.addTab(self.observation_tab, "👁️ Наблюдение")
        self.tabs.addTab(self.search_tab, "🔍 Поиск")
        self.tabs.addTab(self.settings_tab, "⚙️ Настройки")

        self.setCentralWidget(self.tabs)
        self._build_status_bar()
        self._start_system_monitoring()
        self._refresh_events_table()
        self._start_channels()
        
        # Таймер для проверки геометрии окна
        self.geometry_timer = QtCore.QTimer(self)
        self.geometry_timer.timeout.connect(self._ensure_window_safety)
        self.geometry_timer.start(1000)

    def _ensure_window_safety(self) -> None:
        """Убедиться, что окно не выходит за пределы экрана."""
        screen_geometry = QtWidgets.QApplication.primaryScreen().availableGeometry()
        window_geometry = self.frameGeometry()
        
        if not screen_geometry.contains(window_geometry):
            # Если окно вышло за пределы, перемещаем его обратно
            new_x = max(screen_geometry.left(), min(
                window_geometry.x(),
                screen_geometry.right() - window_geometry.width()
            ))
            new_y = max(screen_geometry.top(), min(
                window_geometry.y(),
                screen_geometry.bottom() - window_geometry.height()
            ))
            self.move(new_x, new_y)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setStyleSheet("""
            QStatusBar {
                background-color: #2a2a2a;
                color: #aaa;
                border-top: 2px solid #333;
                padding: 4px 12px;
            }
        """)
        
        # Левая часть: информация о приложении
        app_info = QtWidgets.QLabel("🚗 ANPR Desktop v1.0")
        app_info.setStyleSheet("color: #00ffff; font-weight: bold;")
        status.addWidget(app_info)
        
        status.addPermanentWidget(QtWidgets.QLabel("|"))
        
        # Статистика событий
        self.event_count_label = QtWidgets.QLabel("События: 0")
        self.event_count_label.setToolTip("Количество событий в базе данных")
        status.addPermanentWidget(self.event_count_label)
        
        status.addPermanentWidget(QtWidgets.QLabel("|"))
        
        # Активные каналы
        self.active_channels_label = QtWidgets.QLabel("Каналы: 0/0")
        self.active_channels_label.setToolTip("Активные/Всего каналов")
        status.addPermanentWidget(self.active_channels_label)
        
        status.addPermanentWidget(QtWidgets.QLabel("|"))
        
        # Системные ресурсы
        self.cpu_label = QtWidgets.QLabel("CPU: —")
        self.cpu_label.setToolTip("Загрузка процессора")
        status.addPermanentWidget(self.cpu_label)
        
        status.addPermanentWidget(QtWidgets.QLabel("|"))
        
        self.ram_label = QtWidgets.QLabel("RAM: —")
        self.ram_label.setToolTip("Использование оперативной памяти")
        status.addPermanentWidget(self.ram_label)

    def _start_system_monitoring(self) -> None:
        self.stats_timer = QtCore.QTimer(self)
        self.stats_timer.setInterval(2000)  # Обновлять каждые 2 секунды
        self.stats_timer.timeout.connect(self._update_system_stats)
        self.stats_timer.start()
        self._update_system_stats()

    def _update_system_stats(self) -> None:
        cpu_percent = psutil.cpu_percent(interval=None)
        ram_percent = psutil.virtual_memory().percent
        
        # Форматирование значений
        self.cpu_label.setText(f"CPU: {cpu_percent:.0f}%")
        
        # Цветовое кодирование
        cpu_color = "#00ff00" if cpu_percent < 50 else "#ff9900" if cpu_percent < 80 else "#ff3333"
        ram_color = "#00ff00" if ram_percent < 60 else "#ff9900" if ram_percent < 85 else "#ff3333"
        
        self.cpu_label.setStyleSheet(f"color: {cpu_color};")
        self.ram_label.setStyleSheet(f"color: {ram_color};")
        self.ram_label.setText(f"RAM: {ram_percent:.0f}%")
        
        # Обновление счетчика событий
        try:
            count = self.db.get_event_count()
            self.event_count_label.setText(f"События: {count}")
        except:
            pass
        
        # Обновление информации о каналах
        active = sum(1 for w in self.channel_workers if w.isRunning())
        total = len(self.settings.get_channels())
        self.active_channels_label.setText(f"Каналы: {active}/{total}")

    # ------------------ Наблюдение ------------------
    def _build_observation_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # Левая колонка: сетка камер
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(8)
        
        # Панель управления сеткой
        controls_panel = QtWidgets.QFrame()
        controls_panel.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 2px solid #333;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        controls_layout = QtWidgets.QHBoxLayout(controls_panel)
        
        controls_layout.addWidget(QtWidgets.QLabel("📐 Сетка камер:"))
        
        self.grid_selector = QtWidgets.QComboBox()
        self.grid_selector.addItems(self.GRID_VARIANTS)
        self.grid_selector.setCurrentText(self.settings.get_grid())
        self.grid_selector.setMinimumWidth(100)
        self.grid_selector.currentTextChanged.connect(self._on_grid_changed)
        controls_layout.addWidget(self.grid_selector)
        
        controls_layout.addStretch()
        
        # Кнопка обновления
        refresh_btn = QtWidgets.QPushButton("🔄 Обновить")
        refresh_btn.setToolTip("Обновить сетку камер")
        refresh_btn.clicked.connect(self._draw_grid)
        refresh_btn.setMaximumWidth(120)
        controls_layout.addWidget(refresh_btn)
        
        left_column.addWidget(controls_panel)

        # Сетка камер
        self.grid_widget = QtWidgets.QWidget()
        self.grid_widget.setStyleSheet("background-color: transparent;")
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        
        left_column.addWidget(self.grid_widget, stretch=1)
        layout.addLayout(left_column, stretch=3)

        # Правая колонка: детали и события
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(12)

        # Детали события
        details_group = QtWidgets.QGroupBox("📋 Информация о событии")
        details_layout = QtWidgets.QVBoxLayout(details_group)
        self.event_detail = EventDetailView()
        details_layout.addWidget(self.event_detail)
        right_column.addWidget(details_group, stretch=2)

        # Список событий
        events_group = QtWidgets.QGroupBox("📜 Последние события")
        events_layout = QtWidgets.QVBoxLayout(events_group)
        
        # Панель управления событиями
        events_controls = QtWidgets.QHBoxLayout()
        events_controls.addWidget(QtWidgets.QLabel("Показать:"))
        
        self.events_limit = QtWidgets.QComboBox()
        self.events_limit.addItems(["50", "100", "200", "500", "Все"])
        self.events_limit.setCurrentText("200")
        self.events_limit.currentTextChanged.connect(self._refresh_events_table)
        events_controls.addWidget(self.events_limit)
        
        events_controls.addStretch()
        
        clear_btn = QtWidgets.QPushButton("🗑️ Очистить")
        clear_btn.setToolTip("Очистить таблицу событий")
        clear_btn.clicked.connect(lambda: self.events_table.setRowCount(0))
        clear_btn.setMaximumWidth(100)
        events_controls.addWidget(clear_btn)
        
        refresh_events_btn = QtWidgets.QPushButton("🔄 Обновить")
        refresh_events_btn.setToolTip("Обновить список событий")
        refresh_events_btn.clicked.connect(self._refresh_events_table)
        refresh_events_btn.setMaximumWidth(120)
        events_controls.addWidget(refresh_events_btn)
        
        events_layout.addLayout(events_controls)
        
        # Таблица событий
        self.events_table = QtWidgets.QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(["Время", "Гос. номер", "Канал", "Уверенность"])
        self.events_table.setStyleSheet(self.TABLE_STYLE)
        self.events_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.events_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        
        self.events_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.events_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.events_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setAlternatingRowColors(True)
        self.events_table.itemSelectionChanged.connect(self._on_event_selected)
        
        events_layout.addWidget(self.events_table)
        right_column.addWidget(events_group, stretch=1)

        layout.addLayout(right_column, stretch=2)

        self._draw_grid()
        return widget

    @staticmethod
    def _prepare_optional_datetime(widget: QtWidgets.QDateTimeEdit) -> None:
        widget.setCalendarPopup(True)
        widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        min_dt = QtCore.QDateTime.fromSecsSinceEpoch(0)
        widget.setMinimumDateTime(min_dt)
        widget.setSpecialValueText("Не выбрано")
        widget.setDateTime(min_dt)

    @staticmethod
    def _get_datetime_value(widget: QtWidgets.QDateTimeEdit) -> Optional[str]:
        if widget.dateTime() == widget.minimumDateTime():
            return None
        return widget.dateTime().toString(QtCore.Qt.ISODate)

    def _draw_grid(self) -> None:
        # Очистка текущей сетки
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        self.channel_labels.clear()
        channels = self.settings.get_channels()
        rows, cols = map(int, self.grid_selector.currentText().split("x"))
        
        index = 0
        for row in range(rows):
            for col in range(cols):
                if index >= len(channels):
                    # Создаем заглушку для пустых ячеек
                    placeholder = QtWidgets.QLabel(f"Канал {index+1}\n(не настроен)")
                    placeholder.setAlignment(QtCore.Qt.AlignCenter)
                    placeholder.setStyleSheet("""
                        QLabel {
                            background-color: #1a1a1a;
                            color: #666;
                            border: 2px dashed #333;
                            border-radius: 6px;
                            padding: 20px;
                            font-weight: 500;
                        }
                    """)
                    self.grid_layout.addWidget(placeholder, row, col)
                else:
                    channel_name = channels[index].get("name", f"Канал {index+1}")
                    label = ChannelView(channel_name)
                    self.channel_labels[channel_name] = label
                    self.grid_layout.addWidget(label, row, col)
                
                index += 1
        
        # Выравнивание по ширине
        for col in range(cols):
            self.grid_layout.setColumnStretch(col, 1)
        
        for row in range(rows):
            self.grid_layout.setRowStretch(row, 1)

    def _on_grid_changed(self, grid: str) -> None:
        self.settings.save_grid(grid)
        self._draw_grid()

    def _start_channels(self) -> None:
        self._stop_workers()
        self.channel_workers = []
        reconnect_conf = self.settings.get_reconnect()
        
        for channel_conf in self.settings.get_channels():
            source = str(channel_conf.get("source", "")).strip()
            channel_name = channel_conf.get("name", "Канал")
            
            if not source:
                label = self.channel_labels.get(channel_name)
                if label:
                    label.set_status("⚠️ Нет источника")
                continue
                
            worker = ChannelWorker(
                channel_conf,
                self.settings.get_db_path(),
                self.settings.get_screenshot_dir(),
                reconnect_conf,
            )
            worker.frame_ready.connect(self._update_frame)
            worker.event_ready.connect(self._handle_event)
            worker.status_ready.connect(self._handle_status)
            self.channel_workers.append(worker)
            worker.start()

    def _stop_workers(self) -> None:
        for worker in self.channel_workers:
            worker.stop()
            worker.wait(2000)
        self.channel_workers = []

    def _update_frame(self, channel_name: str, image: QtGui.QImage) -> None:
        label = self.channel_labels.get(channel_name)
        if not label:
            return
            
        target_size = label.video_label.contentsRect().size()
        pixmap = QtGui.QPixmap.fromImage(image).scaled(
            target_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        label.set_pixmap(pixmap)

    @staticmethod
    def _load_image_from_path(path: Optional[str]) -> Optional[QtGui.QImage]:
        if not path or not os.path.exists(path):
            return None
            
        try:
            image = cv2.imread(path)
            if image is None:
                return None
                
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb.shape
            bytes_per_line = 3 * width
            
            return QtGui.QImage(
                rgb.data, width, height, bytes_per_line,
                QtGui.QImage.Format_RGB888
            ).copy()
        except Exception as e:
            logger.error(f"Ошибка загрузки изображения {path}: {e}")
            return None

    def _handle_event(self, event: Dict) -> None:
        event_id = int(event.get("id", 0))
        frame_image = event.get("frame_image")
        plate_image = event.get("plate_image")
        
        if event_id:
            self.event_images[event_id] = (frame_image, plate_image)
            self.event_cache[event_id] = event
            
        channel_label = self.channel_labels.get(event.get("channel", ""))
        if channel_label:
            channel_label.set_last_plate(event.get("plate", ""))
            
        self._refresh_events_table(select_id=event_id)
        self._show_event_details(event_id)

    def _handle_status(self, channel: str, status: str) -> None:
        label = self.channel_labels.get(channel)
        if label:
            normalized = status.lower()
            if "движ" in normalized or "motion" in normalized:
                label.set_status("")
                label.set_motion_active("обнаружено" in normalized)
            else:
                label.set_status(status)
                label.set_motion_active(False)

    def _on_event_selected(self) -> None:
        selected = self.events_table.selectedItems()
        if not selected:
            return
            
        event_id_item = selected[0]
        event_id = int(event_id_item.data(QtCore.Qt.UserRole) or 0)
        self._show_event_details(event_id)

    def _show_event_details(self, event_id: int) -> None:
        event = self.event_cache.get(event_id)
        if not event:
            return
            
        images = self.event_images.get(event_id, (None, None))
        frame_image, plate_image = images
        
        if frame_image is None and event.get("frame_path"):
            frame_image = self._load_image_from_path(event.get("frame_path"))
        if plate_image is None and event.get("plate_path"):
            plate_image = self._load_image_from_path(event.get("plate_path"))
            
        self.event_images[event_id] = (frame_image, plate_image)
        self.event_detail.set_event(event, frame_image, plate_image)

    def _refresh_events_table(self, select_id: Optional[int] = None) -> None:
        limit_text = self.events_limit.currentText()
        limit = None if limit_text == "Все" else int(limit_text)
        
        rows = self.db.fetch_recent(limit=limit or 200)
        self.events_table.setRowCount(0)
        self.event_cache = {}
        
        for row in rows:
            # Преобразуем sqlite3.Row в словарь
            row_data = dict(row)
            event_id = int(row_data["id"])
            self.event_cache[event_id] = row_data
            
            row_index = self.events_table.rowCount()
            self.events_table.insertRow(row_index)
            
            # Время
            time_item = QtWidgets.QTableWidgetItem(row_data["timestamp"])
            time_item.setData(QtCore.Qt.UserRole, event_id)
            self.events_table.setItem(row_index, 0, time_item)
            
            # Номер
            plate_item = QtWidgets.QTableWidgetItem(row_data["plate"])
            self.events_table.setItem(row_index, 1, plate_item)
            
            # Канал
            channel_item = QtWidgets.QTableWidgetItem(row_data["channel"])
            self.events_table.setItem(row_index, 2, channel_item)
            
            # Уверенность
            conf = row_data.get("confidence")
            if conf is not None:
                conf_value = float(conf)
                conf_item = QtWidgets.QTableWidgetItem(f"{conf_value:.2%}")
                
                # Цветовое кодирование уверенности
                if conf_value > 0.8:
                    conf_item.setForeground(QtGui.QColor(0, 255, 0))
                elif conf_value > 0.6:
                    conf_item.setForeground(QtGui.QColor(255, 165, 0))
                else:
                    conf_item.setForeground(QtGui.QColor(255, 0, 0))
                    
                self.events_table.setItem(row_index, 3, conf_item)

        # Автоматическая сортировка по времени (новые сверху)
        self.events_table.sortItems(0, QtCore.Qt.DescendingOrder)
        
        # Выбор строки если указан ID
        if select_id:
            for row in range(self.events_table.rowCount()):
                item = self.events_table.item(row, 0)
                if item and int(item.data(QtCore.Qt.UserRole) or 0) == select_id:
                    self.events_table.selectRow(row)
                    self.events_table.scrollToItem(item)
                    break

    def _run_plate_search(self) -> None:
        start = self._get_datetime_value(self.search_from)
        end = self._get_datetime_value(self.search_to)
        plate_fragment = self.search_plate.text().strip()
        
        rows = self.db.search_by_plate(
            plate_fragment if plate_fragment else None,
            start=start or None,
            end=end or None
        )
        
        self.search_table.setRowCount(0)
        
        for row in rows:
            # Преобразуем sqlite3.Row в словарь
            row_data = dict(row)
            row_index = self.search_table.rowCount()
            self.search_table.insertRow(row_index)
            
            # Время
            self.search_table.setItem(
                row_index, 0,
                QtWidgets.QTableWidgetItem(row_data["timestamp"])
            )
            
            # Канал
            self.search_table.setItem(
                row_index, 1,
                QtWidgets.QTableWidgetItem(row_data["channel"])
            )
            
            # Номер
            self.search_table.setItem(
                row_index, 2,
                QtWidgets.QTableWidgetItem(row_data["plate"])
            )
            
            # Уверенность
            conf = row_data.get("confidence") or 0
            conf_item = QtWidgets.QTableWidgetItem(f"{float(conf):.2%}")
            
            if float(conf) > 0.8:
                conf_item.setForeground(QtGui.QColor(0, 255, 0))
            elif float(conf) > 0.6:
                conf_item.setForeground(QtGui.QColor(255, 165, 0))
            else:
                conf_item.setForeground(QtGui.QColor(255, 0, 0))
                
            self.search_table.setItem(row_index, 3, conf_item)
            
            # Источник
            self.search_table.setItem(
                row_index, 4,
                QtWidgets.QTableWidgetItem(row_data.get("source", ""))
            )
        
        self.results_count_label.setText(f"Найдено: {len(rows)}")
        
        # Сортировка по времени (новые сверху)
        if rows:
            self.search_table.sortItems(0, QtCore.Qt.DescendingOrder)
            

    # ------------------ Настройки ------------------
    def _build_settings_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        tabs = QtWidgets.QTabWidget()
        tabs.setTabPosition(QtWidgets.QTabWidget.North)
        
        tabs.addTab(self._build_general_settings_tab(), "🌐 Общие")
        tabs.addTab(self._build_channel_settings_tab(), "📹 Каналы")
        
        layout.addWidget(tabs)
        return widget

    def _build_general_settings_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # Настройки переподключения
        reconnect_group = QtWidgets.QGroupBox("🔁 Автоматическое переподключение")
        reconnect_layout = QtWidgets.QGridLayout(reconnect_group)
        reconnect_layout.setVerticalSpacing(8)
        reconnect_layout.setHorizontalSpacing(12)
        
        row = 0
        self.reconnect_on_loss_checkbox = QtWidgets.QCheckBox(
            "Переподключение при потере сигнала"
        )
        reconnect_layout.addWidget(self.reconnect_on_loss_checkbox, row, 0, 1, 2)
        
        row += 1
        reconnect_layout.addWidget(
            QtWidgets.QLabel("Таймаут ожидания кадра:"), row, 0
        )
        self.frame_timeout_input = QtWidgets.QSpinBox()
        self.frame_timeout_input.setRange(1, 300)
        self.frame_timeout_input.setSuffix(" с")
        self.frame_timeout_input.setToolTip(
            "Сколько секунд ждать кадр перед попыткой переподключения"
        )
        reconnect_layout.addWidget(self.frame_timeout_input, row, 1)
        
        row += 1
        reconnect_layout.addWidget(
            QtWidgets.QLabel("Интервал между попытками:"), row, 0
        )
        self.retry_interval_input = QtWidgets.QSpinBox()
        self.retry_interval_input.setRange(1, 300)
        self.retry_interval_input.setSuffix(" с")
        self.retry_interval_input.setToolTip(
            "Интервал между попытками переподключения при потере сигнала"
        )
        reconnect_layout.addWidget(self.retry_interval_input, row, 1)
        
        row += 1
        self.periodic_reconnect_checkbox = QtWidgets.QCheckBox(
            "Переподключение по таймеру"
        )
        reconnect_layout.addWidget(self.periodic_reconnect_checkbox, row, 0, 1, 2)
        
        row += 1
        reconnect_layout.addWidget(
            QtWidgets.QLabel("Интервал переподключения:"), row, 0
        )
        self.periodic_interval_input = QtWidgets.QSpinBox()
        self.periodic_interval_input.setRange(1, 1440)
        self.periodic_interval_input.setSuffix(" мин")
        self.periodic_interval_input.setToolTip(
            "Плановое переподключение каждые N минут"
        )
        reconnect_layout.addWidget(self.periodic_interval_input, row, 1)
        
        layout.addWidget(reconnect_group)

        # Пути к файлам
        paths_group = QtWidgets.QGroupBox("📁 Пути к файлам")
        paths_layout = QtWidgets.QFormLayout(paths_group)
        paths_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        
        # Папка базы данных
        db_row = QtWidgets.QHBoxLayout()
        self.db_dir_input = QtWidgets.QLineEdit()
        browse_db_btn = QtWidgets.QPushButton("📂 Выбрать...")
        browse_db_btn.clicked.connect(self._choose_db_dir)
        browse_db_btn.setMaximumWidth(100)
        db_row.addWidget(self.db_dir_input)
        db_row.addWidget(browse_db_btn)
        paths_layout.addRow("Папка БД:", db_row)
        
        # Папка скриншотов
        screenshot_row = QtWidgets.QHBoxLayout()
        self.screenshot_dir_input = QtWidgets.QLineEdit()
        browse_screenshot_btn = QtWidgets.QPushButton("📂 Выбрать...")
        browse_screenshot_btn.clicked.connect(self._choose_screenshot_dir)
        browse_screenshot_btn.setMaximumWidth(100)
        screenshot_row.addWidget(self.screenshot_dir_input)
        screenshot_row.addWidget(browse_screenshot_btn)
        paths_layout.addRow("Папка для скриншотов:", screenshot_row)
        
        layout.addWidget(paths_group)

        # Кнопки сохранения
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch()
        
        save_general_btn = QtWidgets.QPushButton("💾 Сохранить настройки")
        save_general_btn.clicked.connect(self._save_general_settings)
        save_general_btn.setMinimumWidth(180)
        button_row.addWidget(save_general_btn)
        
        restart_btn = QtWidgets.QPushButton("🔄 Перезапустить каналы")
        restart_btn.clicked.connect(self._start_channels)
        restart_btn.setMinimumWidth(180)
        button_row.addWidget(restart_btn)
        
        layout.addLayout(button_row)
        layout.addStretch()

        scroll.setWidget(content)
        
        main_layout = QtWidgets.QVBoxLayout(widget)
        main_layout.addWidget(scroll)
        
        self._load_general_settings()
        return widget

    def _build_channel_settings_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # Левая панель: список каналов
        left_panel = QtWidgets.QVBoxLayout()
        left_panel.setSpacing(8)
        
        channels_list_group = QtWidgets.QGroupBox("📋 Каналы")
        channels_list_layout = QtWidgets.QVBoxLayout(channels_list_group)
        
        self.channels_list = QtWidgets.QListWidget()
        self.channels_list.setMinimumWidth(200)
        self.channels_list.setMaximumWidth(250)
        self.channels_list.setStyleSheet(self.LIST_STYLE)
        self.channels_list.currentRowChanged.connect(self._load_channel_form)
        channels_list_layout.addWidget(self.channels_list)
        
        # Кнопки управления списком
        list_buttons = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("➕ Добавить")
        add_btn.clicked.connect(self._add_channel)
        remove_btn = QtWidgets.QPushButton("🗑️ Удалить")
        remove_btn.clicked.connect(self._remove_channel)
        list_buttons.addWidget(add_btn)
        list_buttons.addWidget(remove_btn)
        channels_list_layout.addLayout(list_buttons)
        
        left_panel.addWidget(channels_list_group)
        left_panel.addStretch()
        layout.addLayout(left_panel)

        # Центральная панель: предпросмотр ROI
        center_panel = QtWidgets.QVBoxLayout()
        center_panel.setSpacing(8)
        
        preview_group = QtWidgets.QGroupBox("👁️ Предпросмотр ROI")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        
        self.preview = ROIEditor()
        self.preview.roi_changed.connect(self._on_roi_drawn)
        preview_layout.addWidget(self.preview)
        
        # Кнопка обновления кадра
        refresh_frame_btn = QtWidgets.QPushButton("🔄 Обновить кадр")
        refresh_frame_btn.clicked.connect(self._refresh_preview_frame)
        refresh_frame_btn.setMaximumWidth(150)
        preview_layout.addWidget(refresh_frame_btn, alignment=QtCore.Qt.AlignCenter)
        
        center_panel.addWidget(preview_group)
        center_panel.addStretch()
        layout.addLayout(center_panel, stretch=2)

        # Правая панель: настройки канала
        right_panel = QtWidgets.QVBoxLayout()
        right_panel.setSpacing(12)
        
        # Общие настройки канала
        channel_group = QtWidgets.QGroupBox("⚙️ Настройки канала")
        channel_form = QtWidgets.QFormLayout(channel_group)
        channel_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        
        self.channel_name_input = QtWidgets.QLineEdit()
        self.channel_name_input.setPlaceholderText("Введите название канала...")
        channel_form.addRow("Название:", self.channel_name_input)
        
        self.channel_source_input = QtWidgets.QLineEdit()
        self.channel_source_input.setPlaceholderText("rtsp://... или номер устройства")
        channel_form.addRow("Источник/RTSP:", self.channel_source_input)
        
        right_panel.addWidget(channel_group)

        # Настройки распознавания
        recognition_group = QtWidgets.QGroupBox("🔍 Настройки распознавания")
        recognition_form = QtWidgets.QFormLayout(recognition_group)
        
        self.best_shots_input = QtWidgets.QSpinBox()
        self.best_shots_input.setRange(1, 50)
        self.best_shots_input.setToolTip(
            "Количество бестшотов, участвующих в консенсусе трека"
        )
        recognition_form.addRow("Бестшоты на трек:", self.best_shots_input)
        
        self.cooldown_input = QtWidgets.QSpinBox()
        self.cooldown_input.setRange(0, 3600)
        self.cooldown_input.setToolTip(
            "Интервал (в секундах), в течение которого не создается повторное "
            "событие для того же номера"
        )
        recognition_form.addRow("Пауза повтора (сек):", self.cooldown_input)
        
        self.min_conf_input = QtWidgets.QDoubleSpinBox()
        self.min_conf_input.setRange(0.0, 1.0)
        self.min_conf_input.setSingleStep(0.05)
        self.min_conf_input.setDecimals(2)
        self.min_conf_input.setToolTip(
            "Минимальная уверенность OCR (0-1) для приема результата; "
            "ниже — помечается как нечитаемое"
        )
        recognition_form.addRow("Мин. уверенность OCR:", self.min_conf_input)
        
        right_panel.addWidget(recognition_group)

        # Настройки детектора движения
        motion_group = QtWidgets.QGroupBox("🎬 Детектор движения")
        motion_form = QtWidgets.QFormLayout(motion_group)
        
        self.detection_mode_input = QtWidgets.QComboBox()
        self.detection_mode_input.addItem("Постоянное", "continuous")
        self.detection_mode_input.addItem("Детектор движения", "motion")
        motion_form.addRow("Обнаружение ТС:", self.detection_mode_input)
        
        self.detector_stride_input = QtWidgets.QSpinBox()
        self.detector_stride_input.setRange(1, 12)
        self.detector_stride_input.setToolTip(
            "Запускать YOLO на каждом N-м кадре в зоне распознавания, "
            "чтобы снизить нагрузку"
        )
        motion_form.addRow("Шаг инференса (кадр):", self.detector_stride_input)
        
        self.motion_threshold_input = QtWidgets.QDoubleSpinBox()
        self.motion_threshold_input.setRange(0.0, 1.0)
        self.motion_threshold_input.setDecimals(3)
        self.motion_threshold_input.setSingleStep(0.005)
        self.motion_threshold_input.setToolTip(
            "Порог чувствительности по площади изменения внутри ROI"
        )
        motion_form.addRow("Порог движения:", self.motion_threshold_input)
        
        self.motion_stride_input = QtWidgets.QSpinBox()
        self.motion_stride_input.setRange(1, 30)
        self.motion_stride_input.setToolTip(
            "Обрабатывать каждый N-й кадр для поиска движения"
        )
        motion_form.addRow("Частота анализа (кадр):", self.motion_stride_input)
        
        self.motion_activation_frames_input = QtWidgets.QSpinBox()
        self.motion_activation_frames_input.setRange(1, 60)
        self.motion_activation_frames_input.setToolTip(
            "Сколько кадров подряд должно быть движение, чтобы включить распознавание"
        )
        motion_form.addRow("Мин. кадров с движением:", self.motion_activation_frames_input)
        
        self.motion_release_frames_input = QtWidgets.QSpinBox()
        self.motion_release_frames_input.setRange(1, 120)
        self.motion_release_frames_input.setToolTip(
            "Сколько кадров без движения нужно, чтобы остановить распознавание"
        )
        motion_form.addRow("Мин. кадров без движения:", self.motion_release_frames_input)
        
        right_panel.addWidget(motion_group)

        # Настройки ROI
        roi_group = QtWidgets.QGroupBox("📍 Зона распознавания (ROI)")
        roi_layout = QtWidgets.QGridLayout(roi_group)
        roi_layout.setVerticalSpacing(6)
        roi_layout.setHorizontalSpacing(8)
        
        self.roi_x_input = QtWidgets.QSpinBox()
        self.roi_x_input.setRange(0, 100)
        self.roi_y_input = QtWidgets.QSpinBox()
        self.roi_y_input.setRange(0, 100)
        self.roi_w_input = QtWidgets.QSpinBox()
        self.roi_w_input.setRange(1, 100)
        self.roi_h_input = QtWidgets.QSpinBox()
        self.roi_h_input.setRange(1, 100)
        
        for spin in (self.roi_x_input, self.roi_y_input, 
                    self.roi_w_input, self.roi_h_input):
            spin.valueChanged.connect(self._on_roi_inputs_changed)
        
        roi_layout.addWidget(QtWidgets.QLabel("X (%):"), 0, 0)
        roi_layout.addWidget(self.roi_x_input, 0, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Y (%):"), 1, 0)
        roi_layout.addWidget(self.roi_y_input, 1, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Ширина (%):"), 2, 0)
        roi_layout.addWidget(self.roi_w_input, 2, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Высота (%):"), 3, 0)
        roi_layout.addWidget(self.roi_h_input, 3, 1)
        
        right_panel.addWidget(roi_group)

        # Кнопка сохранения
        save_btn = QtWidgets.QPushButton("💾 Сохранить канал")
        save_btn.clicked.connect(self._save_channel)
        save_btn.setMinimumHeight(36)
        right_panel.addWidget(save_btn)
        right_panel.addStretch()

        layout.addLayout(right_panel, stretch=2)

        self._load_general_settings()
        self._reload_channels_list()
        return widget

    def _reload_channels_list(self) -> None:
        self.channels_list.clear()
        for channel in self.settings.get_channels():
            item = QtWidgets.QListWidgetItem(channel.get("name", "Канал"))
            item.setIcon(self.style().standardIcon(
                QtWidgets.QStyle.SP_DriveNetIcon
            ))
            self.channels_list.addItem(item)
            
        if self.channels_list.count():
            self.channels_list.setCurrentRow(0)

    def _load_general_settings(self) -> None:
        reconnect = self.settings.get_reconnect()
        signal_loss = reconnect.get("signal_loss", {})
        periodic = reconnect.get("periodic", {})
        
        self.db_dir_input.setText(self.settings.get_db_dir())
        self.screenshot_dir_input.setText(self.settings.get_screenshot_dir())

        self.reconnect_on_loss_checkbox.setChecked(
            bool(signal_loss.get("enabled", True))
        )
        self.frame_timeout_input.setValue(
            int(signal_loss.get("frame_timeout_seconds", 5))
        )
        self.retry_interval_input.setValue(
            int(signal_loss.get("retry_interval_seconds", 5))
        )

        self.periodic_reconnect_checkbox.setChecked(
            bool(periodic.get("enabled", False))
        )
        self.periodic_interval_input.setValue(
            int(periodic.get("interval_minutes", 60))
        )

    def _choose_screenshot_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Выбор папки для скриншотов"
        )
        if directory:
            self.screenshot_dir_input.setText(directory)

    def _choose_db_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Выбор папки базы данных"
        )
        if directory:
            self.db_dir_input.setText(directory)

    def _save_general_settings(self) -> None:
        reconnect = {
            "signal_loss": {
                "enabled": self.reconnect_on_loss_checkbox.isChecked(),
                "frame_timeout_seconds": int(self.frame_timeout_input.value()),
                "retry_interval_seconds": int(self.retry_interval_input.value()),
            },
            "periodic": {
                "enabled": self.periodic_reconnect_checkbox.isChecked(),
                "interval_minutes": int(self.periodic_interval_input.value()),
            },
        }
        
        self.settings.save_reconnect(reconnect)
        
        db_dir = self.db_dir_input.text().strip() or "data/db"
        os.makedirs(db_dir, exist_ok=True)
        self.settings.save_db_dir(db_dir)
        
        screenshot_dir = self.screenshot_dir_input.text().strip() or "data/screenshots"
        self.settings.save_screenshot_dir(screenshot_dir)
        os.makedirs(screenshot_dir, exist_ok=True)
        
        self.db = EventDatabase(self.settings.get_db_path())
        self._refresh_events_table()
        self._start_channels()
        
        QtWidgets.QMessageBox.information(
            self, "Сохранение", "Настройки успешно сохранены!"
        )

    def _load_channel_form(self, index: int) -> None:
        channels = self.settings.get_channels()
        if 0 <= index < len(channels):
            channel = channels[index]
            
            self.channel_name_input.setText(channel.get("name", ""))
            self.channel_source_input.setText(channel.get("source", ""))
            
            self.best_shots_input.setValue(int(channel.get(
                "best_shots", self.settings.get_best_shots()
            )))
            
            self.cooldown_input.setValue(int(channel.get(
                "cooldown_seconds", self.settings.get_cooldown_seconds()
            )))
            
            self.min_conf_input.setValue(float(channel.get(
                "ocr_min_confidence", self.settings.get_min_confidence()
            )))
            
            self.detection_mode_input.setCurrentIndex(max(
                0, self.detection_mode_input.findData(
                    channel.get("detection_mode", "continuous")
                )
            ))
            
            self.detector_stride_input.setValue(int(channel.get(
                "detector_frame_stride", 2
            )))
            
            self.motion_threshold_input.setValue(float(channel.get(
                "motion_threshold", 0.01
            )))
            
            self.motion_stride_input.setValue(int(channel.get(
                "motion_frame_stride", 1
            )))
            
            self.motion_activation_frames_input.setValue(int(channel.get(
                "motion_activation_frames", 3
            )))
            
            self.motion_release_frames_input.setValue(int(channel.get(
                "motion_release_frames", 6
            )))

            region = channel.get("region") or {
                "x": 0, "y": 0, "width": 100, "height": 100
            }
            
            self.roi_x_input.setValue(int(region.get("x", 0)))
            self.roi_y_input.setValue(int(region.get("y", 0)))
            self.roi_w_input.setValue(int(region.get("width", 100)))
            self.roi_h_input.setValue(int(region.get("height", 100)))
            
            self.preview.set_roi({
                "x": int(region.get("x", 0)),
                "y": int(region.get("y", 0)),
                "width": int(region.get("width", 100)),
                "height": int(region.get("height", 100)),
            })
            
            self._refresh_preview_frame()

    def _add_channel(self) -> None:
        channels = self.settings.get_channels()
        new_id = max([c.get("id", 0) for c in channels] + [0]) + 1
        
        channels.append({
            "id": new_id,
            "name": f"Канал {new_id}",
            "source": "",
            "best_shots": self.settings.get_best_shots(),
            "cooldown_seconds": self.settings.get_cooldown_seconds(),
            "ocr_min_confidence": self.settings.get_min_confidence(),
            "region": {"x": 0, "y": 0, "width": 100, "height": 100},
            "detection_mode": "continuous",
            "detector_frame_stride": 2,
            "motion_threshold": 0.01,
            "motion_frame_stride": 1,
            "motion_activation_frames": 3,
            "motion_release_frames": 6,
        })
        
        self.settings.save_channels(channels)
        self._reload_channels_list()
        self._draw_grid()
        self._start_channels()
        
        # Выбираем новый канал
        self.channels_list.setCurrentRow(len(channels) - 1)

    def _remove_channel(self) -> None:
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if 0 <= index < len(channels):
            reply = QtWidgets.QMessageBox.question(
                self, "Удаление канала",
                f"Вы уверены, что хотите удалить канал '{channels[index]['name']}'?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                channels.pop(index)
                self.settings.save_channels(channels)
                self._reload_channels_list()
                self._draw_grid()
                self._start_channels()

    def _save_channel(self) -> None:
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if 0 <= index < len(channels):
            channels[index]["name"] = self.channel_name_input.text()
            channels[index]["source"] = self.channel_source_input.text()
            channels[index]["best_shots"] = int(self.best_shots_input.value())
            channels[index]["cooldown_seconds"] = int(self.cooldown_input.value())
            channels[index]["ocr_min_confidence"] = float(self.min_conf_input.value())
            channels[index]["detection_mode"] = self.detection_mode_input.currentData()
            channels[index]["detector_frame_stride"] = int(self.detector_stride_input.value())
            channels[index]["motion_threshold"] = float(self.motion_threshold_input.value())
            channels[index]["motion_frame_stride"] = int(self.motion_stride_input.value())
            channels[index]["motion_activation_frames"] = int(self.motion_activation_frames_input.value())
            channels[index]["motion_release_frames"] = int(self.motion_release_frames_input.value())

            region = {
                "x": int(self.roi_x_input.value()),
                "y": int(self.roi_y_input.value()),
                "width": int(self.roi_w_input.value()),
                "height": int(self.roi_h_input.value()),
            }
            
            region["width"] = min(region["width"], max(1, 100 - region["x"]))
            region["height"] = min(region["height"], max(1, 100 - region["y"]))
            channels[index]["region"] = region
            
            self.settings.save_channels(channels)
            self._reload_channels_list()
            self._draw_grid()
            self._start_channels()
            
            QtWidgets.QMessageBox.information(
                self, "Сохранение", "Настройки канала успешно сохранены!"
            )

    def _on_roi_drawn(self, roi: Dict[str, int]) -> None:
        self.roi_x_input.blockSignals(True)
        self.roi_y_input.blockSignals(True)
        self.roi_w_input.blockSignals(True)
        self.roi_h_input.blockSignals(True)
        
        self.roi_x_input.setValue(roi["x"])
        self.roi_y_input.setValue(roi["y"])
        self.roi_w_input.setValue(roi["width"])
        self.roi_h_input.setValue(roi["height"])
        
        self.roi_x_input.blockSignals(False)
        self.roi_y_input.blockSignals(False)
        self.roi_w_input.blockSignals(False)
        self.roi_h_input.blockSignals(False)

    def _on_roi_inputs_changed(self) -> None:
        roi = {
            "x": int(self.roi_x_input.value()),
            "y": int(self.roi_y_input.value()),
            "width": int(self.roi_w_input.value()),
            "height": int(self.roi_h_input.value()),
        }
        
        roi["width"] = min(roi["width"], max(1, 100 - roi["x"]))
        roi["height"] = min(roi["height"], max(1, 100 - roi["y"]))
        
        self.preview.set_roi(roi)

    def _refresh_preview_frame(self) -> None:
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if not (0 <= index < len(channels)):
            return
            
        source = str(channels[index].get("source", ""))
        if not source:
            self.preview.setPixmap(None)
            return
            
        try:
            capture = cv2.VideoCapture(
                int(source) if source.isnumeric() else source
            )
            ret, frame = capture.read()
            capture.release()
            
            if not ret or frame is None:
                self.preview.setPixmap(None)
                return
                
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb_frame.shape
            bytes_per_line = 3 * width
            
            q_image = QtGui.QImage(
                rgb_frame.data, width, height, bytes_per_line,
                QtGui.QImage.Format_RGB888
            ).copy()
            
            self.preview.setPixmap(QtGui.QPixmap.fromImage(q_image))
            
        except Exception as e:
            logger.error(f"Ошибка загрузки предпросмотра: {e}")
            self.preview.setPixmap(None)

    # ------------------ Жизненный цикл ------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Обработчик закрытия окна."""
        reply = QtWidgets.QMessageBox.question(
            self, "Выход",
            "Вы уверены, что хотите выйти? Все каналы будут остановлены.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self._stop_workers()
            self.geometry_timer.stop()
            event.accept()
        else:
            event.ignore()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Обработчик показа окна."""
        super().showEvent(event)
        
        # Убедимся, что окно находится в безопасной зоне
        self._ensure_window_safety()
        
        # Установим фокус на первую вкладку
        self.tabs.setCurrentIndex(0)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        """Обработчик изменения состояния окна."""
        super().changeEvent(event)
        
        if event.type() == QtCore.QEvent.WindowStateChange:
            # Предотвращаем полноэкранный режим
            if self.windowState() & QtCore.Qt.WindowFullScreen:
                self.showNormal()


# Точка входа для тестирования
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ANPR Desktop")
    app.setOrganizationName("ANPR Systems")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())
