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

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('change_vision_mode')
def handle_mode_change(data):
    global current_vision_mode
    current_vision_mode = data.get('mode')
    if current_vision_mode != 'TRACK':
        robot_mgr.send_command(0, 's')
        robot_mgr.send_command(1, 's')

cap = cv2.VideoCapture(0)

def gen_frames():
    global last_cmd_time, current_vision_mode
    
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

            socketio.emit('vision_data', {
                "dist": round(dist_cm, 1), 
                "angle": round(error_angle, 1)
            })
            
            cv2.line(frame, r_pos, t_pos, (255, 0, 0), 2)

            # --- [핵심 제어 로직 시작] ---
            if current_vision_mode == 'TRACK':
                now = time.time()
                if now - last_cmd_time > 0.05:  # 50ms 주기
                    
                    # 1. 20cm보다 멀 때만 전송 실행
                    if dist_cm > 20.0:
                        dist_error = dist_cm - 20.0
                        v = dist_error * 2.5 
                        w = error_angle * 1.5 if abs(error_angle) > 5 else 0

                        pwm_l = int(v + w)
                        pwm_r = int(v - w)

                        limit = 60
                        pwm_l = max(min(pwm_l, limit), -limit)
                        pwm_r = max(min(pwm_r, limit), -limit)

                        def sign(n): return f"+{n}" if n >= 0 else str(n)
                        final_auto_cmd = f"a{sign(pwm_l)}d{sign(pwm_r)}"

                        # 명령 전송 및 로그 출력
                        robot_mgr.send_command(1, final_auto_cmd)
                        
                        socketio.emit('log', {
                            'type': 'AutoControl',
                            'msg': f"Robot 1: [{final_auto_cmd}] (Dist: {dist_cm:.1f}cm)",
                            'status': 'success'
                        })
                    
                    # 2. 20cm 미만이면 아무것도 하지 않음 (pass)
                    else:
                        pass
                    
                    last_cmd_time = now
            # --- [핵심 제어 로직 끝] ---

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('drive_control')
def handle_drive(data):
    cmd = str(data.get('command'))
    robot_mgr.send_command(0, cmd)

if __name__ == '__main__':
    threading.Thread(target=robot_mgr.start_server, args=(socketio,), daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)