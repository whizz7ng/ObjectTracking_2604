import os
from flask import Flask, render_template, jsonify, Response
from flask_socketio import SocketIO
from vision import VisionSystem
from robot_manager import RobotManager
import cv2
import time
import threading
import math

# 404 방지를 위한 절대 경로 설정
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))
socketio = SocketIO(app, cors_allowed_origins="*")

vision = VisionSystem(os.path.join(base_dir, "calibration.npz"))
robot_mgr = RobotManager()

# 전역 변수
current_vision_mode = 'TRACK'
latest_vision_data = {"dist": 0, "angle": 0}
last_cmd_time = 0

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('change_vision_mode')
def handle_mode_change(data):
    global current_vision_mode
    current_vision_mode = data.get('mode')
    if current_vision_mode != 'TRACK':
        robot_mgr.send_command(0, '3')
        robot_mgr.send_command(1, '3')

cap = cv2.VideoCapture(0)

def gen_frames():
    global latest_vision_data, last_cmd_time, current_vision_mode
    
    
    while True:
        success, frame = cap.read()
        if not success: 
            print("⚠️ 카메라 프레임을 읽을 수 없습니다.")
            break

        frame, markers = vision.process_frame(frame)

        if 0 in markers and 1 in markers:
            # 거리/각도 계산 로직
            r_pos, r_head = markers[0]['center'], markers[0]['heading']
            t_pos = markers[1]['center']
            
            dist_px = math.sqrt((t_pos[0]-r_pos[0])**2 + (t_pos[1]-r_pos[1])**2)
            dist_cm = dist_px * vision.pixel_to_cm
            
            target_rad = math.atan2(t_pos[1]-r_pos[1], t_pos[0]-r_pos[0])
            error_angle = (math.degrees(target_rad) - r_head + 180) % 360 - 180

            latest_vision_data = {"dist": round(dist_cm, 1), "angle": round(error_angle, 1)}
            socketio.emit('vision_data', latest_vision_data)
            cv2.line(frame, r_pos, t_pos, (255, 0, 0), 2)

            # --- [자동 추적 로직: 로봇 1에게 명령] ---
            if current_vision_mode == 'TRACK':
                now = time.time()
                if now - last_cmd_time > 0.15:
                    # 1. 각도 먼저 맞추기 (오차가 클 때)
                    if error_angle > 15:
                        robot_mgr.send_command(1, 'L') # 왼쪽으로 회전
                    elif error_angle < -15:
                        robot_mgr.send_command(1, 'R') # 오른쪽으로 회전
                    # 2. 각도가 어느 정도 맞으면 전진/후진
                    else:
                        if dist_cm > 30: robot_mgr.send_command(1, '1')
                        elif dist_cm < 15: robot_mgr.send_command(1, '2')
                        else: robot_mgr.send_command(1, '3')
                    last_cmd_time = now                    
            

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('drive_control')
def handle_drive(data):
    # --- [수동 조종 로직: 로봇 0에게 명령] ---
    cmd = str(data.get('command'))
    robot_mgr.send_command(0, cmd)

if __name__ == '__main__':
    threading.Thread(target=robot_mgr.start_server, args=(socketio,), daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)