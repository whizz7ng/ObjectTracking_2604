import os
from flask import Flask, render_template, Response
from flask_socketio import SocketIO
from vision import VisionSystem
from robot_manager import RobotManager
import cv2
import time
import threading
import math

# --- 서버 경로 및 Flask 설정 ---
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))
socketio = SocketIO(app, cors_allowed_origins="*")

# --- 시스템 초기화 ---
# VisionSystem: ArUco 마커 감지 및 좌표 변환 시스템
# RobotManager: 실제 로봇 하드웨어와 시리얼 통신을 관리하는 모듈
vision = VisionSystem(os.path.join(base_dir, "calibration.npz"))
robot_mgr = RobotManager()

# --- 전역 상태 변수 ---
current_vision_mode = 'TRACK' # 현재 모드 (TRACK: 자동 추적, IDLE: 대기 등)
last_cmd_time = 0             # 명령 전송 간격 조절을 위한 타임스탬프
is_robot1_manual = False      # 사용자가 방향키로 조작 중일 때 자동 주행 간섭 방지
was_stopped = False           # 중복 정지 명령 전송 방지 (통신 부하 감소)

# 각 로봇의 좌우 모터 편차 보정 계수 (오른쪽 바퀴 PWM에 곱해짐)
robot_calibrations = {0: 1.17, 1: 1.11}

