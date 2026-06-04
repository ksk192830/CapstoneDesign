import cv2
import numpy as np

from machine_vision_client.config import VISIBLE_STREAM_URL


class VisibleStream:
    def __init__(self, url: str = VISIBLE_STREAM_URL, window_name: str = "VisibleStream"):
        self.url = url
        self.window_name = window_name
        self.capture = cv2.VideoCapture(self.url)

    def open(self) -> bool:
        if self.capture.isOpened():
            return True
        self.capture.open(self.url)
        return self.capture.isOpened()

    def read(self):
        if not self.capture.isOpened():
            raise RuntimeError("Visible stream is not opened")

        success, frame = self.capture.read()
        return frame if success else None

    def show(self) -> None:
        if not self.open():
            raise RuntimeError(f"Unable to open visible stream URL: {self.url}")

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        while True:
            frame = self.read()
            if frame is None:
                cv2.imshow(self.window_name, self._create_error_frame())
            else:
                cv2.imshow(self.window_name, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

        self.release()

    def release(self) -> None:
        if self.capture.isOpened():
            self.capture.release()
        cv2.destroyAllWindows()

    def _create_error_frame(self):
        frame = np.full((480, 640, 3), 255, dtype="uint8")
        cv2.putText(
            frame,
            "Unable to read stream",
            (20, 240),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
        return frame
