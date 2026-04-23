import cv2
import cv2.aruco as aruco
import numpy as np
import math

class VisionSystem:
    def __init__(self, calibration_file="calibration.npz"):
        # 4x4_1000 마커를 사용하시므로 설정을 유지하거나 확인이 필요합니다.
        # 기존 4x4_50에서 4x4_1000으로 변경이 필요할 수 있습니다.
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_1000) 
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
                
                # 개별 마커의 헤딩 (보조용)
                top_mid = (c[0] + c[1]) / 2
                bottom_mid = (c[2] + c[3]) / 2
                heading = math.degrees(math.atan2(bottom_mid[1] - top_mid[1], bottom_mid[0] - top_mid[0]))
                
                markers[int(m_id)] = {'center': (cX, cY), 'heading': heading}
        
        return frame, markers

    def get_robot_pose(self, markers, left_id, right_id):
        """두 마커를 조합하여 로봇의 중심 좌표와 벡터 기반 헤딩 계산"""
        # 1. 두 마커가 모두 보일 때 (가장 정확)
        if left_id in markers and right_id in markers:
            l = markers[left_id]['center']
            r = markers[right_id]['center']
            
            cX = (l[0] + r[0]) // 2
            cY = (l[1] + r[1]) // 2
            
            # 좌->우 벡터 기반 각도 계산
            dx = r[0] - l[0]
            dy = r[1] - l[1]
            angle_rad = math.atan2(dy, dx)
            # 로봇 정면 방향으로 보정 (-90도)
            heading = (math.degrees(angle_rad) - 90 + 180) % 360 - 180
            
            return {'center': (cX, cY), 'heading': heading, 'detected': True, 'mode': 'DUAL'}
        
        # 2. 한쪽 마커만 보일 때 (추적 유지용)
        elif left_id in markers:
            return {**markers[left_id], 'detected': True, 'mode': 'SINGLE_L'}
        elif right_id in markers:
            return {**markers[right_id], 'detected': True, 'mode': 'SINGLE_R'}
            
        return {'detected': False}