from __future__ import annotations
import cv2
import numpy as np


# ── helpers ───────────────────────────────────────────────────────────────────

def order_points(pts: np.ndarray) -> np.ndarray:
    """Return 4 points ordered: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # TL: smallest x+y
    rect[2] = pts[np.argmax(s)]   # BR: largest  x+y
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # TR: smallest y-x
    rect[3] = pts[np.argmax(diff)]  # BL: largest  y-x
    return rect


# ── document / paper detection ────────────────────────────────────────────────

def detect_and_warp(img: np.ndarray, min_area_ratio: float = 0.04):
    """
    Find the largest rectangle in *img* and perspective-warp it to a flat view.

    Returns
    -------
    annotated : BGR image with the detected contour drawn on it
    warped    : perspective-corrected crop (or the original if nothing found)
    found     : bool
    """
    h, w = img.shape[:2]
    min_area = w * h * min_area_ratio

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Build an edge map that's robust to varying lighting
    edged = cv2.Canny(blurred, 30, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edged = cv2.dilate(edged, kernel, iterations=2)
    edged = cv2.erode(edged, kernel, iterations=1)

    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours:
        if cv2.contourArea(c) < min_area:
            break
        peri = cv2.arcLength(c, True)
        for eps_factor in (0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(c, eps_factor * peri, True)
            if len(approx) != 4:
                continue

            pts = order_points(approx.reshape(4, 2).astype("float32"))
            tl, tr, br, bl = pts
            out_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
            out_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
            if out_w < 60 or out_h < 60:
                continue

            dst = np.array([[0, 0], [out_w - 1, 0],
                            [out_w - 1, out_h - 1], [0, out_h - 1]], dtype="float32")
            M = cv2.getPerspectiveTransform(pts, dst)
            warped = cv2.warpPerspective(img, M, (out_w, out_h))

            annotated = img.copy()
            cv2.drawContours(annotated, [approx], -1, (0, 230, 80), 3)
            labels = ["TL", "TR", "BR", "BL"]
            for i, pt in enumerate(pts):
                cv2.circle(annotated, tuple(pt.astype(int)), 8, (0, 80, 255), -1)
                cv2.putText(annotated, labels[i],
                            (int(pt[0]) + 10, int(pt[1]) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
            return annotated, warped, True

    annotated = img.copy()
    cv2.putText(annotated, "No rectangle detected — try better lighting",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 60, 255), 2)
    return annotated, img, False


# ── edge → plottable polylines ────────────────────────────────────────────────

def trace_to_paths(img: np.ndarray,
                   thresh1: int = 40,
                   thresh2: int = 120,
                   min_pts: int = 4,
                   simplify_px: float = 2.0,
                   bed_mm: float = 220.0) -> list:
    """
    Canny-edge the image, find contours, and return them as plotter paths
    (list of [(x_mm, y_mm), ...] in 0-bed_mm space).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, thresh1, thresh2)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    ih, iw = edges.shape
    paths = []
    for c in contours:
        if len(c) < min_pts:
            continue
        if simplify_px > 0:
            c = cv2.approxPolyDP(c, simplify_px, False)
        pts = c.reshape(-1, 2)
        path = [(float(p[0]) / iw * bed_mm,
                 (1.0 - float(p[1]) / ih) * bed_mm) for p in pts]
        if len(path) >= 2:
            paths.append(path)
    return paths


def draw_trace_preview(img: np.ndarray, paths: list, bed_mm: float = 220.0) -> np.ndarray:
    """Draw *paths* back onto a copy of *img* (for preview purposes)."""
    ih, iw = img.shape[:2]
    out = img.copy()
    for path in paths:
        for i in range(1, len(path)):
            x1 = int(path[i-1][0] / bed_mm * iw)
            y1 = int((1 - path[i-1][1] / bed_mm) * ih)
            x2 = int(path[i][0] / bed_mm * iw)
            y2 = int((1 - path[i][1] / bed_mm) * ih)
            cv2.line(out, (x1, y1), (x2, y2), (0, 200, 255), 1)
    return out


