const socket = io();

// 로봇 상태 관리 (시각화용)
window.robotState = {
    x: 0, y: 0,
    step: 25
};

// 수동 제어 대상 고정 (Robot 0)
const MANUAL_ROBOT_ID = 0;

window.moveRobot = (direction) => {
    let key = '';
    switch(direction) {
        case 'up':    key = 'w'; break;
        case 'down':  key = 's'; break;
        case 'left':  key = 'a'; break;
        case 'right': key = 'd'; break;
        case 'stop':  key = 's'; break;
        case 'turnL': key = 'wa'; break;
        case 'turnR': key = 'wd'; break;
    }

    // [로봇 0 전용] 단순 문자 명령 전송 (w, a, s, d 등)
    socket.emit('drive_control', { id: MANUAL_ROBOT_ID, command: key });

    // UI 로그 업데이트
    addLog('Control', `Robot ${MANUAL_ROBOT_ID}: [${key}] (${direction})`, 'info');

    // 지도 아이콘 시각화 업데이트
    updateMapVisualization(direction);
};

// 지도 아이콘 이동 로직 분리
function updateMapVisualization(direction) {
    const robotMarker = document.getElementById('robot-1');
    const mapContainer = document.querySelector('.map-zone');
    
    if (!['up', 'down', 'left', 'right'].includes(direction) || !mapContainer || !robotMarker) return;

    let nextX = window.robotState.x;
    let nextY = window.robotState.y;

    if (direction === 'up') nextY -= window.robotState.step;
    else if (direction === 'down') nextY += window.robotState.step;
    else if (direction === 'left') nextX -= window.robotState.step;
    else if (direction === 'right') nextX += window.robotState.step;

    // 경계 제한 확인
    if (nextX >= 0 && nextX <= (mapContainer.clientWidth - robotMarker.clientWidth)) window.robotState.x = nextX;
    if (nextY >= 0 && nextY <= (mapContainer.clientHeight - robotMarker.clientHeight)) window.robotState.y = nextY;
    
    robotMarker.style.left = `${window.robotState.x}px`;
    robotMarker.style.top = `${window.robotState.y}px`;
}

document.addEventListener('DOMContentLoaded', () => {
    // 초기 중앙 정렬
    const setCenter = () => {
        const robotMarker = document.getElementById('robot-1');
        const mapContainer = document.querySelector('.map-zone');
        if (!robotMarker || !mapContainer) return;
        window.robotState.x = (mapContainer.clientWidth / 2) - (robotMarker.clientWidth / 2);
        window.robotState.y = (mapContainer.clientHeight / 2) - (robotMarker.clientHeight / 2);
        robotMarker.style.left = `${window.robotState.x}px`;
        robotMarker.style.top = `${window.robotState.y}px`;
    };

    // D-Pad 클릭 이벤트 (이벤트 위임)
    const dpadContainer = document.querySelector('.d-pad');
    if (dpadContainer) {
        dpadContainer.onclick = (e) => {
            const btn = e.target.closest('button, .d-btn, .btn-center, .circle-btn, .turn-l, .turn-r');
            if (!btn) return;

            e.preventDefault();
            e.stopImmediatePropagation(); 

            let direction = '';
            if (btn.classList.contains('btn-up')) direction = 'up';
            else if (btn.classList.contains('btn-down')) direction = 'down';
            else if (btn.classList.contains('btn-left')) direction = 'left';
            else if (btn.classList.contains('btn-right')) direction = 'right';
            else if (btn.classList.contains('btn-center')) direction = 'stop';
            else if (btn.classList.contains('turn-l')) direction = 'turnL';
            else if (btn.classList.contains('turn-r')) direction = 'turnR';

            if (direction) window.moveRobot(direction);
        };
    }

    // 키보드 조작
    document.onkeydown = (e) => {
        if (e.target.tagName === 'INPUT') return;
        const key = e.key.toLowerCase();
        let direction = '';
        if (key === 'w') direction = 'up';
        else if (key === 's') direction = 'down';
        else if (key === 'a') direction = 'left';
        else if (key === 'd') direction = 'right';
        else if (e.code === 'Space') { e.preventDefault(); direction = 'stop'; }
        if (direction) window.moveRobot(direction);
    };

    socket.on('connect', () => addLog('Network', 'Connected to Server', 'info'));
    socket.on('disconnect', () => addLog('Network', 'Disconnected from Server', 'error'));
    
    setTimeout(setCenter, 100);
});

// 로그 출력 함수
function addLog(activity, message, type = 'info') {
    const logTbody = document.getElementById('log-tbody');
    const logWrapper = document.getElementById('log-wrapper');
    if (!logTbody) return;

    const timeStr = new Date().toLocaleTimeString('ko-KR', { hour12: false });
    const rowClass = type === 'error' ? 'class="log-error"' : '';
    
    const row = `<tr ${rowClass}>
                    <td>${timeStr}</td>
                    <td>${activity}</td>
                    <td style="font-weight:bold;">${message}</td>
                    <td>${type === 'error' ? '❌' : '✅'}</td>
                </tr>`;
    
    logTbody.insertAdjacentHTML('beforeend', row);
    if (logTbody.rows.length > 500) logTbody.deleteRow(0); // 로그 과다 방지
    if (logWrapper) logWrapper.scrollTop = logWrapper.scrollHeight;
}

// 비전 데이터 및 서버 로그 수신 (UI 업데이트 전용)
socket.on('vision_data', (data) => {
    const distEl = document.getElementById('ui-dist');
    const angleEl = document.getElementById('ui-angle');
    if (distEl) distEl.textContent = data.dist.toFixed(1);
    if (angleEl) angleEl.textContent = data.angle.toFixed(1);
});

socket.on('log', (data) => {
    addLog(data.type || 'AutoControl', data.msg, data.status === 'success' ? 'info' : 'error');
});