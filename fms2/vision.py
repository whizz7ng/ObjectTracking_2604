# vision.py (최종 수정본)

import cv2
import cv2.aruco as aruco
import numpy as np
import math

class VisionSystem:
    def __init__(self, calibration_file="calibration.npz"):
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_1000)
        self.parameters = aruco.DetectorParameters()
        
        self.pixel_to_cm = 0.15458784 
        self.mtx, self.dist_coeffs = None, None
        
        try:
            data = np.load(calibration_file)
            self.mtx = data['mtx']
            self.dist_coeffs = data['dist']
            
            if 'pixel_to_cm' in data:
                self.pixel_to_cm = float(data['pixel_to_cm'])
                print(f"✅ 캘리브레이션 로드 완료! (P2C: {self.pixel_to_cm:.6f})")
        except Exception as e:
            print(f"⚠️ 캘리브레이션 파일 로드 오류: {e}")


    def process_frame(self, frame):
        if self.mtx is not None:
            h, w = frame.shape[:2]
            
            # [수정] alpha 값을 0.0에서 0.3 정도로 변경합니다. 
            # 0.0보다 가장자리가 훨씬 덜 잘리지만, 여백도 약간 생깁니다.
            # 이 값을 0.1, 0.2, 0.3 식으로 바꿔보며 본인 카메라에 맞는 최적점을 찾으세요.
            alpha_val = 0.3 
            new_mtx, _ = cv2.getOptimalNewCameraMatrix(self.mtx, self.dist_coeffs, (w, h), alpha_val, (w, h))
            
            # 왜곡 보정 적용
            frame = cv2.undistort(frame, self.mtx, self.dist_coeffs, None, new_mtx)

            # [삭제] 이전 버전의 ROI 자르기는 많이 잘려나가므로 삭제합니다.
            # x, y, w_roi, h_roi = roi
            # if w_roi > 0 and h_roi > 0:
            #     frame = frame[y:y+h_roi, x:x+w_roi]
            # 자르고 난 뒤 대시보드 크기에 맞게 다시 리사이즈 (선택 사항)
            frame = cv2.resize(frame, (w, h))

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

    def get_robot_pose(self, markers, left_id, right_id):
        """두 마커를 조합하여 로봇의 중심 좌표와 벡터 기반 헤딩 계산"""
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
        
        elif left_id in markers:
            return {**markers[left_id], 'detected': True, 'mode': 'SINGLE_L'}
        elif right_id in markers:
            return {**markers[right_id], 'detected': True, 'mode': 'SINGLE_R'}
            
        return {'detected': False}