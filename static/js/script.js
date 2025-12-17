// Global variables
let statusInterval;
let mapInterval;
let isStreaming = true;
let cameraTested = false;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Test camera first
    testCamera();
    
    // Load initial data
    setTimeout(() => {
        updateStatus();
        loadSystemInfo();
        loadMovementLog();
        
        // Set up intervals
        statusInterval = setInterval(updateStatus, 2000);
        mapInterval = setInterval(updateMap, 15000);
        
        // Set up keyboard controls
        setupKeyboardControls();
        
        // Show welcome message
        showNotification('Control panel initialized. Ready for operation.', 'success');
        
        // Initialize battery level
        updateBatteryLevel(100);
    }, 1000);
});

// Test camera function
async function testCamera() {
    try {
        const response = await fetch('/api/test_camera');
        const data = await response.json();
        
        if (data.success) {
            cameraTested = true;
            document.getElementById('cameraFeed').style.borderColor = '#34c759';
            showNotification('Camera stream connected', 'success');
        } else {
            document.getElementById('cameraFeed').style.borderColor = '#ff9500';
            showNotification(`Camera: ${data.message || 'Using simulation'}`, 'warning');
        }
    } catch (error) {
        console.warn('Camera test failed:', error);
        showNotification('Camera stream unavailable - using simulated mode', 'warning');
    }
}

// Robot Connection Functions
async function connectRobot() {
    const btn = document.getElementById('connectBtn');
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Connecting...';
    btn.disabled = true;
    
    try {
        const response = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        showNotification(data.message, data.success ? 'success' : 'error');
        updateConnectionStatus(data.success);
    } catch (error) {
        showNotification('Connection failed: Network error', 'error');
        updateConnectionStatus(false);
    }
}

async function disconnectRobot() {
    try {
        const response = await fetch('/api/disconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        showNotification('Robot disconnected', 'info');
        updateConnectionStatus(false);
    } catch (error) {
        showNotification('Disconnect failed', 'error');
    }
}

// Movement Control Functions
async function sendCommand(command, duration = 1.0) {
    const btn = event?.target || document.querySelector(`[onclick*="${command}"]`);
    if (btn) {
        btn.classList.add('pulse');
        setTimeout(() => btn.classList.remove('pulse'), 300);
    }
    
    try {
        const payload = { command };
        if (duration) payload.duration = duration;
        
        const response = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        if (data.success) {
            document.getElementById('lastCommand').textContent = command.replace('_', ' ').toUpperCase();
            
            // Add to log immediately
            addToLog({
                timestamp: new Date().toISOString(),
                command: command.toUpperCase(),
                position: [0, 0], // Will be updated by status
                heading: 0,
                status: 'executed'
            });
        }
        
        setTimeout(loadMovementLog, 100);
    } catch (error) {
        console.error('Command failed:', error);
        showNotification('Command failed to send', 'error');
    }
}

function updateSpeed(speed) {
    document.getElementById('speedValue').textContent = speed;
    // In a real implementation, you would send this to the robot
    console.log('Speed updated to:', speed);
}

// AI Navigation Functions
async function navigateToTarget() {
    const target = document.getElementById('navigationTarget').value.trim();
    if (!target) {
        showNotification('Please enter a destination', 'warning');
        return;
    }
    
    document.getElementById('aiResponse').textContent = `Navigating to: "${target}"...`;
    
    try {
        const response = await fetch('/api/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target })
        });
        
        const data = await response.json();
        showNotification(`Navigation: ${data.message}`, 'info');
        
        setTimeout(() => {
            document.getElementById('aiResponse').textContent = 
                `Destination: ${target}\nStatus: Navigating...`;
        }, 1000);
    } catch (error) {
        document.getElementById('aiResponse').textContent = 'Navigation failed. Check connection.';
        showNotification('Navigation failed', 'error');
    }
}

