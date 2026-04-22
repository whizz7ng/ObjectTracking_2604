import cv2
import cv2.aruco as aruco
import numpy as np
import math

class VisionSystem:
    def __init__(self, calibration_file="calibration.npz"):
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        self.parameters = aruco.DetectorParameters()
        self.pixel_to_cm = 0.1275 
        
        try:
            with np.load(calibration_file) as data:
                self.mtx = data['mtx']
                self.dist_coeffs = data['dist']
        except:
            self.mtx, self.dist_coeffs = None, None
            print("⚠️ 캘리브레이션 파일을 찾을 수 없습니다.")

    def process_frame(self, frame):
        """왜곡 보정 및 마커 탐지"""
        if self.mtx is not None:
            h, w = frame.shape[:2]
            new_mtx, _ = cv2.getOptimalNewCameraMatrix(self.mtx, self.dist_coeffs, (w, h), 1, (w, h))
            frame = cv2.undistort(frame, self.mtx, self.dist_coeffs, None, new_mtx)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = aruco.detectMarkers(gray, self.aruco_dict, parameters=self.parameters)
        
        markers = {}
        if ids is not None:
            aruco.drawDetectedMarkers(frame, corners, ids)
            for i, m_id in enumerate(ids.flatten()):
                c = corners[i][0]
                cX, cY = int(np.mean(c[:, 0])), int(np.mean(c[:, 1]))
                top_mid = (c[0] + c[1]) / 2
                bottom_mid = (c[2] + c[3]) / 2
                heading = math.degrees(math.atan2(bottom_mid[1] - top_mid[1], bottom_mid[0] - top_mid[0]))
                markers[int(m_id)] = {'center': (cX, cY), 'heading': heading}
        
        return frame, markers