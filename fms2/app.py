import os
from flask import Flask, render_template, Response
from flask_socketio import SocketIO
from vision import VisionSystem
from robot_manager import RobotManager
import cv2
import time
import threading
import math

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))
socketio = SocketIO(app, cors_allowed_origins="*")

vision = VisionSystem(os.path.join(base_dir, "calibration.npz"))
robot_mgr = RobotManager()

current_vision_mode = 'TRACK'
last_cmd_time = 0

# --- [수정] 보정값 저장 변수 추가 ---
robot_calibrations = {0: 1.14, 1: 1.16}

@app.route('/')
def index():
    return render_template('index.html')

# --- [복구] 누락되었던 비디오 피드 라우트 ---
@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('change_vision_mode')
def handle_mode_change(data):
    global current_vision_mode
    current_vision_mode = data.get('mode')
    if current_vision_mode != 'TRACK':
        robot_mgr.send_command(0, 's')
        robot_mgr.send_command(1, 's')

# --- [추가] 브라우저 보정값 수신 ---
@socketio.on('update_calibration')
def handle_calibration(data):
    global robot_calibrations
    try:
        robot_calibrations[int(data.get('id'))] = float(data.get('factor', 1.0))
    except: pass

cap = cv2.VideoCapture(0)

def gen_frames():
    global last_cmd_time, current_vision_mode, robot_calibrations
    
    while True:
        success, frame = cap.read()
        if not success: break
        frame, markers = vision.process_frame(frame)

        if 0 in markers and 1 in markers:
            r_pos, r_head = markers[0]['center'], markers[0]['heading']
            t_pos = markers[1]['center']
            
            dist_px = math.sqrt((t_pos[0]-r_pos[0])**2 + (t_pos[1]-r_pos[1])**2)
            dist_cm = dist_px * vision.pixel_to_cm
            
            target_rad = math.atan2(t_pos[1]-r_pos[1], t_pos[0]-r_pos[0])
            error_angle = (math.degrees(target_rad) - r_head + 180) % 360 - 180

            socketio.emit('vision_data', {"dist": round(dist_cm, 1), "angle": round(error_angle, 1)})
            cv2.line(frame, r_pos, t_pos, (255, 0, 0), 2)


            if current_vision_mode == 'TRACK':
                now = time.time()
                if now - last_cmd_time > 0.05:
                    if dist_cm > 20.0:
                        dist_error = dist_cm - 20.0
                        v = dist_error * 2.5 
                        w = error_angle * 1.5 if abs(error_angle) > 5 else 0

                        # 1. 먼저 순수 계산
                        pwm_l_raw = int(v + w)
                        pwm_r_raw = int(v - w)

                        # 2. 하드웨어 한계치(limit) 적용
                        limit = 60
                        pwm_l = max(min(pwm_l_raw, limit), -limit)
                        pwm_r = max(min(pwm_r_raw, limit), -limit)

                        # 3. 마지막에 보정 계수 곱하기 (이 순서여야 0.5 반영이 보임)
                        # Robot 0은 수동이므로 여기서는 Robot 1(자동주행)만 적용
                        pwm_r = int(pwm_r * robot_calibrations.get(1, 1.0))

                        def sign(n): return f"+{n}" if n >= 0 else str(n)
                        final_auto_cmd = f"a{sign(pwm_l)}d{sign(pwm_r)}"
                        
                        robot_mgr.send_command(1, final_auto_cmd)
                        
                        socketio.emit('log', {
                            'type': 'AutoControl',
                            'msg': f"Robot 1: [{final_auto_cmd}] (Cali: {robot_calibrations.get(1)})",
                            'status': 'success'
                        })
                    # --- [추가] 20cm 이하일 경우 정지 명령 전송 ---
                    else:
                        robot_mgr.send_command(1, "a+0d+0")
                        socketio.emit('log', {
                            'type': 'AutoControl',
                            'msg': "Robot 1: Target Reached (Stop)",
                            'status': 'success'
                        })
                    last_cmd_time = now


        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@socketio.on('drive_control')
def handle_drive(data):
    cmd = str(data.get('command'))
    robot_mgr.send_command(0, cmd)

# --- [추가] 로봇 1 비상 키보드 제어 (TRACK 모드 중 개입용) ---
@socketio.on('emergency_control_robot1')
def handle_emergency_robot1(data):
    key_cmd = data.get('command')
    
    # [수정] 하드코딩된 80을 지우고, 브라우저가 보내준 값을 사용합니다.
    # 브라우저에서 90을 보내면 90이 들어옵니다.
    base_pwm = data.get('pwm') 
    
    if base_pwm is None:
        base_pwm = 80 # 혹시라도 값이 안 넘어올 경우를 대비한 안전장치
    else:
        base_pwm = int(base_pwm)
        
    target_id = 1
    cali = robot_calibrations.get(target_id, 1.16)
    
    pwm_l, pwm_r = 0, 0

    if key_cmd == 'up':
        pwm_l, pwm_r = base_pwm, base_pwm
    elif key_cmd == 'down':
        pwm_l, pwm_r = -base_pwm, -base_pwm
    elif key_cmd == 'left':
        pwm_l, pwm_r = -base_pwm, base_pwm
    elif key_cmd == 'right':
        pwm_l, pwm_r = base_pwm, -base_pwm
    elif key_cmd == 'stop':
        pwm_l, pwm_r = 0, 0

    # 보정치 적용 및 프로토콜 생성 (쉼표와 줄바꿈 포함)
    pwm_l_final = int(pwm_l)
    pwm_r_final = int(pwm_r * cali)

    def sign(n): return f"+{n}" if n >= 0 else str(n)
    
    # 로봇 0 형식: a+90,d+104\n (90 * 1.16 = 104.4)
    final_cmd = f"a{sign(pwm_l_final)},d{sign(pwm_r_final)}\n"
    
    robot_mgr.send_command(target_id, final_cmd)

    # 실제 나가는 값을 로그로 확인
    socketio.emit('log', {
        'type': 'EMERGENCY',
        'msg': f"Robot 1 Override: {final_cmd.strip()}",
        'status': 'danger'
    })    

if __name__ == '__main__':
    threading.Thread(target=robot_mgr.start_server, args=(socketio,), daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)