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
            background-color: #1a1a1a;
            color: #ccc;
            border: 2px solid #333;
            border-radius: 4px;
            padding: 4px;
            font-weight: 500;
        """)
        self.video_label.setMinimumSize(220, 150)
        self.video_label.setScaledContents(False)
        self.video_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, 
            QtWidgets.QSizePolicy.Expanding
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_label)

        # Индикатор движения
        self.motion_indicator = QtWidgets.QLabel("⚡ Движение")
        self.motion_indicator.setParent(self.video_label)
        self.motion_indicator.setStyleSheet("""
            background-color: rgba(220, 53, 69, 0.9);
            color: white;
            padding: 4px 8px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 11px;
        """)
        self.motion_indicator.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.motion_indicator.hide()

        # Последний распознанный номер
        self.last_plate = QtWidgets.QLabel("—")
        self.last_plate.setParent(self.video_label)
        self.last_plate.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.7);
            color: #4dfefe;
            padding: 4px 8px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 12px;
        """)
        self.last_plate.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.last_plate.hide()

        # Статус
        self.status_hint = QtWidgets.QLabel("")
        self.status_hint.setParent(self.video_label)
        self.status_hint.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.85);
            color: #ddd;
            padding: 3px 6px;
            border-radius: 4px;
            font-size: 10px;
        """)
        self.status_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.status_hint.hide()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        rect = self.video_label.contentsRect()
        margin = 8
        
        # Позиционирование индикатора движения
        indicator_size = self.motion_indicator.sizeHint()
        self.motion_indicator.move(
            rect.right() - indicator_size.width() - margin,
            rect.top() + margin
        )
        
        # Позиционирование номера
        self.last_plate.move(rect.left() + margin, rect.top() + margin)
        
        # Позиционирование статуса
        status_size = self.status_hint.sizeHint()
        self.status_hint.move(
            rect.left() + margin,
            rect.bottom() - status_size.height() - margin
        )

    def set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        if pixmap.isNull():
            self.video_label.setText("Нет сигнала")
            self.video_label.setPixmap(QtGui.QPixmap())
        else:
            self.video_label.setText("")
            self.video_label.setPixmap(pixmap)

    def set_motion_active(self, active: bool) -> None:
        self.motion_indicator.setVisible(active)

    def set_last_plate(self, plate: str) -> None:
        has_plate = bool(plate and plate.strip())
        self.last_plate.setVisible(has_plate)
        if has_plate:
            self.last_plate.setText(f"🚗 {plate}")
        else:
            self.last_plate.setText("—")
        self.last_plate.adjustSize()

    def set_status(self, text: str) -> None:
        has_text = bool(text and text.strip())
        self.status_hint.setVisible(has_text)
        if has_text:
            self.status_hint.setText(f"📶 {text}")
            self.status_hint.adjustSize()


class ROIEditor(QtWidgets.QLabel):
    """Виджет предпросмотра канала с настраиваемой областью распознавания."""

    roi_changed = QtCore.pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__("Нет кадра")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(380, 220)
        self.setMaximumHeight(300)
        self.setStyleSheet("""
            background-color: #1a1a1a;
            color: #888;
            border: 2px solid #333;
            border-radius: 4px;
            padding: 8px;
        """)
        self._roi = {"x": 0, "y": 0, "width": 100, "height": 100}
        self._pixmap: Optional[QtGui.QPixmap] = None
        self._rubber_band = QtWidgets.QRubberBand(
            QtWidgets.QRubberBand.Rectangle, self
        )
        self._rubber_band.setStyleSheet("border: 2px dashed #00ffff;")
        self._origin: Optional[QtCore.QPoint] = None

    def set_roi(self, roi: Dict[str, int]) -> None:
        self._roi = {
            "x": max(0, min(100, int(roi.get("x", 0)))),
            "y": max(0, min(100, int(roi.get("y", 0)))),
            "width": max(1, min(100 - self._roi["x"], int(roi.get("width", 100)))),
            "height": max(1, min(100 - self._roi["y"], int(roi.get("height", 100)))),
        }
        self.update()

    def setPixmap(self, pixmap: Optional[QtGui.QPixmap]) -> None:
        self._pixmap = pixmap
        if pixmap is None or pixmap.isNull():
            super().setPixmap(QtGui.QPixmap())
            self.setText("Нет кадра")
        else:
            self.setText("")
            scaled = self._scaled_pixmap(self.size())
            super().setPixmap(scaled)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._pixmap and not self._pixmap.isNull():
            super().setPixmap(self._scaled_pixmap(event.size()))

    def _scaled_pixmap(self, size: QtCore.QSize) -> QtGui.QPixmap:
        if not self._pixmap:
            return QtGui.QPixmap()
        return self._pixmap.scaled(
            size - QtCore.QSize(16, 16),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )

    def _image_geometry(self) -> Optional[Tuple[QtCore.QPoint, QtCore.QSize]]:
        if not self._pixmap or self._pixmap.isNull():
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
        
        # Рисуем ROI
        roi_rect = QtCore.QRect(
            offset.x() + int(size.width() * self._roi["x"] / 100),
            offset.y() + int(size.height() * self._roi["y"] / 100),
            int(size.width() * self._roi["width"] / 100),
            int(size.height() * self._roi["height"] / 100),
        )
        
        # Полупрозрачная заливка
        painter.setBrush(QtGui.QColor(0, 200, 0, 40))
        
        # Зеленый контур
        pen = QtGui.QPen(QtGui.QColor(0, 200, 0), 2)
        painter.setPen(pen)
        painter.drawRect(roi_rect)
        
        # Угловые маркеры
        marker_size = 8
        corners = [
            roi_rect.topLeft(),
            roi_rect.topRight(),
            roi_rect.bottomLeft(),
            roi_rect.bottomRight(),
        ]
        painter.setBrush(QtGui.QColor(0, 200, 0))
        painter.setPen(QtCore.Qt.NoPen)
        for corner in corners:
            painter.drawEllipse(corner, marker_size, marker_size)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            return
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
        if self._origin is None or event.button() != QtCore.Qt.LeftButton:
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
        
        if selection.isValid() and selection.width() > 10 and selection.height() > 10:
            x_pct = max(0, min(100, 
                int((selection.left() - offset.x()) * 100 / size.width())))
            y_pct = max(0, min(100,
                int((selection.top() - offset.y()) * 100 / size.height())))
            w_pct = max(1, min(100 - x_pct,
                int(selection.width() * 100 / size.width())))
            h_pct = max(1, min(100 - y_pct,
                int(selection.height() * 100 / size.height())))
            
            self._roi = {
                "x": x_pct, 
                "y": y_pct, 
                "width": w_pct, 
                "height": h_pct
            }
            self.roi_changed.emit(self._roi)
        
        self._origin = None
        self.update()


class EventDetailView(QtWidgets.QWidget):
    """Отображение выбранного события: метаданные, кадр и область номера."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(320)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # Кадр распознавания
        self.frame_preview = self._build_preview(
            "📷 Кадр распознавания", 
            min_height=240,
            keep_aspect=True
        )
        layout.addWidget(self.frame_preview, stretch=3)

        # Нижняя строка: номер + метаданные
        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(12)
        
        self.plate_preview = self._build_preview(
            "🚗 Область номера",
            min_size=QtCore.QSize(240, 140),
            keep_aspect=True
        )
        bottom_row.addWidget(self.plate_preview, 1)

        # Метаданные
        meta_group = QtWidgets.QGroupBox("📊 Данные распознавания")
        meta_group.setStyleSheet("""
            QGroupBox {
                background-color: #1a1a1a;
                color: white;
                border: 2px solid #333;
                border-radius: 6px;
                padding: 12px;
                font-weight: 500;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 6px;
                color: #4dfefe;
            }
            QLabel { 
                color: #e0e0e0; 
                padding: 2px 0;
            }
        """)
        meta_group.setMinimumWidth(240)
        meta_layout = QtWidgets.QFormLayout(meta_group)
        meta_layout.setVerticalSpacing(8)
        
        self.time_label = QtWidgets.QLabel("—")
        self.channel_label = QtWidgets.QLabel("—")
        self.plate_label = QtWidgets.QLabel("—")
        self.conf_label = QtWidgets.QLabel("—")
        
        meta_layout.addRow("📅 Дата:", self.time_label)
        meta_layout.addRow("📺 Канал:", self.channel_label)
        meta_layout.addRow("🚗 Гос. номер:", self.plate_label)
        meta_layout.addRow("🎯 Уверенность:", self.conf_label)
        
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
        group.setStyleSheet("""
            QGroupBox {
                background-color: #1a1a1a;
                color: white;
                border: 2px solid #333;
                border-radius: 6px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 6px;
                color: #4dfefe;
            }
        """)
        wrapper = QtWidgets.QVBoxLayout(group)
        wrapper.setContentsMargins(2, 2, 2, 2)
        
        label = QtWidgets.QLabel("Нет изображения")
        label.setAlignment(QtCore.Qt.AlignCenter)
        
        if min_size:
            label.setMinimumSize(min_size)
        else:
            label.setMinimumHeight(min_height)
            
        label.setStyleSheet("""
            background-color: #111;
            color: #888;
            border: 1px solid #444;
            border-radius: 4px;
        """)
        label.setScaledContents(False)
        wrapper.addWidget(label)
        
        # Динамическое свойство для доступа к label
        group.setProperty("display_label", label)
        return group

    def clear(self) -> None:
        self.time_label.setText("—")
        self.channel_label.setText("—")
        self.plate_label.setText("—")
        self.conf_label.setText("—")
        
        for group in (self.frame_preview, self.plate_preview):
            label = group.property("display_label")
            if label:
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

        # Обновляем метаданные
        self.time_label.setText(event.get("timestamp", "—"))
        self.channel_label.setText(event.get("channel", "—"))
        
        plate = event.get("plate") or "—"
        self.plate_label.setText(plate)
        
        conf = event.get("confidence")
        if conf is not None:
            self.conf_label.setText(f"{float(conf):.2%}")
        else:
            self.conf_label.setText("—")

        # Обновляем изображения
        self._set_image(self.frame_preview, frame_image, keep_aspect=True)
        self._set_image(self.plate_preview, plate_image, keep_aspect=True)

    def _set_image(
        self,
        group: QtWidgets.QGroupBox,
        image: Optional[QtGui.QImage],
        keep_aspect: bool = False,
    ) -> None:
        label = group.property("display_label")
        if not label:
            return
            
        if image is None or image.isNull():
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
    
    # Стили
    APP_STYLE = """
        QMainWindow {
            background-color: #1e1e1e;
        }
        QTabWidget::pane {
            border: 2px solid #333;
            border-radius: 6px;
            background-color: #252525;
            padding: 4px;
        }
        QTabBar::tab {
            background: #2a2a2a;
            color: #aaa;
            padding: 10px 20px;
            margin-right: 4px;
            border: 1px solid #333;
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            font-weight: 500;
        }
        QTabBar::tab:selected {
            background: #252525;
            color: #00ffff;
            border-bottom: 2px solid #00ffff;
        }
        QTabBar::tab:hover {
            background: #303030;
        }
    """
    
    GROUP_BOX_STYLE = """
        QGroupBox {
            background-color: #252525;
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
            color: #4dfefe;
        }
        QLabel {
            color: #e0e0e0;
        }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {
            background-color: #1a1a1a;
            color: #f0f0f0;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 6px;
            selection-background-color: #00ffff;
        }
        QPushButton {
            background-color: #00bcd4;
            color: #000;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            min-height: 24px;
        }
        QPushButton:hover {
            background-color: #4dfefe;
            color: #000;
        }
        QPushButton:pressed {
            background-color: #00a0b0;
        }
        QCheckBox {
            color: #e0e0e0;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #555;
            border-radius: 4px;
        }
        QCheckBox::indicator:checked {
            background-color: #00ffff;
            border-color: #00ffff;
        }
    """
    
    TABLE_STYLE = """
        QTableWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
            border: 1px solid #333;
            border-radius: 4px;
            gridline-color: #333;
            alternate-background-color: #222;
        }
        QHeaderView::section {
            background-color: #252525;
            color: #00ffff;
            padding: 8px;
            border: none;
            font-weight: 600;
        }
        QTableWidget::item {
            padding: 6px;
            border-bottom: 1px solid #333;
        }
        QTableWidget::item:selected {
            background-color: #00ffff;
            color: #000;
        }
        QScrollBar:vertical {
            background-color: #252525;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background-color: #444;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #555;
        }
    """
    
    LIST_STYLE = """
        QListWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
            border: 1px solid #333;
            border-radius: 6px;
            padding: 4px;
        }
        QListWidget::item {
            padding: 8px;
            border-bottom: 1px solid #333;
            border-radius: 4px;
        }
        QListWidget::item:selected {
            background-color: #00ffff;
            color: #000;
        }
        QListWidget::item:hover {
            background-color: #333;
        }
    """

    def __init__(self, settings: Optional[SettingsManager] = None) -> None:
        super().__init__()
        self.setWindowTitle("🚗 ANPR Desktop")
        self.setWindowIcon(self._create_app_icon())
        
        # Оптимальный размер с соотношением 16:9
        self.resize(1280, 720)
        
        # Центрирование окна
        self._center_window()
        
        self.settings = settings or SettingsManager()
        self.db = EventDatabase(self.settings.get_db_path())

        self.channel_workers: List[ChannelWorker] = []
        self.channel_labels: Dict[str, ChannelView] = {}
        self.event_images: Dict[int, Tuple[Optional[QtGui.QImage], Optional[QtGui.QImage]]] = {}
        self.event_cache: Dict[int, Dict] = {}

        self._setup_ui()
        self._start_system_monitoring()
        self._refresh_events_table()
        self._start_channels()

    def _create_app_icon(self) -> QtGui.QIcon:
        """Создает иконку приложения."""
        pixmap = QtGui.QPixmap(64, 64)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        # Фон
        painter.setBrush(QtGui.QColor(0, 188, 212))
        painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
        
        # Машина
        painter.setPen(QtGui.QPen(QtCore.Qt.black, 2))
        painter.setBrush(QtCore.Qt.white)
        painter.drawEllipse(18, 35, 8, 8)
        painter.drawEllipse(38, 35, 8, 8)
        
        # Кузов
        painter.drawRoundedRect(15, 20, 34, 15, 4, 4)
        
        painter.end()
        return QtGui.QIcon(pixmap)

    def _center_window(self) -> None:
        """Центрирует окно на экране."""
        frame_geometry = self.frameGeometry()
        screen_center = QtWidgets.QDesktopWidget().availableGeometry().center()
        frame_geometry.moveCenter(screen_center)
        self.move(frame_geometry.topLeft())

    def _setup_ui(self) -> None:
        """Настраивает основной интерфейс."""
        self.setStyleSheet(self.APP_STYLE)
        
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QtWidgets.QTabWidget.North)
        
        # Создаем вкладки
        self.observation_tab = self._build_observation_tab()
        self.search_tab = self._build_search_tab()
        self.settings_tab = self._build_settings_tab()
        
        self.tabs.addTab(self.observation_tab, "👁️ Наблюдение")
        self.tabs.addTab(self.search_tab, "🔍 Поиск")
        self.tabs.addTab(self.settings_tab, "⚙️ Настройки")
        
        self.setCentralWidget(self.tabs)
        self._build_status_bar()

    def _build_status_bar(self) -> None:
        """Создает строку состояния."""
        status = self.statusBar()
        status.setStyleSheet("""
            QStatusBar {
                background-color: #252525;
                color: white;
                border-top: 1px solid #333;
                padding: 6px;
            }
        """)
        status.setSizeGripEnabled(False)
        
        # Виджеты статуса
        self.status_label = QtWidgets.QLabel("Готово")
        status.addWidget(self.status_label)
        
        # Статистика системы
        status.addPermanentWidget(QtWidgets.QLabel("|"))
        self.cpu_label = QtWidgets.QLabel("⚙️ CPU: —%")
        self.ram_label = QtWidgets.QLabel("💾 RAM: —%")
        self.fps_label = QtWidgets.QLabel("🎬 FPS: —")
        
        status.addPermanentWidget(self.cpu_label)
        status.addPermanentWidget(self.ram_label)
        status.addPermanentWidget(self.fps_label)

    def _start_system_monitoring(self) -> None:
        """Запускает мониторинг системы."""
        self.stats_timer = QtCore.QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._update_system_stats)
        self.stats_timer.start()
        self._update_system_stats()
        
        # Счетчик FPS
        self.frame_count = 0
        self.fps_timer = QtCore.QTimer(self)
        self.fps_timer.setInterval(1000)
        self.fps_timer.timeout.connect(self._update_fps)
        self.fps_timer.start()

    def _update_system_stats(self) -> None:
        """Обновляет статистику системы."""
        cpu_percent = psutil.cpu_percent(interval=None)
        ram_percent = psutil.virtual_memory().percent
        self.cpu_label.setText(f"⚙️ CPU: {cpu_percent:.0f}%")
        self.ram_label.setText(f"💾 RAM: {ram_percent:.0f}%")

    def _update_fps(self) -> None:
        """Обновляет счетчик FPS."""
        self.fps_label.setText(f"🎬 FPS: {self.frame_count}")
        self.frame_count = 0

    # ------------------ Наблюдение ------------------
    def _build_observation_tab(self) -> QtWidgets.QWidget:
        """Создает вкладку наблюдения."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # Левая колонка - сетка камер
        left_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(12)
        
        # Панель управления сеткой
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("📐 Сетка:"))
        self.grid_selector = QtWidgets.QComboBox()
        self.grid_selector.addItems(self.GRID_VARIANTS)
        self.grid_selector.setCurrentText(self.settings.get_grid())
        self.grid_selector.currentTextChanged.connect(self._on_grid_changed)
        self.grid_selector.setFixedWidth(100)
        controls.addWidget(self.grid_selector)
        controls.addStretch()
        
        # Кнопка обновления
        refresh_btn = QtWidgets.QPushButton("🔄 Обновить")
        refresh_btn.clicked.connect(self._refresh_channels)
        refresh_btn.setFixedWidth(120)
        controls.addWidget(refresh_btn)
        
        left_column.addLayout(controls)

        # Сетка камер
        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        
        left_column.addWidget(self.grid_widget, stretch=4)
        layout.addLayout(left_column, stretch=3)

        # Правая колонка - события и детали
        right_column = QtWidgets.QVBoxLayout()
        right_column.setSpacing(12)
        
        # Детали события
        details_group = QtWidgets.QGroupBox("📋 Детали события")
        details_group.setStyleSheet(self.GROUP_BOX_STYLE)
        details_layout = QtWidgets.QVBoxLayout(details_group)
        self.event_detail = EventDetailView()
        details_layout.addWidget(self.event_detail)
        right_column.addWidget(details_group, stretch=2)

        # Таблица событий
        events_group = QtWidgets.QGroupBox("📈 Последние события")
        events_group.setStyleSheet(self.GROUP_BOX_STYLE)
        events_layout = QtWidgets.QVBoxLayout(events_group)
        
        self.events_table = QtWidgets.QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(
            ["Время", "Гос. номер", "Канал", "Уверенность"]
        )
        self.events_table.setStyleSheet(self.TABLE_STYLE)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self.events_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.events_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setAlternatingRowColors(True)
        self.events_table.setColumnWidth(0, 140)
        self.events_table.setColumnWidth(1, 120)
        self.events_table.setColumnWidth(2, 100)
        self.events_table.setColumnWidth(3, 90)
        
        self.events_table.itemSelectionChanged.connect(
            self._on_event_selected
        )
        
        events_layout.addWidget(self.events_table)
        right_column.addWidget(events_group, stretch=1)

        layout.addLayout(right_column, stretch=2)
        
        self._draw_grid()
        return widget

    def _refresh_channels(self) -> None:
        """Обновляет все каналы."""
        self._start_channels()
        self.status_label.setText("Каналы обновлены")

    @staticmethod
    def _prepare_optional_datetime(widget: QtWidgets.QDateTimeEdit) -> None:
        """Настраивает QDateTimeEdit для необязательной даты."""
        widget.setCalendarPopup(True)
        widget.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        min_dt = QtCore.QDateTime.fromSecsSinceEpoch(0)
        widget.setMinimumDateTime(min_dt)
        widget.setSpecialValueText("Не выбрано")
        widget.setDateTime(min_dt)

    @staticmethod
    def _get_datetime_value(widget: QtWidgets.QDateTimeEdit) -> Optional[str]:
        """Получает значение даты из QDateTimeEdit."""
        if widget.dateTime() == widget.minimumDateTime():
            return None
        return widget.dateTime().toString(QtCore.Qt.ISODate)

    def _draw_grid(self) -> None:
        """Рисует сетку каналов."""
        # Очищаем старую сетку
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
                if index < len(channels):
                    channel_name = channels[index].get("name", f"Канал {index+1}")
                else:
                    channel_name = f"Пустой {index+1}"
                
                label = ChannelView(channel_name)
                if index < len(channels):
                    self.channel_labels[channel_name] = label
                
                self.grid_layout.addWidget(label, row, col)
                index += 1

    def _on_grid_changed(self, grid: str) -> None:
        """Обработчик изменения сетки."""
        self.settings.save_grid(grid)
        self._draw_grid()
        self.status_label.setText(f"Сетка изменена на {grid}")

    def _start_channels(self) -> None:
        """Запускает рабочие потоки для каналов."""
        self._stop_workers()
        self.channel_workers = []
        reconnect_conf = self.settings.get_reconnect()
        
        for channel_conf in self.settings.get_channels():
            source = str(channel_conf.get("source", "")).strip()
            channel_name = channel_conf.get("name", "Канал")
            
            if not source:
                label = self.channel_labels.get(channel_name)
                if label:
                    label.set_status("Нет источника")
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
        """Останавливает все рабочие потоки."""
        for worker in self.channel_workers:
            worker.stop()
            worker.wait(2000)
        self.channel_workers = []

    def _update_frame(self, channel_name: str, image: QtGui.QImage) -> None:
        """Обновляет кадр в канале."""
        self.frame_count += 1
        label = self.channel_labels.get(channel_name)
        if not label:
            return
            
        if image.isNull():
            label.set_pixmap(QtGui.QPixmap())
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
        """Загружает изображение из файла."""
        if not path or not os.path.exists(path):
            return None
            
        try:
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if image is None:
                return None
                
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb.shape
            bytes_per_line = 3 * width
            
            return QtGui.QImage(
                rgb.data, width, height,
                bytes_per_line, QtGui.QImage.Format_RGB888
            ).copy()
        except Exception as e:
            logger.error(f"Ошибка загрузки изображения {path}: {e}")
            return None

    def _handle_event(self, event: Dict) -> None:
        """Обрабатывает новое событие."""
        event_id = int(event.get("id", 0))
        frame_image = event.get("frame_image")
        plate_image = event.get("plate_image")
        
        if event_id:
            self.event_images[event_id] = (frame_image, plate_image)
            self.event_cache[event_id] = event
            
        # Обновляем последний номер в канале
        channel_label = self.channel_labels.get(event.get("channel", ""))
        if channel_label:
            channel_label.set_last_plate(event.get("plate", ""))
            
        self._refresh_events_table(select_id=event_id)
        self._show_event_details(event_id)

    def _handle_status(self, channel: str, status: str) -> None:
        """Обновляет статус канала."""
        label = self.channel_labels.get(channel)
        if label:
            normalized = status.lower()
            if "движ" in normalized or "motion" in normalized:
                label.set_motion_active(True)
                label.set_status("")
            elif "переподключ" in normalized or "reconnect" in normalized:
                label.set_status("Переподключение...")
                label.set_motion_active(False)
            else:
                label.set_status(status)
                label.set_motion_active(False)

    def _on_event_selected(self) -> None:
        """Обработчик выбора события в таблице."""
        selected = self.events_table.selectedItems()
        if not selected:
            return
            
        event_id_item = selected[0]
        event_id = int(event_id_item.data(QtCore.Qt.UserRole) or 0)
        self._show_event_details(event_id)

    def _show_event_details(self, event_id: int) -> None:
        """Показывает детали события."""
        event = self.event_cache.get(event_id)
        images = self.event_images.get(event_id, (None, None))
        frame_image, plate_image = images
        
        if event:
            # Загружаем изображения из файлов если они не были загружены
            if frame_image is None and event.get("frame_path"):
                frame_image = self._load_image_from_path(event.get("frame_path"))
            if plate_image is None and event.get("plate_path"):
                plate_image = self._load_image_from_path(event.get("plate_path"))
            self.event_images[event_id] = (frame_image, plate_image)
            
        self.event_detail.set_event(event, frame_image, plate_image)

    def _refresh_events_table(self, select_id: Optional[int] = None) -> None:
        """Обновляет таблицу событий."""
        rows = self.db.fetch_recent(limit=100)
        self.events_table.setRowCount(0)
        self.event_cache = {row["id"]: dict(row) for row in rows}
        
        for row_data in rows:
            row_index = self.events_table.rowCount()
            self.events_table.insertRow(row_index)
            
            # Время
            time_item = QtWidgets.QTableWidgetItem(row_data["timestamp"])
            time_item.setData(QtCore.Qt.UserRole, int(row_data["id"]))
            self.events_table.setItem(row_index, 0, time_item)
            
            # Номер
            plate_item = QtWidgets.QTableWidgetItem(row_data["plate"])
            self.events_table.setItem(row_index, 1, plate_item)
            
            # Канал
            channel_item = QtWidgets.QTableWidgetItem(row_data["channel"])
            self.events_table.setItem(row_index, 2, channel_item)
            
            # Уверенность
            conf = row_data.get("confidence")
            conf_text = f"{float(conf):.2%}" if conf is not None else "—"
            conf_item = QtWidgets.QTableWidgetItem(conf_text)
            self.events_table.setItem(row_index, 3, conf_item)
            
            # Цветовое кодирование уверенности
            if conf is not None:
                if conf > 0.9:
                    conf_item.setForeground(QtGui.QColor("#00ff00"))
                elif conf > 0.7:
                    conf_item.setForeground(QtGui.QColor("#ffff00"))
                else:
                    conf_item.setForeground(QtGui.QColor("#ff6666"))

        # Выделяем выбранную строку
        if select_id:
            for row in range(self.events_table.rowCount()):
                item = self.events_table.item(row, 0)
                if item and int(item.data(QtCore.Qt.UserRole) or 0) == select_id:
                    self.events_table.selectRow(row)
                    self.events_table.scrollToItem(item)
                    break

    # ------------------ Поиск ------------------
    def _build_search_tab(self) -> QtWidgets.QWidget:
        """Создает вкладку поиска."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        widget.setStyleSheet(self.GROUP_BOX_STYLE)

        # Фильтры
        filters_group = QtWidgets.QGroupBox("🔍 Фильтры поиска")
        filters_group.setStyleSheet(self.GROUP_BOX_STYLE)
        form = QtWidgets.QFormLayout(filters_group)
        form.setVerticalSpacing(10)
        
        self.search_plate = QtWidgets.QLineEdit()
        self.search_plate.setPlaceholderText("Например: А123ВС777")
        
        self.search_from = QtWidgets.QDateTimeEdit()
        self._prepare_optional_datetime(self.search_from)
        
        self.search_to = QtWidgets.QDateTimeEdit()
        self._prepare_optional_datetime(self.search_to)
        
        form.addRow("🚗 Номер:", self.search_plate)
        form.addRow("📅 Дата с:", self.search_from)
        form.addRow("📅 Дата по:", self.search_to)
        
        layout.addWidget(filters_group)

        # Кнопки
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch()
        
        clear_btn = QtWidgets.QPushButton("🗑️ Очистить")
        clear_btn.clicked.connect(self._clear_search)
        clear_btn.setFixedWidth(120)
        button_row.addWidget(clear_btn)
        
        search_btn = QtWidgets.QPushButton("🔍 Поиск")
        search_btn.clicked.connect(self._run_plate_search)
        search_btn.setFixedWidth(120)
        button_row.addWidget(search_btn)
        
        layout.addLayout(button_row)

        # Таблица результатов
        self.search_table = QtWidgets.QTableWidget(0, 5)
        self.search_table.setHorizontalHeaderLabels(
            ["Время", "Канал", "Номер", "Уверенность", "Источник"]
        )
        self.search_table.setStyleSheet(self.TABLE_STYLE)
        self.search_table.horizontalHeader().setStretchLastSection(True)
        self.search_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self.search_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.search_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.search_table, stretch=1)

        return widget

    def _clear_search(self) -> None:
        """Очищает поля поиска."""
        self.search_plate.clear()
        self.search_from.setDateTime(self.search_from.minimumDateTime())
        self.search_to.setDateTime(self.search_to.minimumDateTime())
        self.search_table.setRowCount(0)

    def _run_plate_search(self) -> None:
        """Выполняет поиск по номеру."""
        start = self._get_datetime_value(self.search_from)
        end = self._get_datetime_value(self.search_to)
        plate_fragment = self.search_plate.text().strip()
        
        if not plate_fragment and not start and not end:
            self.status_label.setText("Укажите критерии поиска")
            return
            
        rows = self.db.search_by_plate(
            plate_fragment, 
            start=start or None, 
            end=end or None
        )
        
        self.search_table.setRowCount(0)
        
        for row_data in rows:
            row_index = self.search_table.rowCount()
            self.search_table.insertRow(row_index)
            
            self.search_table.setItem(
                row_index, 0, 
                QtWidgets.QTableWidgetItem(row_data["timestamp"])
            )
            self.search_table.setItem(
                row_index, 1, 
                QtWidgets.QTableWidgetItem(row_data["channel"])
            )
            self.search_table.setItem(
                row_index, 2, 
                QtWidgets.QTableWidgetItem(row_data["plate"])
            )
            
            conf = row_data.get("confidence")
            conf_text = f"{float(conf):.2%}" if conf is not None else "—"
            self.search_table.setItem(
                row_index, 3, 
                QtWidgets.QTableWidgetItem(conf_text)
            )
            
            self.search_table.setItem(
                row_index, 4, 
                QtWidgets.QTableWidgetItem(row_data["source"])
            )
            
            # Цветовое кодирование
            if conf is not None:
                conf_item = self.search_table.item(row_index, 3)
                if conf > 0.9:
                    conf_item.setForeground(QtGui.QColor("#00ff00"))
                elif conf > 0.7:
                    conf_item.setForeground(QtGui.QColor("#ffff00"))
                else:
                    conf_item.setForeground(QtGui.QColor("#ff6666"))
        
        self.status_label.setText(
            f"Найдено {len(rows)} событий"
        )

    # ------------------ Настройки ------------------
    def _build_settings_tab(self) -> QtWidgets.QWidget:
        """Создает вкладку настроек."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        tabs = QtWidgets.QTabWidget()
        tabs.setTabPosition(QtWidgets.QTabWidget.North)
        tabs.addTab(self._build_general_settings_tab(), "🌐 Общие")
        tabs.addTab(self._build_channel_settings_tab(), "📺 Каналы")
        
        layout.addWidget(tabs)
        return widget

    def _build_general_settings_tab(self) -> QtWidgets.QWidget:
        """Создает вкладку общих настроек."""
        widget = QtWidgets.QScrollArea()
        widget.setWidgetResizable(True)
        widget.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        container.setStyleSheet(self.GROUP_BOX_STYLE)

        # Группа переподключения
        reconnect_group = QtWidgets.QGroupBox("🔄 Автоматическое переподключение")
        reconnect_group.setStyleSheet(self.GROUP_BOX_STYLE)
        reconnect_form = QtWidgets.QFormLayout(reconnect_group)
        reconnect_form.setVerticalSpacing(10)
        
        self.reconnect_on_loss_checkbox = QtWidgets.QCheckBox(
            "Переподключение при потере сигнала"
        )
        reconnect_form.addRow(self.reconnect_on_loss_checkbox)

        self.frame_timeout_input = QtWidgets.QSpinBox()
        self.frame_timeout_input.setRange(1, 300)
        self.frame_timeout_input.setSuffix(" с")
        self.frame_timeout_input.setToolTip(
            "Сколько секунд ждать кадр перед попыткой переподключения"
        )
        reconnect_form.addRow("Таймаут ожидания кадра:", self.frame_timeout_input)

        self.retry_interval_input = QtWidgets.QSpinBox()
        self.retry_interval_input.setRange(1, 300)
        self.retry_interval_input.setSuffix(" с")
        self.retry_interval_input.setToolTip(
            "Интервал между попытками переподключения при потере сигнала"
        )
        reconnect_form.addRow("Интервал между попытками:", self.retry_interval_input)

        self.periodic_reconnect_checkbox = QtWidgets.QCheckBox(
            "Переподключение по таймеру"
        )
        reconnect_form.addRow(self.periodic_reconnect_checkbox)

        self.periodic_interval_input = QtWidgets.QSpinBox()
        self.periodic_interval_input.setRange(1, 1440)
        self.periodic_interval_input.setSuffix(" мин")
        self.periodic_interval_input.setToolTip(
            "Плановое переподключение каждые N минут"
        )
        reconnect_form.addRow("Интервал переподключения:", self.periodic_interval_input)
        
        layout.addWidget(reconnect_group)

        # Группа путей
        paths_group = QtWidgets.QGroupBox("📁 Пути")
        paths_group.setStyleSheet(self.GROUP_BOX_STYLE)
        paths_form = QtWidgets.QFormLayout(paths_group)
        paths_form.setVerticalSpacing(10)
        
        db_row = QtWidgets.QHBoxLayout()
        self.db_dir_input = QtWidgets.QLineEdit()
        browse_db_btn = QtWidgets.QPushButton("📂 Выбрать...")
        browse_db_btn.clicked.connect(self._choose_db_dir)
        db_row.addWidget(self.db_dir_input)
        db_row.addWidget(browse_db_btn)
        db_container = QtWidgets.QWidget()
        db_container.setLayout(db_row)
        paths_form.addRow("Папка базы данных:", db_container)

        screenshot_row = QtWidgets.QHBoxLayout()
        self.screenshot_dir_input = QtWidgets.QLineEdit()
        browse_screenshot_btn = QtWidgets.QPushButton("📂 Выбрать...")
        browse_screenshot_btn.clicked.connect(self._choose_screenshot_dir)
        screenshot_row.addWidget(self.screenshot_dir_input)
        screenshot_row.addWidget(browse_screenshot_btn)
        screenshot_container = QtWidgets.QWidget()
        screenshot_container.setLayout(screenshot_row)
        paths_form.addRow("Папка для скриншотов:", screenshot_container)
        
        layout.addWidget(paths_group)

        # Кнопка сохранения
        save_general_btn = QtWidgets.QPushButton("💾 Сохранить общие настройки")
        save_general_btn.clicked.connect(self._save_general_settings)
        save_general_btn.setFixedHeight(36)
        layout.addWidget(save_general_btn)
        
        layout.addStretch()
        
        self._load_general_settings()
        widget.setWidget(container)
        return widget

    def _build_channel_settings_tab(self) -> QtWidgets.QWidget:
        """Создает вкладку настроек каналов."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)
        
        widget.setStyleSheet(self.GROUP_BOX_STYLE)

        # Левая панель - список каналов
        left_panel = QtWidgets.QVBoxLayout()
        left_panel.setSpacing(10)
        
        channels_label = QtWidgets.QLabel("📺 Каналы")
        channels_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #00ffff;")
        left_panel.addWidget(channels_label)
        
        self.channels_list = QtWidgets.QListWidget()
        self.channels_list.setFixedWidth(200)
        self.channels_list.setStyleSheet(self.LIST_STYLE)
        self.channels_list.currentRowChanged.connect(self._load_channel_form)
        left_panel.addWidget(self.channels_list)

        # Кнопки управления каналами
        list_buttons = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("➕ Добавить")
        add_btn.clicked.connect(self._add_channel)
        remove_btn = QtWidgets.QPushButton("🗑️ Удалить")
        remove_btn.clicked.connect(self._remove_channel)
        
        list_buttons.addWidget(add_btn)
        list_buttons.addWidget(remove_btn)
        left_panel.addLayout(list_buttons)
        
        layout.addLayout(left_panel)

        # Центральная панель - предпросмотр и ROI
        center_panel = QtWidgets.QVBoxLayout()
        
        preview_group = QtWidgets.QGroupBox("👁️ Предпросмотр")
        preview_group.setStyleSheet(self.GROUP_BOX_STYLE)
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        
        self.preview = ROIEditor()
        self.preview.roi_changed.connect(self._on_roi_drawn)
        preview_layout.addWidget(self.preview)
        
        center_panel.addWidget(preview_group)
        layout.addLayout(center_panel, 2)

        # Правая панель - настройки канала
        right_panel = QtWidgets.QVBoxLayout()
        
        # Группа основных настроек канала
        channel_group = QtWidgets.QGroupBox("⚙️ Основные настройки")
        channel_group.setStyleSheet(self.GROUP_BOX_STYLE)
        channel_form = QtWidgets.QFormLayout(channel_group)
        channel_form.setVerticalSpacing(8)
        
        self.channel_name_input = QtWidgets.QLineEdit()
        self.channel_source_input = QtWidgets.QLineEdit()
        self.channel_source_input.setPlaceholderText("rtsp:// или номер камеры")
        
        channel_form.addRow("Название:", self.channel_name_input)
        channel_form.addRow("Источник:", self.channel_source_input)
        right_panel.addWidget(channel_group)

        # Группа распознавания
        recognition_group = QtWidgets.QGroupBox("🔍 Распознавание")
        recognition_group.setStyleSheet(self.GROUP_BOX_STYLE)
        recognition_form = QtWidgets.QFormLayout(recognition_group)
        recognition_form.setVerticalSpacing(8)
        
        self.best_shots_input = QtWidgets.QSpinBox()
        self.best_shots_input.setRange(1, 50)
        self.best_shots_input.setToolTip(
            "Количество бестшотов, участвующих в консенсусе трека"
        )
        recognition_form.addRow("Бестшоты на трек:", self.best_shots_input)

        self.cooldown_input = QtWidgets.QSpinBox()
        self.cooldown_input.setRange(0, 3600)
        self.cooldown_input.setSuffix(" сек")
        self.cooldown_input.setToolTip(
            "Пауза перед повторным распознаванием того же номера"
        )
        recognition_form.addRow("Пауза повтора:", self.cooldown_input)

        self.min_conf_input = QtWidgets.QDoubleSpinBox()
        self.min_conf_input.setRange(0.0, 1.0)
        self.min_conf_input.setSingleStep(0.05)
        self.min_conf_input.setDecimals(2)
        self.min_conf_input.setToolTip(
            "Минимальная уверенность OCR для принятия результата"
        )
        recognition_form.addRow("Мин. уверенность OCR:", self.min_conf_input)
        right_panel.addWidget(recognition_group)

        # Группа движения
        motion_group = QtWidgets.QGroupBox("⚡ Детектор движения")
        motion_group.setStyleSheet(self.GROUP_BOX_STYLE)
        motion_form = QtWidgets.QFormLayout(motion_group)
        motion_form.setVerticalSpacing(8)
        
        self.detection_mode_input = QtWidgets.QComboBox()
        self.detection_mode_input.addItem("Постоянное распознавание", "continuous")
        self.detection_mode_input.addItem("По движению", "motion")
        motion_form.addRow("Режим:", self.detection_mode_input)

        self.detector_stride_input = QtWidgets.QSpinBox()
        self.detector_stride_input.setRange(1, 12)
        self.detector_stride_input.setToolTip(
            "Обрабатывать каждый N-й кадр для снижения нагрузки"
        )
        motion_form.addRow("Шаг обработки:", self.detector_stride_input)

        self.motion_threshold_input = QtWidgets.QDoubleSpinBox()
        self.motion_threshold_input.setRange(0.0, 1.0)
        self.motion_threshold_input.setDecimals(3)
        self.motion_threshold_input.setSingleStep(0.005)
        self.motion_threshold_input.setToolTip(
            "Порог чувствительности по площади изменения"
        )
        motion_form.addRow("Порог движения:", self.motion_threshold_input)

        self.motion_stride_input = QtWidgets.QSpinBox()
        self.motion_stride_input.setRange(1, 30)
        motion_form.addRow("Частота анализа:", self.motion_stride_input)

        self.motion_activation_frames_input = QtWidgets.QSpinBox()
        self.motion_activation_frames_input.setRange(1, 60)
        motion_form.addRow("Мин. кадров с движением:", self.motion_activation_frames_input)

        self.motion_release_frames_input = QtWidgets.QSpinBox()
        self.motion_release_frames_input.setRange(1, 120)
        motion_form.addRow("Мин. кадров без движения:", self.motion_release_frames_input)
        right_panel.addWidget(motion_group)

        # Группа ROI
        roi_group = QtWidgets.QGroupBox("🎯 Зона распознавания")
        roi_group.setStyleSheet(self.GROUP_BOX_STYLE)
        roi_layout = QtWidgets.QGridLayout(roi_group)
        roi_layout.setVerticalSpacing(8)
        roi_layout.setHorizontalSpacing(12)
        
        self.roi_x_input = QtWidgets.QSpinBox()
        self.roi_x_input.setRange(0, 100)
        self.roi_x_input.setSuffix(" %")
        
        self.roi_y_input = QtWidgets.QSpinBox()
        self.roi_y_input.setRange(0, 100)
        self.roi_y_input.setSuffix(" %")
        
        self.roi_w_input = QtWidgets.QSpinBox()
        self.roi_w_input.setRange(1, 100)
        self.roi_w_input.setSuffix(" %")
        
        self.roi_h_input = QtWidgets.QSpinBox()
        self.roi_h_input.setRange(1, 100)
        self.roi_h_input.setSuffix(" %")
        
        for spin in (self.roi_x_input, self.roi_y_input, 
                     self.roi_w_input, self.roi_h_input):
            spin.valueChanged.connect(self._on_roi_inputs_changed)

        roi_layout.addWidget(QtWidgets.QLabel("X:"), 0, 0)
        roi_layout.addWidget(self.roi_x_input, 0, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Y:"), 1, 0)
        roi_layout.addWidget(self.roi_y_input, 1, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Ширина:"), 2, 0)
        roi_layout.addWidget(self.roi_w_input, 2, 1)
        roi_layout.addWidget(QtWidgets.QLabel("Высота:"), 3, 0)
        roi_layout.addWidget(self.roi_h_input, 3, 1)
        
        refresh_btn = QtWidgets.QPushButton("🔄 Обновить кадр")
        refresh_btn.clicked.connect(self._refresh_preview_frame)
        roi_layout.addWidget(refresh_btn, 4, 0, 1, 2)
        
        right_panel.addWidget(roi_group)

        # Кнопка сохранения канала
        save_btn = QtWidgets.QPushButton("💾 Сохранить канал")
        save_btn.clicked.connect(self._save_channel)
        save_btn.setFixedHeight(36)
        right_panel.addWidget(save_btn)
        right_panel.addStretch()

        layout.addLayout(right_panel, 2)

        self._load_general_settings()
        self._reload_channels_list()
        return widget

    def _reload_channels_list(self) -> None:
        """Перезагружает список каналов."""
        self.channels_list.clear()
        for channel in self.settings.get_channels():
            self.channels_list.addItem(channel.get("name", "Канал"))
        if self.channels_list.count():
            self.channels_list.setCurrentRow(0)

    def _load_general_settings(self) -> None:
        """Загружает общие настройки."""
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
        """Выбирает папку для скриншотов."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, 
            "Выбор папки для скриншотов",
            self.screenshot_dir_input.text()
        )
        if directory:
            self.screenshot_dir_input.setText(directory)

    def _choose_db_dir(self) -> None:
        """Выбирает папку базы данных."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, 
            "Выбор папки базы данных",
            self.db_dir_input.text()
        )
        if directory:
            self.db_dir_input.setText(directory)

    def _save_general_settings(self) -> None:
        """Сохраняет общие настройки."""
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
        
        # Перезагружаем базу данных и каналы
        self.db = EventDatabase(self.settings.get_db_path())
        self._refresh_events_table()
        self._start_channels()
        
        self.status_label.setText("Общие настройки сохранены")

    def _load_channel_form(self, index: int) -> None:
        """Загружает настройки выбранного канала."""
        channels = self.settings.get_channels()
        if not (0 <= index < len(channels)):
            return
            
        channel = channels[index]
        
        # Блокируем сигналы чтобы избежать рекурсии
        self.channel_name_input.blockSignals(True)
        self.channel_source_input.blockSignals(True)
        self.best_shots_input.blockSignals(True)
        self.cooldown_input.blockSignals(True)
        self.min_conf_input.blockSignals(True)
        
        self.channel_name_input.setText(channel.get("name", ""))
        self.channel_source_input.setText(channel.get("source", ""))
        self.best_shots_input.setValue(
            int(channel.get("best_shots", self.settings.get_best_shots()))
        )
        self.cooldown_input.setValue(
            int(channel.get("cooldown_seconds", self.settings.get_cooldown_seconds()))
        )
        self.min_conf_input.setValue(
            float(channel.get("ocr_min_confidence", self.settings.get_min_confidence()))
        )
        
        self.detection_mode_input.setCurrentIndex(
            max(0, self.detection_mode_input.findData(
                channel.get("detection_mode", "continuous")
            ))
        )
        
        self.detector_stride_input.setValue(
            int(channel.get("detector_frame_stride", 2))
        )
        self.motion_threshold_input.setValue(
            float(channel.get("motion_threshold", 0.01))
        )
        self.motion_stride_input.setValue(
            int(channel.get("motion_frame_stride", 1))
        )
        self.motion_activation_frames_input.setValue(
            int(channel.get("motion_activation_frames", 3))
        )
        self.motion_release_frames_input.setValue(
            int(channel.get("motion_release_frames", 6))
        )

        # ROI
        region = channel.get("region") or {"x": 0, "y": 0, "width": 100, "height": 100}
        
        self.roi_x_input.blockSignals(True)
        self.roi_y_input.blockSignals(True)
        self.roi_w_input.blockSignals(True)
        self.roi_h_input.blockSignals(True)
        
        self.roi_x_input.setValue(int(region.get("x", 0)))
        self.roi_y_input.setValue(int(region.get("y", 0)))
        self.roi_w_input.setValue(int(region.get("width", 100)))
        self.roi_h_input.setValue(int(region.get("height", 100)))
        
        self.roi_x_input.blockSignals(False)
        self.roi_y_input.blockSignals(False)
        self.roi_w_input.blockSignals(False)
        self.roi_h_input.blockSignals(False)
        
        self.preview.set_roi(region)
        
        # Разблокируем сигналы
        self.channel_name_input.blockSignals(False)
        self.channel_source_input.blockSignals(False)
        self.best_shots_input.blockSignals(False)
        self.cooldown_input.blockSignals(False)
        self.min_conf_input.blockSignals(False)
        
        # Обновляем предпросмотр
        self._refresh_preview_frame()

    def _add_channel(self) -> None:
        """Добавляет новый канал."""
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
        
        self.status_label.setText(f"Добавлен канал {new_id}")

    def _remove_channel(self) -> None:
        """Удаляет выбранный канал."""
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if 0 <= index < len(channels):
            channel_name = channels[index].get("name", "Канал")
            channels.pop(index)
            self.settings.save_channels(channels)
            self._reload_channels_list()
            self._draw_grid()
            self._start_channels()
            
            self.status_label.setText(f"Удален канал: {channel_name}")

    def _save_channel(self) -> None:
        """Сохраняет настройки канала."""
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if not (0 <= index < len(channels)):
            return
            
        channels[index]["name"] = self.channel_name_input.text()
        channels[index]["source"] = self.channel_source_input.text()
        channels[index]["best_shots"] = int(self.best_shots_input.value())
        channels[index]["cooldown_seconds"] = int(self.cooldown_input.value())
        channels[index]["ocr_min_confidence"] = float(self.min_conf_input.value())
        channels[index]["detection_mode"] = self.detection_mode_input.currentData()
        channels[index]["detector_frame_stride"] = int(self.detector_stride_input.value())
        channels[index]["motion_threshold"] = float(self.motion_threshold_input.value())
        channels[index]["motion_frame_stride"] = int(self.motion_stride_input.value())
        channels[index]["motion_activation_frames"] = int(
            self.motion_activation_frames_input.value()
        )
        channels[index]["motion_release_frames"] = int(
            self.motion_release_frames_input.value()
        )

        # ROI
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
        
        self.status_label.setText(
            f"Настройки канала '{channels[index]['name']}' сохранены"
        )

    def _on_roi_drawn(self, roi: Dict[str, int]) -> None:
        """Обработчик изменения ROI."""
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
        """Обработчик изменения значений ROI в полях ввода."""
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
        """Обновляет кадр предпросмотра."""
        index = self.channels_list.currentRow()
        channels = self.settings.get_channels()
        
        if not (0 <= index < len(channels)):
            self.preview.setPixmap(None)
            return
            
        source = str(channels[index].get("source", "")).strip()
        if not source:
            self.preview.setPixmap(None)
            self.status_label.setText("Источник не указан")
            return
            
        try:
            # Пробуем открыть источник
            if source.isnumeric():
                source_int = int(source)
                if source_int < 0:
                    raise ValueError("Некорректный номер камеры")
                capture = cv2.VideoCapture(source_int)
            else:
                capture = cv2.VideoCapture(source)
                
            if not capture.isOpened():
                self.preview.setPixmap(None)
                self.status_label.setText(f"Не удалось открыть: {source}")
                return
                
            # Читаем кадр
            ret, frame = capture.read()
            capture.release()
            
            if not ret or frame is None:
                self.preview.setPixmap(None)
                self.status_label.setText(f"Не удалось получить кадр: {source}")
                return
                
            # Конвертируем в QImage
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb_frame.shape
            bytes_per_line = 3 * width
            
            q_image = QtGui.QImage(
                rgb_frame.data, width, height,
                bytes_per_line, QtGui.QImage.Format_RGB888
            ).copy()
            
            self.preview.setPixmap(QtGui.QPixmap.fromImage(q_image))
            self.status_label.setText(f"Кадр загружен: {source}")
            
        except Exception as e:
            logger.error(f"Ошибка загрузки предпросмотра: {e}")
            self.preview.setPixmap(None)
            self.status_label.setText(f"Ошибка: {str(e)}")

    # ------------------ Жизненный цикл ------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Обработчик закрытия окна."""
        # Подтверждение выхода
        reply = QtWidgets.QMessageBox.question(
            self,
            'Подтверждение выхода',
            'Вы уверены, что хотите выйти?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self._stop_workers()
            
            # Сохраняем настройки
            try:
                self.settings.save()
            except Exception as e:
                logger.error(f"Ошибка сохранения настроек: {e}")
                
            event.accept()
        else:
            event.ignore()


def main():
    """Точка входа в приложение."""
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ANPR Desktop")
    app.setOrganizationName("ANPR Systems")
    
    # Устанавливаем стиль
    app.setStyle('Fusion')
    
    # Создаем и показываем главное окно
    window = MainWindow()
    window.show()
    
    # Центрируем окно
    window._center_window()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
