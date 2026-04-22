from flask import Flask, render_template, jsonify, Response
from flask_socketio import SocketIO
import socket
import threading
import time
import re
import cv2
import cv2.aruco as aruco
import numpy as np
import math

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


# --- [비전 설정 영역] ---
ARUCO_DICT = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
PARAMETERS = aruco.DetectorParameters()
PIXEL_TO_CM = 0.1275 

# 캘리브레이션 데이터 로드 (파일이 없을 경우 대비 예외처리 권장)
try:
    with np.load("calibration.npz") as data:
        mtx = data['mtx']
        dist_coeffs = data['dist']
except:
    mtx, dist_coeffs = None, None
    print("⚠️ 캘리브레이션 파일을 찾을 수 없습니다.")

cap = cv2.VideoCapture(0)

# 전역 변수
current_rc_client = None
is_arduino_online = False
latest_vision_data = {"dist": 0, "angle": 0}
current_vision_mode = 'TRACK' # 기본값
last_cmd_time = 0

@socketio.on('change_vision_mode')
def handle_mode_change(data):
    global current_vision_mode, current_rc_client
    current_vision_mode = data.get('mode')
    print(f"📡 현재 비전 모드 변경됨: {current_vision_mode}")
    
    # TRACK 모드가 아니게 될 때 로봇을 즉시 정지시킴 (안전 장치)
    if current_vision_mode != 'TRACK' and current_rc_client:
        try:
            current_rc_client.sendall('3'.encode())
        except:
            pass
    
    
def gen_frames():
    """비전 처리 및 웹 스트리밍용 프레임 생성기"""
    global latest_vision_data, last_cmd_time, current_vision_mode, current_rc_client
    while True:
        success, frame = cap.read()
        if not success:
            break
        
        # 1. 왜곡 보정
        if mtx is not None:
            h, w = frame.shape[:2]
            new_mtx, _ = cv2.getOptimalNewCameraMatrix(mtx, dist_coeffs, (w, h), 1, (w, h))
            frame = cv2.undistort(frame, mtx, dist_coeffs, None, new_mtx)

        # 2. ArUco 탐지 및 계산
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = aruco.detectMarkers(gray, ARUCO_DICT, parameters=PARAMETERS)

        if ids is not None:
            aruco.drawDetectedMarkers(frame, corners, ids)
            markers = {}
            for i, m_id in enumerate(ids.flatten()):
                c = corners[i][0]
                cX = int(np.mean(c[:, 0]))
                cY = int(np.mean(c[:, 1]))
                top_mid = (c[0] + c[1]) / 2
                bottom_mid = (c[2] + c[3]) / 2
                heading_rad = math.atan2(bottom_mid[1] - top_mid[1], bottom_mid[0] - top_mid[0])
                markers[m_id] = {'center': (cX, cY), 'heading': math.degrees(heading_rad)}

            # ✅ 아래 블록들이 for문 밖, if ids is not None 안에 정확히 들어와야 합니다.
            if 0 in markers and 1 in markers:
                # 거리 및 각도 계산 로직
                r_pos = markers[0]['center']
                r_head = markers[0]['heading']
                t_pos = markers[1]['center']
                
                dist_px = math.sqrt((t_pos[0]-r_pos[0])**2 + (t_pos[1]-r_pos[1])**2)
                dist_cm = dist_px * PIXEL_TO_CM
                
                target_rad = math.atan2(t_pos[1]-r_pos[1], t_pos[0]-r_pos[0])
                error_angle = math.degrees(target_rad) - r_head
                
                # 각도 보정 (-180 ~ 180)
                error_angle = (error_angle + 180) % 360 - 180

                latest_vision_data = {"dist": round(dist_cm, 1), "angle": round(error_angle, 1)}
                socketio.emit('vision_data', latest_vision_data)
                cv2.line(frame, r_pos, t_pos, (255, 0, 0), 2)

                # --- [핵심: 모드별 동작 추가] ---
                if current_vision_mode == 'TRACK' and current_rc_client:
                    current_time = time.time()
                    if current_time - last_cmd_time > 0.15:
                        try:
                            if dist_cm > 30:
                                current_rc_client.sendall('1'.encode())
                            elif dist_cm < 15:
                                current_rc_client.sendall('2'.encode())
                            else:
                                current_rc_client.sendall('3'.encode())
                            last_cmd_time = current_time
                        except Exception as e:
                            print(f"자동 조종 전송 에러: {e}")
                            current_rc_client = None

        # 3. 프레임 인코딩 후 전송
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        
# --- [기존 RC 소켓 서버 로직은 그대로 유지] ---
def rc_socket_server():
    global current_rc_client, is_arduino_online
    HOST = '0.0.0.0'
    PORT = 10000
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, PORT))
        s.listen(1)
        while True:
            client, addr = s.accept()
            current_rc_client, is_arduino_online = client, True
            client.setblocking(False) 
            data_buffer = ""
            while True:
                try:
                    data = client.recv(1024)
                    if not data: break
                    data_buffer += data.decode(errors='ignore')
                    while "\n" in data_buffer:
                        line, data_buffer = data_buffer.split("\n", 1)
                        match = re.search(r"L:(\d+)\s+R:(\d+)", line)
                        if match:
                            socketio.emit('encoder_data', {'l': match.group(1), 'r': match.group(2)})
                except BlockingIOError:
                    time.sleep(0.01); continue
                except: break
            is_arduino_online = False
            client.close()
    finally: s.close()

threading.Thread(target=rc_socket_server, daemon=True).start()

# --- [Routes] ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """웹 브라우저의 <img> 태그가 호출할 스트리밍 경로"""
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/telemetry')
def get_telemetry():
    return jsonify({
        "status": "Online" if is_arduino_online else "Offline",
        "vision_dist": latest_vision_data["dist"],
        "vision_angle": latest_vision_data["angle"],
        "battery": 88 if is_arduino_online else "--",
        "cpu": 12
    })

@socketio.on('drive_control')
def handle_drive(data):
    global current_rc_client
    cmd = str(data.get('command'))
    if current_rc_client:
        try: current_rc_client.sendall(cmd.encode())
        except: current_rc_client = None

if __name__ == '__main__':
    # 비전 연산 부하를 고려하여 debug=False 권장
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)