async function exploreRoom() {
    document.getElementById('aiResponse').textContent = 'Starting autonomous exploration...';
    
    try {
        const response = await fetch('/api/explore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        showNotification('Exploration started', 'info');
        document.getElementById('aiResponse').textContent = 
            'Autonomous exploration in progress. Mapping environment...';
    } catch (error) {
        showNotification('Exploration failed to start', 'error');
    }
}

// Camera Functions
function toggleStream() {
    const btn = document.getElementById('streamBtn');
    const icon = btn.querySelector('i');
    const feed = document.getElementById('cameraFeed');
    
    if (isStreaming) {
        // Stop stream
        fetch('/api/stop_stream', { method: 'POST' }).catch(console.error);
        icon.className = 'fas fa-play';
        btn.innerHTML = '<i class="fas fa-play"></i> Resume';
        feed.style.opacity = '0.7';
        showNotification('Stream paused', 'info');
    } else {
        // Start stream
        fetch('/api/start_stream', { method: 'POST' }).catch(console.error);
        icon.className = 'fas fa-pause';
        btn.innerHTML = '<i class="fas fa-pause"></i> Pause';
        feed.style.opacity = '1';
        showNotification('Stream resumed', 'success');
    }
    
    isStreaming = !isStreaming;
}

function toggleFullscreen() {
    const feed = document.getElementById('cameraFeed');
    if (!document.fullscreenElement) {
        feed.requestFullscreen().catch(console.error);
    } else {
        document.exitFullscreen();
    }
}

async function takeSnapshot() {
    try {
        const response = await fetch('/api/snapshot');
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('snapshotImage').src = `data:image/jpeg;base64,${data.image}`;
            
            let analysisHTML = '<div style="display: grid; gap: 10px;">';
            if (data.analysis) {
                const analysis = data.analysis;
                analysisHTML += `
                    <div style="display: flex; justify-content: space-between; padding: 8px; background: #f8f9fa; border-radius: 6px;">
                        <span>Left Obstacle:</span>
                        <span style="font-weight: 600; color: ${analysis.left_obstacle ? '#dc3545' : '#28a745'}">
                            ${analysis.left_obstacle ? 'Yes' : 'No'}
                        </span>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 8px; background: #f8f9fa; border-radius: 6px;">
                        <span>Center Obstacle:</span>
                        <span style="font-weight: 600; color: ${analysis.center_obstacle ? '#dc3545' : '#28a745'}">
                            ${analysis.center_obstacle ? 'Yes' : 'No'}
                        </span>
                    </div>
                    <div style="display: flex; justify-content: space-between; padding: 8px; background: #f8f9fa; border-radius: 6px;">
                        <span>Right Obstacle:</span>
                        <span style="font-weight: 600; color: ${analysis.right_obstacle ? '#dc3545' : '#28a745'}">
                            ${analysis.right_obstacle ? 'Yes' : 'No'}
                        </span>
                    </div>
                `;
                
                // Generate navigation advice
                let advice = "Clear path ahead.";
                if (analysis.center_obstacle) {
                    advice = "Obstacle detected ahead. Consider turning left or right.";
                } else if (analysis.left_obstacle && !analysis.right_obstacle) {
                    advice = "Obstacle on left. Safe to turn right.";
                } else if (analysis.right_obstacle && !analysis.left_obstacle) {
                    advice = "Obstacle on right. Safe to turn left.";
                }
                document.getElementById('navigationAdvice').textContent = advice;
            }
            analysisHTML += '</div>';
            document.getElementById('analysisResult').innerHTML = analysisHTML;
            
            document.getElementById('snapshotModal').style.display = 'block';
        }
    } catch (error) {
        showNotification('Failed to capture snapshot', 'error');
    }
}

// Map Functions
async function updateMap() {
    try {
        const response = await fetch('/api/map');
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('mapImage').src = `data:image/png;base64,${data.map}`;
            document.getElementById('mapPosition').textContent = 
                `${data.position[0].toFixed(1)}, ${data.position[1].toFixed(1)}`;
            document.getElementById('mapHeading').textContent = `${Math.round(data.heading)}°`;
        }
    } catch (error) {
        console.error('Map update failed:', error);
    }
}

