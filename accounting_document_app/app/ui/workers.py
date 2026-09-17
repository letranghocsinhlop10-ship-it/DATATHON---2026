"""QThread bọc các service tầng ``app/services`` — không block main thread.

Mỗi worker chạy MỘT bước của pipeline (SCAN, MATCH...) trong luồng riêng và
phát tín hiệu Qt để MainWindow cập nhật progress bar / bảng mà không đụng
trực tiếp vào widget từ thread khác (Qt cấm việc đó).

Huỷ là "cooperative": ``request_cancel()`` chỉ bật một cờ, service tự kiểm
tra cờ đó SAU MỖI FILE rồi dừng — không bao giờ kill thread giữa chừng, vì
kill giữa chừng có thể để DB ở trạng thái dở dang.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from app.services.match_service import MatchResult, MatchService
from app.services.scan_service import ScanProgress, ScanResult, ScanService

__all__ = ["ScanWorker", "MatchWorker"]

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Chạy ``ScanService.scan_folder`` trong luồng riêng.

    Signals:
        progress: Phát sau mỗi file, mang ``ScanProgress``.
        finished_ok: Phát khi quét xong, mang ``ScanResult``.
        failed: Phát khi có lỗi không lường trước làm dừng cả worker
            (KHÁC với lỗi từng file — lỗi từng file được ``ScanService`` tự
            xử lý và không tới đây).
    """

    progress = Signal(object)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, service: ScanService, folder: str, run_id: int | None, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._folder = folder
        self._run_id = run_id
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        """Yêu cầu dừng sau file đang xử lý — không kill thread."""
        logger.info("Người dùng yêu cầu huỷ quét")
        self._cancel_event.set()

    def run(self) -> None:  # noqa: D102 - override QThread.run
        try:
            result = self._service.scan_folder(
                self._folder,
                run_id=self._run_id,
                on_progress=lambda p: self.progress.emit(p),
                should_cancel=self._cancel_event.is_set,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 - báo lỗi qua signal, không crash app
            logger.exception("ScanWorker lỗi không lường trước")
            self.failed.emit(str(exc))


class MatchWorker(QThread):
    """Chạy ``MatchService.match_run`` trong luồng riêng.

    Signals:
        finished_ok: Phát khi ghép xong, mang ``MatchResult``.
        failed: Phát khi có lỗi không lường trước.
    """

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, service: MatchService, run_id: int, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._run_id = run_id

    def run(self) -> None:  # noqa: D102 - override QThread.run
        try:
            result = self._service.match_run(self._run_id)
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("MatchWorker lỗi không lường trước")
            self.failed.emit(str(exc))
