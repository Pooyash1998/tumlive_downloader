const API_BASE = 'http://127.0.0.1:5001/api';

let lectures = [];
let selectedLectures = new Set();

// Initialize app
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    setupEventListeners();
});

// Load configuration
async function loadConfig() {
    try {
        const response = await fetch(`${API_BASE}/config`);
        const config = await response.json();
        
        if (config.hasCredentials) {
            document.getElementById('savedUsername').textContent = config.username;
            document.getElementById('userAvatar').textContent = config.username[0].toUpperCase();
            document.getElementById('savedUserCard').style.display = 'block';
            document.getElementById('manualLoginForm').style.display = 'none';
            document.getElementById('username').value = config.username;
        } else {
            document.getElementById('savedUserCard').style.display = 'none';
            document.getElementById('manualLoginForm').style.display = 'block';
        }
        
        document.getElementById('outputDir').value = config.outputDir;
        
        // Set max parallel downloads
        const maxDownloads = config.maxDownloads || 3;
        document.getElementById('maxParallelSlider').value = maxDownloads;
        document.getElementById('maxParallelDownloads').value = maxDownloads;
        
    } catch (error) {
        console.error('Failed to load config:', error);
        // Show manual login form if config fails
        document.getElementById('savedUserCard').style.display = 'none';
        document.getElementById('manualLoginForm').style.display = 'block';
    }
}

// Setup event listeners
function setupEventListeners() {
    // Login
    document.getElementById('loginBtn').addEventListener('click', handleLogin);
    document.getElementById('continueBtn')?.addEventListener('click', handleContinueLogin);
    document.getElementById('password').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleLogin();
    });
    
    // Toggle between saved and manual login
    document.getElementById('useOtherAccountBtn')?.addEventListener('click', showManualLogin);
    document.getElementById('backToSavedBtn')?.addEventListener('click', showSavedLogin);
    
    // Max parallel downloads sync
    const slider = document.getElementById('maxParallelSlider');
    const numberInput = document.getElementById('maxParallelDownloads');
    
    slider?.addEventListener('input', (e) => {
        numberInput.value = e.target.value;
    });
    
    numberInput?.addEventListener('input', (e) => {
        const value = Math.min(16, Math.max(1, parseInt(e.target.value) || 1));
        e.target.value = value;
        slider.value = value;
    });
    
    // Logout
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    
    // Download
    document.getElementById('downloadBtn').addEventListener('click', handleDownload);
    
    // Select all
    document.getElementById('selectAll').addEventListener('change', handleSelectAll);
    
    // Filters
    document.getElementById('courseFilter').addEventListener('change', filterLectures);
    document.getElementById('weekFilter').addEventListener('change', filterLectures);
    document.getElementById('dayFilter').addEventListener('change', filterLectures);
    document.getElementById('cameraFilter').addEventListener('change', filterLectures);
}

// Show manual login form
function showManualLogin() {
    document.getElementById('savedUserCard').style.display = 'none';
    document.getElementById('manualLoginForm').style.display = 'block';
    document.getElementById('backToSavedBtn').style.display = 'block';
    // Clear any previous values
    document.getElementById('username').value = '';
    document.getElementById('password').value = '';
    document.getElementById('username').focus();
}

// Show saved login form
function showSavedLogin() {
    document.getElementById('savedUserCard').style.display = 'block';
    document.getElementById('manualLoginForm').style.display = 'none';
    document.getElementById('backToSavedBtn').style.display = 'none';
}

// Handle login
async function handleLogin() {
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    
    if (!username || !password) {
        showStatus('loginStatus', 'Please enter both username and password', 'error');
        return;
    }
    
    const loginBtn = document.getElementById('loginBtn');
    loginBtn.disabled = true;
    loginBtn.textContent = 'Signing in...';
    
    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMainPage();
            await loadLectures();
        } else {
            showStatus('loginStatus', data.error || 'Login failed', 'error');
            loginBtn.disabled = false;
            loginBtn.textContent = 'Sign In';
        }
    } catch (error) {
        showStatus('loginStatus', 'Connection error. Please try again.', 'error');
        loginBtn.disabled = false;
        loginBtn.textContent = 'Sign In';
    }
}

// Handle continue with saved credentials
async function handleContinueLogin() {
    const continueBtn = document.getElementById('continueBtn');
    continueBtn.disabled = true;
    continueBtn.textContent = 'Signing in...';
    
    try {
        // Get saved credentials from config
        const configResponse = await fetch(`${API_BASE}/config`);
        const config = await configResponse.json();
        
        if (!config.hasCredentials) {
            showStatus('loginStatus', 'No saved credentials found', 'error');
            continueBtn.disabled = false;
            continueBtn.textContent = 'Continue';
            return;
        }
        
        // Use the saved username and get password from backend
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                username: config.username,
                useSavedPassword: true 
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMainPage();
            await loadLectures();
        } else {
            showStatus('loginStatus', data.error || 'Login failed', 'error');
            continueBtn.disabled = false;
            continueBtn.textContent = 'Continue';
        }
    } catch (error) {
        showStatus('loginStatus', 'Connection error. Please try again.', 'error');
        continueBtn.disabled = false;
        continueBtn.textContent = 'Continue';
    }
}

