const socket = io();

// 로봇 상태 관리 (지도 아이콘 위치 및 시뮬레이션 데이터)
window.robotState = {
    x: 0, y: 0,
    step: 25,
    currentSpeed: 0.0 
};

let isAutoMoving = false;
let accumulatedDistance = 0; 
let targetDistanceTicks = 50; 
let activeRobotId = 0; // 현재 제어 중인 로봇 ID (0 또는 1)

document.addEventListener('DOMContentLoaded', () => {
    const robotMarker = document.getElementById('robot-1');
    const mapContainer = document.querySelector('.map-zone');

    // --- 1. 초기 위치 설정 (중앙 정렬) ---
    const setCenter = () => {
        if (!robotMarker || !mapContainer) return;
        window.robotState.x = (mapContainer.clientWidth / 2) - (robotMarker.clientWidth / 2);
        window.robotState.y = (mapContainer.clientHeight / 2) - (robotMarker.clientHeight / 2);
        updatePosition();
        addLog('System', 'CENTER_ALIGN', 'info');
    };

    const updatePosition = () => {
        if (!robotMarker) return;
        robotMarker.style.left = `${window.robotState.x}px`;
        robotMarker.style.top = `${window.robotState.y}px`;
    };

    // --- 2. 로봇 제어 핵심 함수 (D-PAD & 키보드 통합) ---
    // direction: 'up', 'down', 'left', 'right', 'stop'
    // key: 'w', 's', 'a', 'd'
    window.moveRobot = (direction) => {
        let key = '';
        switch(direction) {
            case 'up':    key = 'w'; break;
            case 'down':  key = 's'; break;
            case 'left':  key = 'a'; break;
            case 'right': key = 'd'; break;
            case 'stop':  key = 's'; break;
        }

        let finalCmd = '';

        // [Robot 0] 단순 문자 전송
        if (activeRobotId === 0) {
            finalCmd = key;
        } 
        // [Robot 1] 부호 및 출력값 포함 프로토콜
        else if (activeRobotId === 1) {
            const withSign = (num) => (num >= 0 ? `+${num}` : `${num}`);
            
            // 전진 파워 10, 좌회전(-10, +30) 예시 값 적용
            const p = 10;   // w 파워
            const al = -10; // 좌측 모터
            const dl = 30;  // 우측 모터

            if (key === 'w') finalCmd = `w${withSign(p)}`;
            else if (key === 's') finalCmd = `s`;
            else if (key === 'a') finalCmd = `a${withSign(al)},d${withSign(dl)}`;
            else if (key === 'd') finalCmd = `a${withSign(dl)},d${withSign(al)}`;
        }

        // 서버로 명령 전송
        socket.emit('drive_control', { id: activeRobotId, command: finalCmd });

        // 지도 아이콘 이동 시각화 (상하좌우 방향 기준)
        if (direction !== 'stop' && mapContainer) {
            let nextX = window.robotState.x;
            let nextY = window.robotState.y;
            switch(direction) {
                case 'up':    nextY -= window.robotState.step; break;
                case 'down':  nextY += window.robotState.step; break;
                case 'left':  nextX -= window.robotState.step; break;
                case 'right': nextX += window.robotState.step; break;
            }
            if (nextX >= 0 && nextX <= (mapContainer.clientWidth - robotMarker.clientWidth)) window.robotState.x = nextX;
            if (nextY >= 0 && nextY <= (mapContainer.clientHeight - robotMarker.clientHeight)) window.robotState.y = nextY;
            updatePosition();
        }

        addLog('Control', `Robot ${activeRobotId}: [${finalCmd}]`, 'info');
    };

    // --- 3. 이벤트 바인딩 (D-PAD & 키보드) ---

    // D-PAD 버튼: 상(w), 하(s), 좌(a), 우(d) 매핑
    const dpadMap = {
        '.btn-up': 'up',
        '.btn-down': 'down',
        '.btn-left': 'left',
        '.btn-right': 'right',
        '.btn-center': 'stop'
    };

    Object.entries(dpadMap).forEach(([selector, dir]) => {
        const btn = document.querySelector(selector);
        if (btn) btn.addEventListener('click', () => window.moveRobot(dir));
    });

    // 키보드 이벤트 (wsad)
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return;
        const key = e.key.toLowerCase();
        if (key === 'w') window.moveRobot('up');
        else if (key === 's') window.moveRobot('down');
        else if (key === 'a') window.moveRobot('left');
        else if (key === 'd') window.moveRobot('right');
        else if (e.code === 'Space') {
            e.preventDefault();
            window.moveRobot('stop');
        }
    });

    // --- 4. 데이터 수신 ---
    socket.on('encoder_data', (data) => {
        const robotId = data.id;
        const lEl = document.getElementById(`enc-${robotId}-l`);
        const rEl = document.getElementById(`enc-${robotId}-r`);
        if (lEl && rEl) {
            lEl.innerText = `L:${String(data.l).padStart(3, '0')}`;
            rEl.innerText = `R:${String(data.r).padStart(3, '0')}`;
        }
    });

    socket.on('vision_data', (data) => {
        const distEl = document.getElementById('ui-dist');
        const angleEl = document.getElementById('ui-angle');
        if (distEl && angleEl) {
            distEl.innerText = data.dist;
            angleEl.innerText = data.angle;
            distEl.style.color = parseFloat(data.dist) < 20.0 ? "#ef4444" : "#3b82f6";
        }
    });

    socket.on('connect', () => addLog('Network', 'Connected to Server', 'info'));
    socket.on('disconnect', () => addLog('Network', 'Disconnected from Server', 'error'));

    setTimeout(setCenter, 100);
});

// --- 5. 자동 로그 시스템 ---
function addLog(activity, message, type = 'info') {
    const logTbody = document.getElementById('log-tbody');
    const logWrapper = document.getElementById('log-wrapper');
    if (!logTbody) return;

    const now = new Date();
    const timeStr = now.toLocaleTimeString('ko-KR', { hour12: false });
    const rowClass = type === 'error' ? 'class="log-error"' : '';
    
    const row = `<tr ${rowClass}>
                    <td>${timeStr}</td>
                    <td>${activity}</td>
                    <td style="font-weight:bold;">${message}</td>
                    <td>${type === 'error' ? '❌' : '✅'}</td>
                </tr>`;
    
    logTbody.insertAdjacentHTML('beforeend', row);
    if (logTbody.rows.length > 1000) logTbody.deleteRow(0);
    
    if (logWrapper) {
        const isAtBottom = logWrapper.scrollHeight - logWrapper.clientHeight <= logWrapper.scrollTop + 50;
        if (isAtBottom) logWrapper.scrollTop = logWrapper.scrollHeight;
    }
}

function changeMode(modeName) {
    socket.emit('change_vision_mode', { mode: modeName });
    addLog('Vision', `MODE_SET: ${modeName}`, 'info');
}