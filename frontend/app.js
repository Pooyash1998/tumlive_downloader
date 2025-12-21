const API_BASE = 'http://127.0.0.1:5001/api';

let courses = [];
let lectures = [];
let selectedLectures = new Set();
let currentCourse = null;
let sortAscending = true;

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
        document.getElementById('outputDir').title = config.outputDir; // Show full path in tooltip
        
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
    
    // Navigation
    document.getElementById('backToCourses').addEventListener('click', showCourseSelection);
    
    // Browse folder
    document.getElementById('browseBtn').addEventListener('click', handleBrowseFolder);
    
    // Download dialog
    document.getElementById('closeDownloadDialog').addEventListener('click', closeDownloadDialog);
    
    // Logout
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    
    // Download
    document.getElementById('downloadBtn').addEventListener('click', handleDownload);
    
    // Select all
    document.getElementById('selectAll').addEventListener('change', handleSelectAll);
    
    // Filters
    document.getElementById('weekFilter').addEventListener('change', filterLectures);
    document.getElementById('dayFilter').addEventListener('change', filterLectures);
    document.getElementById('cameraFilter').addEventListener('change', filterLectures);
    document.getElementById('groupBy').addEventListener('change', filterLectures);
    
    // Sort toggle
    document.getElementById('sortButton').addEventListener('click', toggleSort);
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
    
    // Show loading overlay for initial data fetch
    showLoading(true, 'Signing in and loading course data...');
    
    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showMainPage();
            await loadCourses();
        } else {
            showStatus('loginStatus', data.error || 'Login failed', 'error');
            loginBtn.disabled = false;
            loginBtn.textContent = 'Sign In';
        }
    } catch (error) {
        showStatus('loginStatus', 'Connection error. Please try again.', 'error');
        loginBtn.disabled = false;
        loginBtn.textContent = 'Sign In';
    } finally {
        showLoading(false);
    }
}

// Handle continue with saved credentials
async function handleContinueLogin() {
    const continueBtn = document.getElementById('continueBtn');
    continueBtn.disabled = true;
    continueBtn.textContent = 'Signing in...';
    
    // Show loading overlay for initial data fetch
    showLoading(true, 'Signing in and loading course data...');
    
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
            await loadCourses();
        } else {
            showStatus('loginStatus', data.error || 'Login failed', 'error');
            continueBtn.disabled = false;
            continueBtn.textContent = 'Continue';
        }
    } catch (error) {
        showStatus('loginStatus', 'Connection error. Please try again.', 'error');
        continueBtn.disabled = false;
        continueBtn.textContent = 'Continue';
    } finally {
        showLoading(false);
    }
}

// Show main page
function showMainPage() {
    document.getElementById('loginPage').classList.remove('active');
    document.getElementById('mainPage').classList.add('active');
}

// Show course selection
function showCourseSelection() {
    document.getElementById('courseSelection').style.display = 'flex';
    document.getElementById('lecturesSection').style.display = 'none';
    currentCourse = null;
    
    // Reset selections when going back to course selection
    selectedLectures.clear();
    updateSelectAllState();
}

// Show lectures for selected course
function showLecturesSection(courseName) {
    document.getElementById('courseSelection').style.display = 'none';
    document.getElementById('lecturesSection').style.display = 'flex';
    document.getElementById('selectedCourseName').textContent = courseName;
    currentCourse = courseName;
    
    // Reset selections when switching to a new course
    selectedLectures.clear();
    updateSelectAllState();
}

// Load courses
async function loadCourses() {
    document.getElementById('coursesStatus').textContent = 'Loading courses...';
    
    try {
        const response = await fetch(`${API_BASE}/courses`);
        const data = await response.json();
        
        if (response.ok) {
            courses = data.courses;
            populateCourses(courses);
            document.getElementById('coursesStatus').textContent = `${courses.length} courses found`;
        } else {
            document.getElementById('coursesStatus').textContent = 'Error loading courses';
        }
    } catch (error) {
        document.getElementById('coursesStatus').textContent = 'Error loading courses';
    }
}

// Populate courses grid
function populateCourses(courseList) {
    const container = document.getElementById('coursesGrid');
    container.innerHTML = '';
    
    courseList.forEach(course => {
        const card = document.createElement('div');
        card.className = 'course-card';
        card.innerHTML = `
            <h3>${course.name}</h3>
            <p>Click to view lectures</p>
        `;
        
        card.addEventListener('click', () => {
            loadCourseLectures(course.name);
        });
        
        container.appendChild(card);
    });
}