// Show main page
function showMainPage() {
    document.getElementById('loginPage').classList.remove('active');
    document.getElementById('mainPage').classList.add('active');
}

// Load lectures
async function loadLectures() {
    showLoading(true);
    
    try {
        const response = await fetch(`${API_BASE}/lectures`);
        const data = await response.json();
        
        if (response.ok) {
            lectures = data.lectures;
            populateLectures(lectures);
            populateCourseFilter(lectures);
            populateWeekFilter(lectures);
            populateDayFilter(lectures);
            document.getElementById('lecturesStatus').textContent = `${lectures.length} lectures found`;
        } else {
            document.getElementById('lecturesStatus').textContent = 'Error loading lectures';
        }
    } catch (error) {
        document.getElementById('lecturesStatus').textContent = 'Error loading lectures';
    } finally {
        showLoading(false);
    }
}

// Populate lectures list
function populateLectures(lectureList) {
    const container = document.getElementById('lecturesList');
    container.innerHTML = '';
    
    lectureList.forEach(lecture => {
        const item = document.createElement('div');
        item.className = 'lecture-item';
        item.dataset.id = lecture.id;
        item.dataset.course = lecture.courseName;
        item.dataset.camera = lecture.cameraType;
        item.dataset.week = lecture.weekNumber || '';
        item.dataset.day = lecture.dayOfWeek || '';
        
        // Format date display
        let dateDisplay = '';
        if (lecture.date) {
            const date = new Date(lecture.date);
            dateDisplay = date.toLocaleDateString('en-US', { 
                month: 'short', 
                day: 'numeric',
                year: 'numeric'
            });
        }
        
        // Build details string
        let details = [];
        if (lecture.weekNumber) details.push(`Week ${lecture.weekNumber}`);
        if (lecture.dayOfWeek) details.push(lecture.dayOfWeek);
        if (dateDisplay) details.push(dateDisplay);
        if (lecture.duration) details.push(lecture.duration);
        
        item.innerHTML = `
            <input type="checkbox" id="lecture-${lecture.id}" data-id="${lecture.id}">
            <div class="lecture-info">
                <div class="lecture-name">${lecture.displayName}</div>
                <div class="lecture-details">
                    <span class="camera-badge ${lecture.cameraType.toLowerCase()}">${lecture.cameraType}</span>
                    ${details.length > 0 ? `<span class="lecture-meta">${details.join(' • ')}</span>` : ''}
                </div>
            </div>
        `;
        
        const checkbox = item.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedLectures.add(lecture);
            } else {
                selectedLectures.delete(lecture);
            }
            updateSelectAllState();
        });
        
        item.addEventListener('click', (e) => {
            if (e.target.tagName !== 'INPUT') {
                checkbox.checked = !checkbox.checked;
                checkbox.dispatchEvent(new Event('change'));
            }
        });
        
        container.appendChild(item);
    });
}

// Populate course filter
function populateCourseFilter(lectureList) {
    const filter = document.getElementById('courseFilter');
    const courses = [...new Set(lectureList.map(l => l.courseName))];
    
    filter.innerHTML = '<option value="">All Courses</option>';
    courses.forEach(course => {
        const option = document.createElement('option');
        option.value = course;
        option.textContent = course;
        filter.appendChild(option);
    });
}

// Populate week filter
function populateWeekFilter(lectureList) {
    const filter = document.getElementById('weekFilter');
    const weeks = [...new Set(lectureList.map(l => l.weekNumber).filter(w => w))].sort((a, b) => parseInt(a) - parseInt(b));
    
    filter.innerHTML = '<option value="">All Weeks</option>';
    weeks.forEach(week => {
        const option = document.createElement('option');
        option.value = week;
        option.textContent = `Week ${week}`;
        filter.appendChild(option);
    });
}

// Populate day filter
function populateDayFilter(lectureList) {
    const filter = document.getElementById('dayFilter');
    const daysOrder = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const days = [...new Set(lectureList.map(l => l.dayOfWeek).filter(d => d))].sort((a, b) => {
        return daysOrder.indexOf(a) - daysOrder.indexOf(b);
    });
    
    filter.innerHTML = '<option value="">All Days</option>';
    days.forEach(day => {
        const option = document.createElement('option');
        option.value = day;
        option.textContent = day;
        filter.appendChild(option);
    });
}