@app.route('/')
def index():
    """메인 관제 페이지 렌더링"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """웹 브라우저에 실시간 영상 스트리밍 전송"""
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('change_vision_mode')
def handle_mode_change(data):
    """웹 UI에서 추적 모드 변경 시 호출"""
    global current_vision_mode
    current_vision_mode = data.get('mode')
    if current_vision_mode != 'TRACK':
        # 추적 중단 시 모든 로봇 안전 정지
        robot_mgr.send_command(0, 's')
        robot_mgr.send_command(1, 's')

@socketio.on('update_calibration')
def handle_calibration(data):
    """웹 UI에서 실시간으로 입력한 보정 계수 업데이트"""
    global robot_calibrations
    try:
        robot_calibrations[int(data.get('id'))] = float(data.get('factor', 1.0))
    except: pass

# 카메라 장치 연결 (0번 카메라)
cap = cv2.VideoCapture(0)
last_error_angle = 0  # 이전 각도 오차 저장용

def gen_frames():
    """
    [함수 기능 정의]
    1. 영상 스트리밍 및 ArUco 마커 인식 (Robot 0, 1)
    2. 로봇 간 물리적 거리(cm) 및 상대 각도(degree) 계산
    3. TRACK 모드: 거리 23cm 초과 시 PWM 75~150 범위 내에서 제어 주행
    4. 지능형 조향: 가변 Gain + Damping 브레이크 + 배면 회전 고정 로직 적용
    5. 안전 로직: 시야 이탈 시 즉시 정지 및 정지 명령 중복 전송 방지(was_stopped 플래그)
    6. 사용자 우선: 키보드 조작 시 자동 주행 명령 차단
    """
    global last_cmd_time, current_vision_mode, robot_calibrations, is_robot1_manual, was_stopped, last_error_angle
    
    while True:
        success, frame = cap.read()
        if not success: break
        
        # 1. 마커 탐지 및 좌표 획득 (vision.py 호출)
        frame, markers = vision.process_frame(frame)

        if current_vision_mode == 'TRACK':
            now = time.time()
            # 0.05초(20Hz) 간격으로 제어 명령 계산 (너무 빠르면 시리얼 통신 병목 발생)
            if now - last_cmd_time > 0.05:

                # 2. 로봇별 포즈(좌표+각도) 산출 (좌/우 듀얼 마커 조합 방식)
                target_robot = vision.get_robot_pose(markers, 10, 11)   # 로봇 0
                follower_robot = vision.get_robot_pose(markers, 20, 21) # 로봇 1 (추적기)

                if target_robot['detected'] and follower_robot['detected']:
                    # 두 로봇 사이의 거리 및 상대 각도 계산
                    r_pos, r_head = follower_robot['center'], follower_robot['heading']
                    t_pos = target_robot['center']
                    
                    # 피타고라스 정리로 픽셀 거리 계산 후 cm로 변환
                    dist_px = math.sqrt((t_pos[0]-r_pos[0])**2 + (t_pos[1]-r_pos[1])**2)
                    dist_cm = dist_px * vision.pixel_to_cm
                    
                    # 삼각함수를 이용한 타겟 방향각 계산 (수학적 좌표계: 왼쪽 +, 오른쪽 -)
                    target_rad = math.atan2(t_pos[1]-r_pos[1], t_pos[0]-r_pos[0])
                    error_angle = (math.degrees(target_rad) - r_head + 180) % 360 - 180

                    # UI 데이터 전송
                    socketio.emit('vision_data', {"dist": round(dist_cm, 1), "angle": round(error_angle, 1)})

                    # 3. 자동 주행 판단 (수동 조작 중이 아닐 때만)
                    if not is_robot1_manual:
                        stop_threshold = 23.0 # 정지 거리 (cm)
                        
                        if dist_cm > stop_threshold:
                            # [선속도 v 계산] 거리에 비례한 비례 제어
                            dist_error = dist_cm - stop_threshold
                            v = dist_error * 2.2 
                            
                            # --- [지능형 조향 w 계산 로직 시작] ---
                            deadzone = 10.0      # 조향 불감대
                            base_w_gain = 0.8    # 기본 조향 계수
                            d_gain = 0.3         # Damping 브레이크 계수


                            # --- [수정] 조향 방향성 교정 ---

                            if abs(error_angle) <= deadzone:
                                w = 0
                                last_error_angle = 0
                            else:
                                if abs(error_angle) > 140:
                                    # 타겟이 좌측(각도 부호에 따라)에 있다면 
                                    # 수동 좌회전 명령(a 작게, d 크게)이 나오도록 w 방향을 조정
                                    # 기존: w = 100 if error_angle > 0 else -100
                                    w = -100 if error_angle > 0 else 100 
                                else:
                                    adjusted_error = error_angle - (deadzone if error_angle > 0 else -deadzone)
                                    
                                    dynamic_gain = base_w_gain * (abs(adjusted_error) / 90.0)
                                    dynamic_gain = max(0.4, min(dynamic_gain, base_w_gain))
                                    
                                    p_term = adjusted_error * dynamic_gain
                                    d_term = (error_angle - last_error_angle) * d_gain
                                    
                                    # [핵심] 여기서 마이너스를 붙여서 수동 조작 방향과 일치시킵니다.
                                    w = -(p_term + d_term) 
                                
                                last_error_angle = error_angle

                            # 회전량 최종 제한: 선속도(v) 대비 과도한 회전 방지
                            max_w = 100 if abs(v) < 80 else abs(v) * 0.9
                            w = max(min(w, max_w), -max_w)
                            # --- [지능형 조향 w 계산 로직 종료] ---

                            # 4. PWM 제한 및 최소 구동력 확보
                            min_pwm, limit = 75, 150
                            pwm_l_raw = v - w 
                            pwm_r_raw = v + w
                            
                            pwm_l = max(min(pwm_l_raw, limit), -limit)
                            pwm_r = max(min(pwm_r_raw, limit), -limit)

                            # 정지 상태에서 출발 시 모터 마찰력을 이기기 위한 최소 PWM 보정
                            if 0 < pwm_l < min_pwm: pwm_l = min_pwm
                            elif -min_pwm < pwm_l < 0: pwm_l = -min_pwm
                            if 0 < pwm_r < min_pwm: pwm_r = min_pwm
                            elif -min_pwm < pwm_r < 0: pwm_r = -min_pwm

                            # 5. 최종 출력 계산 (우측 모터 보정 계수 적용)
                            current_cali = robot_calibrations.get(1, 1.0)
                            pwm_l_final = int(pwm_l)
                            pwm_r_final = int(pwm_r * current_cali)
                            pwm_r_final = max(min(pwm_r_final, limit), -limit)

                            # 문자열 형태의 명령 생성 (예: a+100,d+116)
                            def sign(n): return f"+{n}" if n >= 0 else str(n)
                            final_auto_cmd = f"a{sign(pwm_l_final)},d{sign(pwm_r_final)}\n"
                            
                            move_dir = "직진" if w == 0 else ("좌회전" if w > 0 else "우회전")
                            
                            # 로그 출력 및 명령 전송
                            print(f"[자동] {move_dir} | 계수: {current_cali:.2f} | 명령: {final_auto_cmd.strip()} | 각도: {error_angle:.1f}°")
                            robot_mgr.send_command(1, final_auto_cmd)
                            was_stopped = False # 주행 중이므로 정지 플래그 해제

                            # 관제 시스템 실시간 로그 전송
                            socketio.emit('log', {
                                'type': 'AUTO',
                                'msg': f"[자동] {move_dir} | 명령: {final_auto_cmd.strip()} | 각도: {error_angle:.1f}°",
                                'status': 'info'
                            })
                            
                        else:
                            # 목표 도달 시 정지 (중복 명령 방지)
                            if not was_stopped:
                                robot_mgr.send_command(1, "a+0,d+0\n")
                                was_stopped = True 
                                print(f"[디버그] 정지: 목표 도달")
                                socketio.emit('log', {'type': 'SYSTEM', 'msg': '목표 도달: 정지', 'status': 'success'})
                
                else:
                    # 마커 인식 실패 시 안전을 위해 즉시 정지
                    if not is_robot1_manual and not was_stopped:
                        robot_mgr.send_command(1, "a+0,d+0\n")
                        was_stopped = True
                        print(f"[디버그] 정지: 인식 불가")

                last_cmd_time = now

        # 영상 데이터를 JPG로 인코딩하여 스트리밍
        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        
        
@socketio.on('drive_control')
def handle_drive(data):
    """로봇 0 (타겟) 수동 제어 핸들러"""
    cmd = str(data.get('command'))
    robot_mgr.send_command(0, cmd)

@socketio.on('emergency_control_robot1')
def handle_emergency_robot1(data):
    """로봇 1 (추적기) 수동 비상 제어 핸들러 (사용자 우선순위)"""
    global is_robot1_manual
    key_cmd = data.get('command')
    
    # 5. 수동 제어 우선 로직
    # 정지 명령이 오면 수동 모드를 해제하여 다시 자동 추적이 가능하게 함
    if key_cmd == 'stop':
        is_robot1_manual = False
    else:
        is_robot1_manual = True # 방향키 입력 중에는 자동 추적 로직 무시

    base_pwm = data.get('pwm') 
    base_pwm = int(base_pwm) if base_pwm is not None else 80
    cali = robot_calibrations.get(1, 1.0)
    
    # 회전 시 회전 반경을 부드럽게 하기 위해 안쪽 바퀴는 50% 속도 적용
    half_pwm = int(base_pwm / 2)
    
    pwm_l, pwm_r = 0, 0
    move_desc = ""

    # 입력 키에 따른 방향 설정
    if key_cmd == 'up': 
        pwm_l, pwm_r = base_pwm, base_pwm
        move_desc = "전진"
    elif key_cmd == 'down': 
        pwm_l, pwm_r = -base_pwm, -base_pwm
        move_desc = "후진"
    elif key_cmd == 'left': 
        pwm_l, pwm_r = half_pwm, base_pwm
        move_desc = "좌회전"
    elif key_cmd == 'right': 
        pwm_l, pwm_r = base_pwm, half_pwm
        move_desc = "우회전"
    elif key_cmd == 'stop': 
        pwm_l, pwm_r = 0, 0
        move_desc = "정지"

    # 수동 제어에서도 보정 계수 적용
    pwm_l_final = int(pwm_l)
    pwm_r_final = int(pwm_r * cali)

    def sign(n): return f"+{n}" if n >= 0 else str(n)
    final_cmd = f"a{sign(pwm_l_final)},d{sign(pwm_r_final)}\n"
    
    # 디버그 정보 출력
    if key_cmd != 'stop':
        print(f"[수동] 로봇1 {move_desc} | 계수: {cali:.2f} | 최종명령: {final_cmd.strip()}")
    else:
        print(f"[수동] 로봇1 {move_desc}")

    robot_mgr.send_command(1, final_cmd)

    # 비상 오버라이드 로그 전송
    socketio.emit('log', {
        'type': 'EMERGENCY',
        'msg': f"Robot 1 Override: {final_cmd.strip()} (Cali: {cali})",
        'status': 'danger'
    })    

if __name__ == '__main__':
    # RobotManager 서버를 별도 스레드로 실행 (비차단형)
    threading.Thread(target=robot_mgr.start_server, args=(socketio,), daemon=True).start()
    # Flask 앱 실행
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)