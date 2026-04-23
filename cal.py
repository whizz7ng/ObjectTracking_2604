import numpy as np
import cv2
import math
import os

# 1. 설정
CALIB_FILE = "calibration.npz"
REAL_DIST_CM = 30.0  # 바닥에 놓은 자의 실제 거리

if not os.path.exists(CALIB_FILE):
    print(f"에러: {CALIB_FILE} 파일이 없습니다. 먼저 캘리브레이션을 진행하세요.")
    exit()

# 기존 데이터 로드
data = dict(np.load(CALIB_FILE))
mtx = data['mtx']
dist = data['dist']

cap = cv2.VideoCapture(0)
clicked_points = []

def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        clicked_points.append((x, y))
        print(f"지점 {len(clicked_points)} 클릭: ({x}, {y})")

print(f"--- 거리 계수(pixel_to_cm) 업데이트 모드 ---")
print(f"1. 바닥에 {REAL_DIST_CM}cm 자를 똑바로 놓으세요.")
print(f"2. 화면에서 자의 양 끝 지점을 순서대로 클릭하세요.")
print(f"3. 잘못 클릭했다면 'r'을 눌러 초기화하세요. 'q'는 종료입니다.")

while True:
    ret, frame = cap.read()
    if not ret: break

    # 렌즈 왜곡 보정 적용 (정확한 거리 측정을 위해 필수)
    h, w = frame.shape[:2]
    new_mtx, roi = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))
    undistorted_frame = cv2.undistort(frame, mtx, dist, None, new_mtx)

    # 클릭한 지점 표시
    for pt in clicked_points:
        cv2.circle(undistorted_frame, pt, 5, (0, 0, 255), -1)
    
    if len(clicked_points) == 2:
        p1, p2 = clicked_points[0], clicked_points[1]
        cv2.line(undistorted_frame, p1, p2, (0, 255, 0), 2)
        
        # 픽셀 거리 계산
        pixel_dist = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
        new_p2c = REAL_DIST_CM / pixel_dist
        
        cv2.putText(undistorted_frame, f"Px Dist: {pixel_dist:.1f}", (10, 60), 1, 1.5, (255, 255, 0), 2)
        cv2.putText(undistorted_frame, f"New P2C: {new_p2c:.6f}", (10, 100), 1, 1.5, (0, 255, 0), 2)
        cv2.putText(undistorted_frame, "Press 's' to Save / 'r' to Reset", (10, 140), 1, 1.2, (255, 255, 255), 2)

    cv2.imshow('Update Distance Scale', undistorted_frame)
    cv2.setMouseCallback('Update Distance Scale', mouse_callback)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('s') and len(clicked_points) == 2:
        # 파일 업데이트
        data['pixel_to_cm'] = new_p2c
        np.savez(CALIB_FILE, **data)
        print(f"\n성공: 새로운 계수 {new_p2c:.6f} 가 {CALIB_FILE}에 저장되었습니다.")
        break
    elif key == ord('r'):
        clicked_points = []
        print("초기화되었습니다. 다시 클릭하세요.")
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()