// Filter lectures
function filterLectures() {
    const courseFilter = document.getElementById('courseFilter').value;
    const weekFilter = document.getElementById('weekFilter').value;
    const dayFilter = document.getElementById('dayFilter').value;
    const cameraFilter = document.getElementById('cameraFilter').value;
    
    const filtered = lectures.filter(lecture => {
        const matchesCourse = !courseFilter || lecture.courseName === courseFilter;
        const matchesWeek = !weekFilter || lecture.weekNumber === weekFilter;
        const matchesDay = !dayFilter || lecture.dayOfWeek === dayFilter;
        const matchesCamera = !cameraFilter || lecture.cameraType === cameraFilter;
        return matchesCourse && matchesWeek && matchesDay && matchesCamera;
    });
    
    populateLectures(filtered);
}

// Handle select all
function handleSelectAll(e) {
    const checkboxes = document.querySelectorAll('.lecture-item input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = e.target.checked;
        const lectureId = cb.dataset.id;
        const lecture = lectures.find(l => l.id === lectureId);
        if (e.target.checked) {
            selectedLectures.add(lecture);
        } else {
            selectedLectures.delete(lecture);
        }
    });
}

// Update select all state
function updateSelectAllState() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.lecture-item input[type="checkbox"]');
    const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
    
    selectAll.checked = checkedCount === checkboxes.length && checkboxes.length > 0;
    selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
}

// Handle download
async function handleDownload() {
    if (selectedLectures.size === 0) {
        showStatus('downloadStatus', 'Please select at least one lecture', 'error');
        return;
    }
    
    const outputDir = document.getElementById('outputDir').value;
    const maxParallelDownloads = parseInt(document.getElementById('maxParallelDownloads').value) || 3;
    const downloadBtn = document.getElementById('downloadBtn');
    
    downloadBtn.disabled = true;
    downloadBtn.textContent = 'Downloading...';
    document.getElementById('downloadProgress').style.display = 'block';
    
    try {
        const response = await fetch(`${API_BASE}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lectures: Array.from(selectedLectures),
                outputDir: outputDir,
                maxParallelDownloads: maxParallelDownloads
            })
        });
        
        if (response.ok) {
            pollDownloadStatus();
        } else {
            const data = await response.json();
            showStatus('downloadStatus', data.error || 'Download failed', 'error');
            downloadBtn.disabled = false;
            downloadBtn.textContent = 'Download Selected';
            document.getElementById('downloadProgress').style.display = 'none';
        }
    } catch (error) {
        showStatus('downloadStatus', 'Connection error', 'error');
        downloadBtn.disabled = false;
        downloadBtn.textContent = 'Download Selected';
        document.getElementById('downloadProgress').style.display = 'none';
    }
}

// Poll download status
async function pollDownloadStatus() {
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/download/status`);
            const status = await response.json();
            
            document.getElementById('progressFill').style.width = `${status.progress}%`;
            document.getElementById('progressText').textContent = status.message;
            
            if (status.status === 'completed') {
                clearInterval(interval);
                showStatus('downloadStatus', 'Downloads completed successfully!', 'success');
                document.getElementById('downloadBtn').disabled = false;
                document.getElementById('downloadBtn').textContent = 'Download Selected';
                setTimeout(() => {
                    document.getElementById('downloadProgress').style.display = 'none';
                }, 3000);
            } else if (status.status === 'error') {
                clearInterval(interval);
                showStatus('downloadStatus', status.message, 'error');
                document.getElementById('downloadBtn').disabled = false;
                document.getElementById('downloadBtn').textContent = 'Download Selected';
            }
        } catch (error) {
            clearInterval(interval);
            showStatus('downloadStatus', 'Error checking download status', 'error');
            document.getElementById('downloadBtn').disabled = false;
            document.getElementById('downloadBtn').textContent = 'Download Selected';
        }
    }, 1000);
}

// Handle logout
async function handleLogout() {
    try {
        await fetch(`${API_BASE}/logout`, { method: 'POST' });
    } catch (error) {
        console.error('Logout error:', error);
    }
    
    document.getElementById('mainPage').classList.remove('active');
    document.getElementById('loginPage').classList.add('active');
    lectures = [];
    selectedLectures.clear();
}

// Show loading overlay
function showLoading(show) {
    document.getElementById('loadingOverlay').style.display = show ? 'flex' : 'none';
}

// Show status message
function showStatus(elementId, message, type) {
    const element = document.getElementById(elementId);
    element.textContent = message;
    element.className = `status-message ${type}`;
    element.style.display = 'block';
    
    if (type === 'success') {
        setTimeout(() => {
            element.style.display = 'none';
        }, 5000);
    }
}