// Status Update Functions
async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (data.success) {
            const status = data.status;
            
            // Update position displays
            const posStr = `${status.position[0].toFixed(2)}, ${status.position[1].toFixed(2)}`;
            document.getElementById('robotPosition').textContent = posStr;
            document.getElementById('mapPosition').textContent = posStr.replace('.00', '');
            
            // Update other displays
            const heading = Math.round(status.heading);
            document.getElementById('robotHeading').textContent = `${heading}°`;
            document.getElementById('mapHeading').textContent = `${heading}°`;
            
            document.getElementById('currentSpeed').textContent = status.speed;
            document.getElementById('batteryPercent').textContent = `${Math.round(status.battery)}%`;
            document.getElementById('obstaclesCount').textContent = status.obstacles_detected;
            
            // Update battery level
            updateBatteryLevel(status.battery);
            
            // Update connection status
            updateConnectionStatus(status.connected);
            
            // Update movements count
            document.getElementById('movementsCount').textContent = status.movements_recorded;
        }
    } catch (error) {
        console.warn('Status update failed:', error);
    }
}

function updateBatteryLevel(level) {
    const batteryLevel = document.getElementById('batteryLevel');
    const percent = Math.min(100, Math.max(0, level));
    batteryLevel.style.width = `${100 - percent}%`;
    
    // Update battery percent color
    const percentElement = document.getElementById('batteryPercent');
    if (percent > 70) {
        percentElement.style.color = '#28a745';
    } else if (percent > 30) {
        percentElement.style.color = '#ffc107';
    } else {
        percentElement.style.color = '#dc3545';
    }
}

async function loadSystemInfo() {
    try {
        const response = await fetch('/api/system_info');
        const data = await response.json();
        
        if (data.success) {
            const info = data.info;
            document.getElementById('cameraInfo').textContent = 
                `${info.camera_resolution[0]}×${info.camera_resolution[1]}`;
            document.getElementById('arduinoPort').textContent = info.arduino_port || 'Not connected';
            document.getElementById('mapSize').textContent = `${info.map_size[0]}×${info.map_size[1]}`;
            
            // Update camera info display
            document.getElementById('cameraInfoDisplay').textContent = 
                `${info.camera_resolution[0]}×${info.camera_resolution[1]} @ ${info.frame_rate || 30}fps`;
        }
    } catch (error) {
        console.error('System info load failed:', error);
    }
}

async function loadMovementLog() {
    try {
        const response = await fetch('/api/movement_log');
        const data = await response.json();
        
        if (data.success && data.movements.length > 0) {
            const logBody = document.getElementById('logBody');
            logBody.innerHTML = '';
            
            // Show only last 10 movements
            const recentMovements = data.movements.slice(-10).reverse();
            
            recentMovements.forEach(move => {
                const row = document.createElement('tr');
                
                // Format timestamp
                const date = new Date(move.timestamp);
                const timeString = date.toLocaleTimeString([], { 
                    hour: '2-digit', 
                    minute: '2-digit',
                    second: '2-digit'
                });
                
                // Status indicator
                const statusIcon = move.status === 'executed' ? 
                    '<i class="fas fa-check" style="color:#28a745"></i>' :
                    '<i class="fas fa-times" style="color:#dc3545"></i>';
                
                row.innerHTML = `
                    <td class="log-time">${timeString}</td>
                    <td>${move.command}</td>
                    <td>${move.position[0].toFixed(1)}, ${move.position[1].toFixed(1)}</td>
                    <td>${Math.round(move.heading)}°</td>
                    <td>${statusIcon}</td>
                `;
                
                logBody.appendChild(row);
            });
        }
    } catch (error) {
        console.error('Movement log load failed:', error);
    }
}

function addToLog(move) {
    const logBody = document.getElementById('logBody');
    
    // Remove placeholder if present
    if (logBody.children.length === 1 && logBody.children[0].colSpan) {
        logBody.innerHTML = '';
    }
    
    const row = document.createElement('tr');
    const date = new Date(move.timestamp);
    const timeString = date.toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit',
        second: '2-digit'
    });
    
    row.innerHTML = `
        <td class="log-time">${timeString}</td>
        <td>${move.command}</td>
        <td>${move.position[0].toFixed(1)}, ${move.position[1].toFixed(1)}</td>
        <td>${Math.round(move.heading)}°</td>
        <td><i class="fas fa-check" style="color:#28a745"></i></td>
    `;
    
    // Add at the beginning
    logBody.insertBefore(row, logBody.firstChild);
    
    // Keep only 10 entries
    if (logBody.children.length > 10) {
        logBody.removeChild(logBody.lastChild);
    }
}

