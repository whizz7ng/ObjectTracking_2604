const socket = io();
window.robotState = { x: 0, y: 0, step: 25 };
const MANUAL_ROBOT_ID = 0;

// --- [추가] 보정값 동기화 함수 ---
const syncCalibration = (robotId) => {
    const factor = document.getElementById(`calib-${robotId}`)?.value || "1.0";
    socket.emit('update_calibration', { id: robotId, factor: factor });
};

window.moveRobot = (direction) => {
    const basePwm = parseInt(document.getElementById('manual-pwm')?.value || "80");
    const factor0 = parseFloat(document.getElementById('calib-0')?.value || "1.0");
    
    const rightPwm = Math.round(basePwm * factor0);
    const halfBasePwm = Math.floor(basePwm / 2);
    const halfRightPwm = Math.round(halfBasePwm * factor0);
    
    let key = '';
    switch(direction) {
        case 'up':    key = `a+${basePwm},d+${rightPwm}`; break;
        case 'down':  key = `a-${basePwm},d-${rightPwm}`; break;
        case 'left':  key = `a+${halfBasePwm},d+${rightPwm}`; break;
        case 'right': key = `a+${basePwm},d+${halfRightPwm}`; break;
        case 'turnL': key = `a-${basePwm},d+${rightPwm}`; break;
        case 'turnR': key = `a+${basePwm},d-${rightPwm}`; break;
        case 'stop':  key = 'a+0,d+0'; break;
    }

    if (key) {
        socket.emit('drive_control', { id: MANUAL_ROBOT_ID, command: key + '\n' });
        addLog('Control', key, 'info'); 
    }
};

document.addEventListener('DOMContentLoaded', () => {
    // --- [추가] 이벤트 리스너 등록 ---
    document.getElementById('calib-0')?.addEventListener('change', () => syncCalibration(0));
    document.getElementById('calib-1')?.addEventListener('change', () => syncCalibration(1));
    setTimeout(() => { syncCalibration(0); syncCalibration(1); }, 1000);

    // 기존 제어 로직 유지
    let isMoving = false;
    const dpad = document.querySelector('.d-pad');
    if (dpad) {
        const handleStart = (e) => {
            if (isMoving) return;
            const btn = e.target.closest('button, .d-btn, .btn-center, .circle-btn, .turn-l, .turn-r');
            if (!btn) return;
            e.preventDefault();
            let dir = '';
            if (btn.classList.contains('btn-up')) dir = 'up';
            else if (btn.classList.contains('btn-down')) dir = 'down';
            else if (btn.classList.contains('btn-left')) dir = 'left';
            else if (btn.classList.contains('btn-right')) dir = 'right';
            else if (btn.classList.contains('btn-center')) dir = 'stop';
            else if (btn.classList.contains('turn-l')) dir = 'turnL';
            else if (btn.classList.contains('turn-r')) dir = 'turnR';
            if (dir) { isMoving = true; window.moveRobot(dir); }
        };
        const handleEnd = (e) => { if (isMoving) { isMoving = false; window.moveRobot('stop'); } };
        dpad.onmousedown = handleStart; dpad.onmouseup = handleEnd; dpad.onmouseleave = handleEnd;
        dpad.ontouchstart = handleStart; dpad.ontouchend = handleEnd;
    }

    document.onkeydown = (e) => {
        if (e.target.tagName === 'INPUT' || e.repeat) return;
        const key = e.key.toLowerCase();
        let dir = key === 'w' ? 'up' : key === 's' ? 'down' : key === 'a' ? 'left' : key === 'd' ? 'right' : '';
        if (e.code === 'Space') { e.preventDefault(); dir = 'stop'; }
        if (dir) { isMoving = true; window.moveRobot(dir); }
    };

    document.onkeyup = (e) => {
        if (['w', 'a', 's', 'd'].includes(e.key.toLowerCase()) && isMoving) {
            isMoving = false; window.moveRobot('stop');
        }
    };

    socket.on('vision_data', (data) => {
        document.getElementById('ui-dist').textContent = data.dist.toFixed(1);
        document.getElementById('ui-angle').textContent = data.angle.toFixed(1);
    });
    socket.on('log', (data) => addLog(data.type, data.msg, data.status === 'success' ? 'info' : 'error'));
});

// 로봇1 비상제어
// 키 중복 입력 방지 변수
let isMoving = false;

// 1. 키를 눌렀을 때 (keydown)
document.addEventListener('keydown', (event) => {
    let cmd = null;
    switch(event.code) {
        case "ArrowUp":    cmd = "up";    break;
        case "ArrowDown":  cmd = "down";  break;
        case "ArrowLeft":  cmd = "left";  break;
        case "ArrowRight": cmd = "right"; break;
    }

    if (cmd && !isMoving) {
        isMoving = true; // 이동 중 상태로 변경
        sendEmergencyCmd(cmd);
    }
});

// 2. 키에서 손을 뗐을 때 (keyup)
document.addEventListener('keyup', (event) => {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code)) {
        isMoving = false; // 상태 초기화
        sendEmergencyCmd("stop");
    }
});

// 3. 공통 전송 함수 (HTML의 PWM 80 값 포함)
function sendEmergencyCmd(command) {
    // 이미지의 'PWM 80' 입력 필드 값을 가져옴
    const pwmVal = document.querySelector('input[type="number"]')?.value || 80;
    
    socket.emit('emergency_control_robot1', { 
        command: command,
        pwm: pwmVal
    });
    
    // 스페이스바 별도 처리 (비상 정지)
    if (command === "stop") isMoving = false;
}

// 스페이스바는 눌렀을 때 즉시 정지
document.addEventListener('keydown', (event) => {
    if (event.code === "Space") {
        event.preventDefault();
        sendEmergencyCmd("stop");
    }
});

function addLog(activity, message, type = 'info') {
    const tbody = document.getElementById('log-tbody');
    const wrapper = document.getElementById('log-wrapper');
    if (!tbody) return;
    const time = new Date().toLocaleTimeString('ko-KR', { hour12: false });
    const row = `<tr ${type === 'error' ? 'class="log-error"' : ''}>
                    <td>${time}</td><td>${activity}</td><td><b>${message}</b></td><td>${type === 'error' ? '❌' : '✅'}</td>
                </tr>`;
    tbody.insertAdjacentHTML('beforeend', row);
    if (tbody.rows.length > 100) tbody.deleteRow(0);
    if (wrapper) wrapper.scrollTop = wrapper.scrollHeight;
}