// Load lectures for specific course
async function loadCourseLectures(courseName) {
    showLecturesSection(courseName);
    
    try {
        const response = await fetch(`${API_BASE}/lectures/${encodeURIComponent(courseName)}`);
        const data = await response.json();
        
        if (response.ok) {
            lectures = data.lectures;
            populateFilters(lectures);
            filterLectures(); // This will populate the lectures list
            document.getElementById('lecturesStatus').textContent = `${lectures.length} lectures found`;
        } else {
            document.getElementById('lecturesStatus').textContent = 'Error loading lectures';
        }
    } catch (error) {
        document.getElementById('lecturesStatus').textContent = 'Error loading lectures';
    }
}

// Handle browse folder
async function handleBrowseFolder() {
    const browseBtn = document.getElementById('browseBtn');
    const originalText = browseBtn.textContent;
    
    try {
        browseBtn.disabled = true;
        browseBtn.textContent = 'Opening...';
        
        const response = await fetch(`${API_BASE}/browse-folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (response.ok && data.success && data.path) {
            const outputDirInput = document.getElementById('outputDir');
            outputDirInput.value = data.path;
            outputDirInput.title = data.path; // Show full path in tooltip
            showStatus('downloadStatus', 'Output directory updated', 'success');
        } else {
            console.log('Folder selection cancelled:', data.message || data.error);
            if (data.error) {
                showStatus('downloadStatus', `Browser error: ${data.error}`, 'error');
            }
        }
    } catch (error) {
        console.error('Error browsing folder:', error);
        showStatus('downloadStatus', 'Error opening folder browser', 'error');
    } finally {
        browseBtn.disabled = false;
        browseBtn.textContent = originalText;
    }
}

// Toggle sort order
function toggleSort() {
    sortAscending = !sortAscending;
    const sortButton = document.getElementById('sortButton');
    const sortIcon = sortButton.querySelector('.sort-text');
    
    if (sortAscending) {
        sortButton.classList.remove('desc');
        sortIcon.textContent = 'Asc';
    } else {
        sortButton.classList.add('desc');
        sortIcon.textContent = 'Desc';
    }
    
    // Re-render lectures with new sort order
    filterLectures();
}

// Populate lectures list
function populateLectures(lectureList) {
    const container = document.getElementById('lecturesContent');
    container.innerHTML = '';
    
    const groupBy = document.getElementById('groupBy').value;
    const sortToggle = document.getElementById('sortToggle');
    
    // Always show sort toggle
    sortToggle.style.display = 'flex';
    
    if (groupBy) {
        // Group lectures
        const groups = {};
        lectureList.forEach(lecture => {
            const groupKey = groupBy === 'week' ? lecture.week : lecture.weekday;
            if (!groups[groupKey]) {
                groups[groupKey] = [];
            }
            groups[groupKey].push(lecture);
        });
        
        // Sort groups
        const sortedGroups = Object.keys(groups).sort((a, b) => {
            let comparison;
            if (groupBy === 'week') {
                comparison = parseInt(a.replace(/\D/g, '')) - parseInt(b.replace(/\D/g, ''));
            } else {
                const dayOrder = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
                comparison = dayOrder.indexOf(a) - dayOrder.indexOf(b);
            }
            return sortAscending ? comparison : -comparison;
        });
        
        // Render grouped lectures
        sortedGroups.forEach(groupKey => {
            if (groups[groupKey].length === 0) return;
            
            const groupDiv = document.createElement('div');
            groupDiv.className = 'lecture-group';
            
            const groupHeader = document.createElement('div');
            groupHeader.className = 'lecture-group-header';
            groupHeader.innerHTML = `
                <span>${groupKey}</span>
                <span class="toggle-icon">▶</span>
            `;
            
            const groupContent = document.createElement('div');
            groupContent.className = 'lecture-group-content';
            
            // Add click handler for toggle
            groupHeader.addEventListener('click', () => {
                const isExpanded = groupContent.classList.contains('expanded');
                if (isExpanded) {
                    groupContent.classList.remove('expanded');
                    groupHeader.classList.remove('expanded');
                } else {
                    groupContent.classList.add('expanded');
                    groupHeader.classList.add('expanded');
                }
            });
            
            // Sort lectures within each group
            const sortedLectures = groups[groupKey].sort((a, b) => {
                const comparison = new Date(a.date + ' ' + a.time) - new Date(b.date + ' ' + b.time);
                return sortAscending ? comparison : -comparison;
            });
            
            sortedLectures.forEach(lecture => {
                groupContent.appendChild(createLectureItem(lecture));
            });
            
            groupDiv.appendChild(groupHeader);
            groupDiv.appendChild(groupContent);
            container.appendChild(groupDiv);
        });
    } else {
        // No grouping - show all lectures sorted by date/time
        const sortedLectures = lectureList.sort((a, b) => {
            const comparison = new Date(a.date + ' ' + a.time) - new Date(b.date + ' ' + b.time);
            return sortAscending ? comparison : -comparison;
        });
        
        sortedLectures.forEach(lecture => {
            container.appendChild(createLectureItem(lecture));
        });
    }
}

// Create individual lecture item
function createLectureItem(lecture) {
    const item = document.createElement('div');
    item.className = 'lecture-item';
    item.dataset.id = lecture.id;
    item.dataset.camera = lecture.cameraType;
    item.dataset.week = lecture.week || '';
    item.dataset.day = lecture.weekday || '';
    
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
    if (lecture.week) details.push(lecture.week);
    if (lecture.weekday) details.push(lecture.weekday);
    if (dateDisplay) details.push(dateDisplay);
    if (lecture.time) details.push(lecture.time);
    
    item.innerHTML = `
        <input type="checkbox" id="lecture-${lecture.id}" data-id="${lecture.id}">
        <div class="lecture-info">
            <div class="lecture-name">${lecture.title}</div>
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
    
    return item;
}

// Populate filters
function populateFilters(lectureList) {
    populateWeekFilter(lectureList);
    populateDayFilter(lectureList);
}

// Populate week filter
function populateWeekFilter(lectureList) {
    const filter = document.getElementById('weekFilter');
    const weeks = [...new Set(lectureList.map(l => l.week).filter(w => w))].sort((a, b) => {
        const aNum = parseInt(a.replace(/\D/g, ''));
        const bNum = parseInt(b.replace(/\D/g, ''));
        return aNum - bNum;
    });
    
    filter.innerHTML = '<option value="">All Weeks</option>';
    weeks.forEach(week => {
        const option = document.createElement('option');
        option.value = week;
        option.textContent = week;
        filter.appendChild(option);
    });
}

// Populate day filter
function populateDayFilter(lectureList) {
    const filter = document.getElementById('dayFilter');
    const daysOrder = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const days = [...new Set(lectureList.map(l => l.weekday).filter(d => d))].sort((a, b) => {
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
    const weekFilter = document.getElementById('weekFilter').value;
    const dayFilter = document.getElementById('dayFilter').value;
    const cameraFilter = document.getElementById('cameraFilter').value;
    
    const filtered = lectures.filter(lecture => {
        const matchesWeek = !weekFilter || lecture.week === weekFilter;
        const matchesDay = !dayFilter || lecture.weekday === dayFilter;
        const matchesCamera = !cameraFilter || lecture.cameraType === cameraFilter;
        return matchesWeek && matchesDay && matchesCamera;
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
    
    if (!currentCourse) {
        showStatus('downloadStatus', 'No course selected', 'error');
        return;
    }
    
    const outputDir = document.getElementById('outputDir').value;
    const maxParallelDownloads = parseInt(document.getElementById('maxParallelDownloads').value) || 3;
    
    // Reconstruct the lectures structure grouped by stream type
    const lecturesByStreamType = {};
    const streamTypes = new Set();
    
    selectedLectures.forEach(lecture => {
        const streamType = lecture.cameraType;
        streamTypes.add(streamType);
        
        if (!lecturesByStreamType[streamType]) {
            lecturesByStreamType[streamType] = {};
        }
        
        if (!lecturesByStreamType[streamType][currentCourse]) {
            lecturesByStreamType[streamType][currentCourse] = [];
        }
        
        // Reconstruct the original lecture object structure
        lecturesByStreamType[streamType][currentCourse].push({
            "id": lecture.lectureId,
            "url": lecture.url,
            "title": lecture.title,
            "date": lecture.date,
            "time": lecture.time,
            "weekday": lecture.weekday,
            "week": lecture.week,
            "stream_type": streamType
        });
    });
    
    // Show download dialog
    showDownloadDialog(currentCourse, Array.from(streamTypes), selectedLectures.size);
    
    try {
        const response = await fetch(`${API_BASE}/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                courseName: currentCourse,
                lecturesByStreamType: lecturesByStreamType,
                outputDir: outputDir,
                maxParallelDownloads: maxParallelDownloads
            })
        });
        
        if (response.ok) {
            pollDownloadStatusDialog();
        } else {
            const data = await response.json();
            addDownloadLog(`Error: ${data.error || 'Download failed'}`, 'error');
        }
    } catch (error) {
        addDownloadLog(`Connection error: ${error.message}`, 'error');
    }
}

// Show download dialog
function showDownloadDialog(courseName, streamTypes, lectureCount) {
    document.getElementById('downloadCourse').textContent = courseName;
    document.getElementById('downloadStreamTypes').textContent = 
        `${lectureCount} lectures • Stream types: ${streamTypes.join(', ')}`;
    
    // Reset progress
    document.getElementById('dialogProgressFill').style.width = '0%';
    document.getElementById('dialogProgressText').textContent = '0%';
    document.getElementById('dialogProgressMessage').textContent = 'Preparing downloads...';
    document.getElementById('downloadLogs').innerHTML = '';
    
    document.getElementById('downloadDialog').style.display = 'flex';
    addDownloadLog('Download started...', 'success');
}

// Close download dialog
function closeDownloadDialog() {
    document.getElementById('downloadDialog').style.display = 'none';
}

// Add log entry to download dialog
function addDownloadLog(message, type = '') {
    const logsContainer = document.getElementById('downloadLogs');
    const logEntry = document.createElement('div');
    logEntry.className = `download-log-entry ${type}`;
    logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    logsContainer.appendChild(logEntry);
    logsContainer.scrollTop = logsContainer.scrollHeight;
}

// Poll download status for dialog
async function pollDownloadStatusDialog() {
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/download/progress`);
            const data = await response.json();
            
            const overall = data.overall;
            const lectures = data.lectures;
            
            // Update overall progress bar
            document.getElementById('dialogProgressFill').style.width = `${overall.progress}%`;
            document.getElementById('dialogProgressText').textContent = `${overall.progress}%`;
            document.getElementById('dialogProgressMessage').textContent = overall.message;
            
            // Update individual lecture progress bars
            updateLectureProgress(lectures);
            
            // Add log entry for significant progress updates
            if (overall.message.includes('Downloaded') || overall.message.includes('Getting playlist')) {
                addDownloadLog(overall.message, 'info');
            }
            
            if (overall.status === 'completed') {
                clearInterval(interval);
                addDownloadLog('All downloads completed successfully!', 'success');
                document.getElementById('dialogProgressMessage').textContent = 'Downloads completed!';
                
                // Auto-close dialog after 3 seconds
                setTimeout(() => {
                    closeDownloadDialog();
                }, 3000);
                
            } else if (overall.status === 'error') {
                clearInterval(interval);
                addDownloadLog(`Download failed: ${overall.message}`, 'error');
                document.getElementById('dialogProgressMessage').textContent = 'Download failed';
            }
        } catch (error) {
            clearInterval(interval);
            addDownloadLog('Error checking download status', 'error');
        }
    }, 2000);  // Check every 2 seconds
}

// Update individual lecture progress
function updateLectureProgress(lectures) {
    const logsContainer = document.getElementById('downloadLogs');
    
    // Clear and rebuild progress bars
    logsContainer.innerHTML = '';
    
    Object.entries(lectures).forEach(([pid, lecture]) => {
        const progressItem = document.createElement('div');
        progressItem.className = 'lecture-progress-item';
        progressItem.innerHTML = `
            <div class="lecture-progress-header">
                <div class="lecture-name" title="${lecture.name}">${lecture.name}</div>
                <div class="lecture-percentage">${lecture.progress}%</div>
            </div>
            <div class="lecture-progress-bar">
                <div class="lecture-progress-fill" style="width: ${lecture.progress}%"></div>
            </div>
            <div class="lecture-status">${lecture.message}</div>
        `;
        logsContainer.appendChild(progressItem);
    });
}

// Add log entry to download console
function addDownloadLog(message, type = '') {
    const consoleContainer = document.getElementById('downloadConsole');
    const logEntry = document.createElement('div');
    logEntry.className = `download-log-entry ${type}`;
    logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    consoleContainer.appendChild(logEntry);
    consoleContainer.scrollTop = consoleContainer.scrollHeight;
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
    
    // Reset state
    courses = [];
    lectures = [];
    selectedLectures.clear();
    currentCourse = null;
    sortAscending = true;
    
    // Reset navigation
    showCourseSelection();
    
    // Reset login button states
    const loginBtn = document.getElementById('loginBtn');
    const continueBtn = document.getElementById('continueBtn');
    
    if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.textContent = 'Sign In';
    }
    
    if (continueBtn) {
        continueBtn.disabled = false;
        continueBtn.textContent = 'Continue';
    }
    
    // Clear any status messages
    const loginStatus = document.getElementById('loginStatus');
    if (loginStatus) {
        loginStatus.style.display = 'none';
        loginStatus.textContent = '';
    }
    
    // Reset sort button
    const sortButton = document.getElementById('sortButton');
    if (sortButton) {
        sortButton.classList.remove('desc');
        sortButton.querySelector('.sort-text').textContent = 'Asc';
    }
}

// Show loading overlay
function showLoading(show, message = 'Loading Lectures') {
    const overlay = document.getElementById('loadingOverlay');
    if (show) {
        document.querySelector('.loading-content h3').textContent = message;
        document.querySelector('.loading-content p').textContent = 'Please wait...';
        overlay.style.display = 'flex';
    } else {
        overlay.style.display = 'none';
    }
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