function clearLog() {
    if (confirm('Clear all movement logs?')) {
        const logBody = document.getElementById('logBody');
        logBody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted" style="padding: 40px;">
                    No movements recorded yet
                </td>
            </tr>
        `;
        showNotification('Movement log cleared', 'info');
    }
}

// Helper Functions
function updateConnectionStatus(connected) {
    const dot = document.getElementById('connectionDot');
    const text = document.getElementById('connectionStatusText');
    const btn = document.getElementById('connectBtn');
    
    if (connected) {
        dot.className = 'status-indicator connected';
        dot.style.animation = 'none';
        text.textContent = 'Connected';
        btn.innerHTML = '<i class="fas fa-check"></i> Connected';
        btn.disabled = true;
    } else {
        dot.className = 'status-indicator';
        dot.style.animation = 'pulse 2s infinite';
        text.textContent = 'Disconnected';
        btn.innerHTML = '<i class="fas fa-link"></i> Connect Robot';
        btn.disabled = false;
    }
}

function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelectorAll('.notification');
    existing.forEach(n => {
        n.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => n.remove(), 300);
    });
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = 'notification';
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 20px;
        background: white;
        border-radius: 10px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        z-index: 10000;
        animation: slideIn 0.3s ease;
        display: flex;
        align-items: center;
        gap: 12px;
        border-left: 4px solid;
        max-width: 350px;
    `;
    
    // Set border color based on type
    const colors = {
        'success': '#28a745',
        'error': '#dc3545',
        'warning': '#ffc107',
        'info': '#17a2b8'
    };
    notification.style.borderLeftColor = colors[type] || colors.info;
    
    const icons = {
        'success': 'check-circle',
        'error': 'exclamation-circle',
        'warning': 'exclamation-triangle',
        'info': 'info-circle'
    };
    
    notification.innerHTML = `
        <i class="fas fa-${icons[type] || 'info-circle'}" 
           style="color: ${colors[type] || colors.info}; font-size: 18px;"></i>
        <div style="flex: 1;">
            <div style="font-size: 13px; font-weight: 600; margin-bottom: 2px; color: #333;">
                ${type.charAt(0).toUpperCase() + type.slice(1)}
            </div>
            <div style="font-size: 14px; color: #555;">${message}</div>
        </div>
        <button onclick="this.parentElement.remove()" 
                style="background:none; border:none; color:#999; cursor:pointer; padding:4px;">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.style.animation = 'slideOut 0.3s ease forwards';
            setTimeout(() => notification.remove(), 300);
        }
    }, 5000);
}

// Add animation styles
const style = document.createElement('style');
style.textContent = `
@keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}

@keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
}

.pulse {
    animation: pulse 0.3s ease;
}

@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(0.95); }
    100% { transform: scale(1); }
}
`;
document.head.appendChild(style);

// Modal Functions
function closeModal() {
    document.getElementById('snapshotModal').style.display = 'none';
}

// Keyboard Controls
function setupKeyboardControls() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        switch(e.key.toLowerCase()) {
            case 'w': case 'arrowup':
                sendCommand('forward');
                e.preventDefault();
                break;
            case 's': case 'arrowdown':
                sendCommand('backward');
                e.preventDefault();
                break;
            case 'a': case 'arrowleft':
                sendCommand('left');
                e.preventDefault();
                break;
            case 'd': case 'arrowright':
                sendCommand('right');
                e.preventDefault();
                break;
            case 'q':
                sendCommand('smooth_left');
                e.preventDefault();
                break;
            case 'e':
                sendCommand('smooth_right');
                e.preventDefault();
                break;
            case ' ':
                sendCommand('stop');
                e.preventDefault();
                break;
            case 'escape':
                disconnectRobot();
                break;
            case 'f':
                toggleFullscreen();
                break;
        }
    });
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('snapshotModal');
    if (event.target === modal) {
        closeModal();
    }
};

// Make functions available globally
window.connectRobot = connectRobot;
window.disconnectRobot = disconnectRobot;
window.sendCommand = sendCommand;
window.navigateToTarget = navigateToTarget;
window.exploreRoom = exploreRoom;
window.toggleStream = toggleStream;
window.takeSnapshot = takeSnapshot;
window.updateMap = updateMap;
window.closeModal = closeModal;
window.clearLog = clearLog;