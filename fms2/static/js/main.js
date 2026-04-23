const socket = io();
window.robotState = { x: 0, y: 0, step: 25 };
const MANUAL_ROBOT_ID = 0;

// --- [기존] 보정값 동기화 함수 유지 ---
const syncCalibration = (robotId) => {
    const factor = document.getElementById(`calib-${robotId}`)?.value || "1.0";
    socket.emit('update_calibration', { id: robotId, factor: factor });
};

// --- [기존] 로봇 0 제어 함수 유지 ---
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

// --- [추가] 로봇 1 비상제어 전송 함수 (기존 로직과 분리) ---
function sendEmergencyCmd(command) {
    // HTML의 로봇 0 PWM 값을 그대로 가져옴
    const pwmVal = document.getElementById('manual-pwm')?.value || 80;
    
    socket.emit('emergency_control_robot1', { 
        command: command,
        pwm: pwmVal
    });
    
    if (command === "stop") {
        addLog('Emergency', 'Robot 1 STOP', 'error');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // --- [기존] 이벤트 리스너 등록 유지 ---
    document.getElementById('calib-0')?.addEventListener('change', () => syncCalibration(0));
    document.getElementById('calib-1')?.addEventListener('change', () => syncCalibration(1));
    setTimeout(() => { syncCalibration(0); syncCalibration(1); }, 1000);

    let isMoving = false;
    const dpad = document.querySelector('.d-pad');
    
    // --- [기존] D-Pad 제어 로직 유지 ---
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

    // --- [기존 + 추가] 키보드 입력 통합 관리 ---
    document.onkeydown = (e) => {
        if (e.target.tagName === 'INPUT' || e.repeat) return;
        
        // 1. 로봇 0 제어 (WASD)
        const key = e.key.toLowerCase();
        let dir0 = key === 'w' ? 'up' : key === 's' ? 'down' : key === 'a' ? 'left' : key === 'd' ? 'right' : '';
        if (dir0) { isMoving = true; window.moveRobot(dir0); return; }

        // 2. 로봇 1 비상 제어 (방향키)
        let dir1 = null;
        switch(e.code) {
            case "ArrowUp":    dir1 = "up";    break;
            case "ArrowDown":  dir1 = "down";  break;
            case "ArrowLeft":  dir1 = "left";  break;
            case "ArrowRight": dir1 = "right"; break;
        }
        if (dir1) { isMoving = true; sendEmergencyCmd(dir1); return; }

        // 3. 공통 비상 정지 (Space)
        if (e.code === 'Space') { 
            e.preventDefault(); 
            isMoving = false;
            window.moveRobot('stop'); 
            sendEmergencyCmd('stop');
        }
    };

    document.onkeyup = (e) => {
        // 로봇 0 정지 (WASD 해제 시)
        if (['w', 'a', 's', 'd'].includes(e.key.toLowerCase()) && isMoving) {
            isMoving = false; window.moveRobot('stop');
        }
        // 로봇 1 정지 (방향키 해제 시)
        if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.code)) {
            isMoving = false; sendEmergencyCmd("stop");
        }
    };

    // --- [기존] 소켓 리스너 유지 ---
    socket.on('vision_data', (data) => {
        document.getElementById('ui-dist').textContent = data.dist.toFixed(1);
        document.getElementById('ui-angle').textContent = data.angle.toFixed(1);
    });
    socket.on('log', (data) => addLog(data.type, data.msg, data.status === 'success' ? 'info' : 'error'));
});

// --- [기존] 로그 출력 함수 유지 ---
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