# ── worksheet helpers (legacy) ────────────────────────────────────────────────

def scan_worksheet(img: np.ndarray):
    """Detect worksheet boundary (legacy helper). Returns (annotated, found)."""
    annotated, _, found = detect_and_warp(img)
    return annotated, found


# ── grid scan ────────────────────────────────────────────────────────────────

class VisionScanner:
    def __init__(self, plotter):
        self.plotter = plotter
        self.is_scanning = False

    def start_grid_scan(self, cap, grid_size=(3, 3), bed_size=(220, 220),
                        wait_time=1.5, calib_data=None,
                        progress_cb=None, status_cb=None):
        """
        Move plotter in a grid pattern, capture a frame at each position.

        progress_cb(current, total) and status_cb(str) are optional callbacks
        called from the worker thread.
        """
        import time
        self.is_scanning = True
        rows, cols = grid_size
        total = rows * cols
        step_x = bed_size[0] / (cols + 1)
        step_y = bed_size[1] / (rows + 1)

        self.plotter.home()
        time.sleep(2.5)

        images = []
        for r in range(rows):
            for c in range(cols):
                if not self.is_scanning:
                    break
                idx = r * cols + c
                tx = (c + 1) * step_x
                ty = (r + 1) * step_y

                if status_cb:
                    status_cb(f"Moving to cell {idx+1}/{total}  ({tx:.0f}, {ty:.0f}) mm")
                self.plotter.send_gcode(f"G0 X{tx:.2f} Y{ty:.2f} F5000")
                time.sleep(wait_time)

                ret, frame = cap.read()
                if ret:
                    if calib_data and calib_data.get("mtx") is not None:
                        frame = undistort_frame(frame, calib_data["mtx"], calib_data["dist"])
                    images.append(frame)
                if progress_cb:
                    progress_cb(idx + 1, total)

        self.is_scanning = False
        return images, grid_size

    def stitch_scan(self, images: list, grid_size=(3, 3)) -> np.ndarray | None:
        """Tile captured images into a composite canvas with overlap blending."""
        if not images:
            return None
        rows, cols = grid_size
        h, w = images[0].shape[:2]

        # Arrange in row-major order; blend overlapping edges with a soft feather
        canvas_w = w * cols
        canvas_h = h * rows
        canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
        weight = np.zeros((canvas_h, canvas_w, 1), dtype=np.float32)

        # Simple Gaussian weight mask per tile
        wy = cv2.getGaussianKernel(h, h * 0.4)
        wx = cv2.getGaussianKernel(w, w * 0.4)
        tile_weight = (wy @ wx.T)[:, :, np.newaxis].astype(np.float32)
        tile_weight = tile_weight / tile_weight.max()

        for i, img in enumerate(images):
            r = i // cols
            c = i % cols
            y0, x0 = r * h, c * w
            canvas[y0:y0+h, x0:x0+w] += img.astype(np.float32) * tile_weight
            weight[y0:y0+h, x0:x0+w] += tile_weight

        weight = np.maximum(weight, 1e-6)
        result = np.clip(canvas / weight, 0, 255).astype(np.uint8)
        return result


# ── calibration ───────────────────────────────────────────────────────────────

def calibrate_camera(img, grid_size=(9, 6)):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ret, corners = cv2.findChessboardCorners(gray, grid_size, None)
    if ret:
        objp = np.zeros((grid_size[0] * grid_size[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:grid_size[0], 0:grid_size[1]].T.reshape(-1, 2)
        ret, mtx, dist, _, _ = cv2.calibrateCamera(
            [objp], [corners], gray.shape[::-1], None, None)
        return True, mtx, dist
    return False, None, None


def undistort_frame(img, mtx, dist):
    if mtx is None or dist is None:
        return img
    h, w = img.shape[:2]
    new_mtx, _ = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))
    return cv2.undistort(img, mtx, dist, None, new_mtx)
