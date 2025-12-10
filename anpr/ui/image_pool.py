"""Простой пул QImage для переиспользования буферов кадров."""

from __future__ import annotations

import ctypes
from typing import Dict, Tuple

import numpy as np
from PyQt5 import QtGui


class ImagePool:
    """Кэширует QImage по размеру кадра и обновляет их без переразметки памяти."""

    def __init__(self) -> None:
        self._pool: Dict[Tuple[int, int], QtGui.QImage] = {}

    def get_qimage(self, rgb_frame: np.ndarray) -> QtGui.QImage:
        height, width, _ = rgb_frame.shape
        key = (width, height)
        bytes_per_line = width * 3
        if key not in self._pool:
            buffer = bytearray(rgb_frame.nbytes)
            qimage = QtGui.QImage(buffer, width, height, bytes_per_line, QtGui.QImage.Format_RGB888)
            qimage._buffer = buffer  # type: ignore[attr-defined]
            self._pool[key] = qimage
        qimage = self._pool[key]
        bits = qimage.bits()
        bits.setsize(rgb_frame.nbytes)
        ctypes.memmove(int(bits), rgb_frame.ctypes.data, rgb_frame.nbytes)
        return qimage
