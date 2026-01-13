const API_BASE = '/api';

// State
const state = {
    semesters: [],
    courses: [],
    materials: [],
    logsInterval: null,
    isProcessing: false
};

// DOM Elements
const views = {
    dashboard: document.getElementById('dashboard-view'),
    semesters: document.getElementById('semesters-view'),
    logs: document.getElementById('logs-view')
};

const containers = {
    semesterList: document.getElementById('semester-list'),
    courseList: document.getElementById('course-list'),
    materialList: document.getElementById('material-list'),
    logsOutput: document.getElementById('logs-output')
};

const columns = {
    course: document.getElementById('course-list-col'),
    material: document.getElementById('material-list-col')
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initTheme();

    // Auto login/init
    checkAuth();

    // Settings listener
    const maxTabsInput = document.getElementById('max-tabs-input');
    if (maxTabsInput) {
        maxTabsInput.addEventListener('change', async (e) => {
            const val = parseInt(e.target.value);
            if (val > 0) {
                try {
                    await fetch(`${API_BASE}/settings`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ max_concurrent_tasks: val })
                    });
                    showToast(`Max tabs set to ${val}`, 'success');
                } catch (e) {
                    showToast('Failed to update settings', 'error');
                }
            }
        });
    }
});

// Auth Flow
async function checkAuth() {
    showOverlay('Connecting to Synergy...', 'Secure handshake in progress');
    try {
        const res = await fetch(`${API_BASE}/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        if (res.ok) {
            hideOverlay();
            loadSemesters();
            startLogsPolling();
            showToast('Connected to Synergy LMS', 'success');
        } else {
            showOverlay('Connection Failed', 'Please check your .env credentials', true);
        }
    } catch (e) {
        showOverlay('Server Offline', 'Is the parser running?', true);
    }
}

// Data Fetching
async function loadSemesters() {
    renderLoading(containers.semesterList);
    try {
        const res = await fetch(`${API_BASE}/semesters`);
        const data = await res.json();
        state.semesters = data.semesters;
        document.getElementById('stat-semesters').innerText = state.semesters.length;
        renderSemesters();
    } catch (e) {
        console.error(e);
        showToast('Failed to load semesters', 'error');
    }
}

async function loadCourses(semesterId) {
    renderLoading(containers.courseList);
    columns.course.classList.remove('hidden');
    columns.material.classList.add('hidden'); // Hide materials when switching semester

    try {
        const res = await fetch(`${API_BASE}/courses/${semesterId}`);
        const data = await res.json();
        state.courses = data.courses;
        document.getElementById('stat-courses').innerText = state.courses.length;
        renderCourses(semesterId);
    } catch (e) {
        console.error(e);
        showToast('Failed to load courses', 'error');
    }
}

async function loadMaterials(course) {
    renderLoading(containers.materialList);
    columns.material.classList.remove('hidden');

    try {
        // encode URL might be needed
        const res = await fetch(`${API_BASE}/materials?course_url=${encodeURIComponent(course.url)}`);
        const data = await res.json();
        state.materials = data.flat;
        state.currentCourseUrl = course.url; // Save for context
        renderMaterials();
    } catch (e) {
        console.error(e);
        showToast('Failed to load materials', 'error');
    }
}

async function processMaterial(material) {
    const btn = document.getElementById(`btn-${material.data_index || material.url}`);

    // Optimistic UI update
    if (btn) btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    try {
        const res = await fetch(`${API_BASE}/process_material`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                material_url: material.url,
                material_name: material.name,
                material_type: material.type || 'material',
                course_url: state.currentCourseUrl // Pass context
            })
        });

        const data = await res.json();

        if (res.ok) {
            showToast(`Task started: ${material.name}`, 'info');
            // Don't switch to logs anymore!
            // Start polling tasks if not already
            startTaskPolling();
        } else {
            showToast('Failed to start task', 'error');
            if (btn) btn.innerHTML = '<i class="fa-solid fa-play"></i>';
        }
    } catch (e) {
        showToast('Error sending task', 'error');
        if (btn) btn.innerHTML = '<i class="fa-solid fa-play"></i>';
    }
}

// Rendering
function renderSemesters() {
    containers.semesterList.innerHTML = '';
    state.semesters.forEach(sem => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
            <div class="item-title">Semester ${sem}</div>
            <div class="item-meta">Standard Curriculum</div>
        `;
        item.onclick = () => {
            document.querySelectorAll('#semester-list .list-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
            loadCourses(sem);
        };
        containers.semesterList.appendChild(item);
    });
}

function renderCourses(semesterId) {
    containers.courseList.innerHTML = '';

    // Header for Batch Actions
    const header = document.createElement('div');
    header.style.padding = '0 10px 10px 10px';
    header.style.display = 'flex';
    header.style.justifyContent = 'space-between';
    header.innerHTML = `
        <div style="font-size:12px; color:var(--text-muted)">
            <label style="cursor:pointer; display:flex; align-items:center; gap:8px">
                <input type="checkbox" id="select-all-courses"> Select All
            </label>
        </div>
        <button id="process-selected-courses-btn" class="btn btn-secondary" style="font-size:12px; padding:4px 12px; display:none">
            <i class="fa-solid fa-play"></i> Process Selected (<span id="selected-courses-count">0</span>)
        </button>
    `;
    containers.courseList.appendChild(header);

    // Event listener for Select All
    header.querySelector('#select-all-courses').addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('.course-checkbox');
        checkboxes.forEach(cb => cb.checked = e.target.checked);
        updateCourseBatchUI();
    });

    header.querySelector('#process-selected-courses-btn').addEventListener('click', () => {
        processSelectedCourses();
    });

    state.courses.forEach(course => {
        const item = document.createElement('div');
        item.className = 'list-item course-item'; // Added course-item class

        item.innerHTML = `
            <div style="margin-right:12px; display:flex; align-items:center">
                <input type="checkbox" class="course-checkbox" data-url="${course.url}" data-name="${course.name}">
            </div>
            <div style="flex:1">
                <div class="item-title">${course.name}</div>
                <div class="item-meta">${course.control_type}</div>
            </div>
        `;

        const cb = item.querySelector('.course-checkbox');
        cb.addEventListener('change', updateCourseBatchUI);

        // Click on item loads materials (unless clicking checkbox)
        item.onclick = (e) => {
            if (e.target.tagName === 'INPUT') return;

            document.querySelectorAll('#course-list .list-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
            loadMaterials(course);
        };
        containers.courseList.appendChild(item);
    });
}

function updateCourseBatchUI() {
    const selected = document.querySelectorAll('.course-checkbox:checked').length;
    const btn = document.getElementById('process-selected-courses-btn');
    const countSpan = document.getElementById('selected-courses-count');

    if (selected > 0) {
        btn.style.display = 'inline-flex';
        countSpan.innerText = selected;
    } else {
        btn.style.display = 'none';
    }
}

async function processSelectedCourses() {
    const checkboxes = document.querySelectorAll('.course-checkbox:checked');
    if (checkboxes.length === 0) return;

    showToast(`Fetching materials for ${checkboxes.length} courses...`, 'info');
    const btn = document.getElementById('process-selected-courses-btn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Preparing...';
    btn.disabled = true;

    try {
        let totalQueued = 0;

        for (const cb of checkboxes) {
            const courseUrl = cb.getAttribute('data-url');
            const courseName = cb.getAttribute('data-name');

            // Fetch materials for this course
            // Re-using logic from loadMaterials but without rendering
            try {
                const res = await fetch(`${API_BASE}/materials?course_url=${encodeURIComponent(courseUrl)}`);
                const data = await res.json();

                // Queue all materials
                const materials = data.flat;
                if (materials && materials.length > 0) {
                    for (const mat of materials) {
                        if (!mat.is_blocked) {
                            // We need to pass course_url for context manually since state.currentCourseUrl might update
                            // Ideally processMaterial handles this. 
                            // NOTE: Our processMaterial uses state.currentCourseUrl. We should update that or pass it explicitly.
                            // Let's modify processMaterial slightly to prefer passed arg if available, or we update the object before sending.

                            // Construct a payload or temporarily mock state (risky async). 
                            // Better: sending material object with context.

                            // Let's ensure processMaterial takes course_url from the material object if we inject it.
                            mat.course_url = courseUrl;

                            // We call the API directly here to avoid UI flicker/state mess or reuse processMaterial?
                            // processMaterial updates UI buttons. We might not be looking at that course.
                            // So we should just hit the API directly for background processing.

                            await fetch(`${API_BASE}/process_material`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    material_url: mat.url,
                                    material_name: mat.name,
                                    material_type: mat.type || 'material',
                                    course_url: courseUrl
                                })
                            });
                            totalQueued++;
                        }
                    }
                }
            } catch (e) {
                console.error(`Failed to process course ${courseName}`, e);
            }
        }

        showToast(`Successfully queued ${totalQueued} tasks from ${checkboxes.length} courses.`, 'success');

        // Clear selection
        checkboxes.forEach(cb => cb.checked = false);
        updateCourseBatchUI();

        // Start polling if not already
        startTaskPolling();

    } catch (e) {
        showToast('Error processing courses', 'error');
        console.error(e);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function renderMaterials(course) {
    containers.materialList.innerHTML = '';

    // Header for Batch Actions
    const header = document.createElement('div');
    header.style.padding = '0 10px 10px 10px';
    header.style.display = 'flex';
    header.style.justifyContent = 'space-between';
    header.innerHTML = `
        <div style="font-size:12px; color:var(--text-muted)">
            <label style="cursor:pointer; display:flex; align-items:center; gap:8px">
                <input type="checkbox" id="select-all-mats"> Select All
            </label>
        </div>
        <button id="process-selected-btn" class="btn btn-secondary" style="font-size:12px; padding:4px 12px; display:none">
            <i class="fa-solid fa-play"></i> Process Selected (<span id="selected-count">0</span>)
        </button>
    `;
    containers.materialList.appendChild(header);

    // Event listener for Select All
    header.querySelector('#select-all-mats').addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('.mat-checkbox');
        checkboxes.forEach(cb => cb.checked = e.target.checked);
        updateBatchUI();
    });

    header.querySelector('#process-selected-btn').addEventListener('click', () => {
        processSelectedMaterials();
    });

    if (state.materials.length === 0) {
        containers.materialList.innerHTML += '<div style="padding:20px; color:var(--text-muted)">No accessible materials found.</div>';
        return;
    }

    state.materials.forEach(mat => {
        const item = document.createElement('div');
        item.className = 'list-item material-item';
        item.id = `mat-item-${btoa(mat.url).replace(/=/g, '')}`;

        // Icon based on type
        let icon = 'fa-file';
        if (mat.type === 'video') icon = 'fa-video';
        if (mat.type === 'test') icon = 'fa-list-check';
        if (mat.type === 'pdf') icon = 'fa-file-pdf';

        item.innerHTML = `
            <div style="margin-right:12px; display:flex; align-items:center">
                <input type="checkbox" class="mat-checkbox" data-url="${mat.url}" ${mat.is_blocked ? 'disabled' : ''}>
            </div>
            <div class="material-info" style="flex:1">
                <i class="fa-solid ${icon} material-icon"></i>
                <div style="width:100%">
                    <div class="item-title" style="font-size:14px">${mat.name}</div>
                    <div class="item-meta">
                        ${mat.type.toUpperCase()}
                        <span class="status-placeholder"></span>
                    </div>
                    <div class="progress-container hidden" style="display:none">
                        <div class="progress-bar" style="width:0%"></div>
                    </div>
                </div>
            </div>
            <div class="actions-area">
            ${!mat.is_blocked ?
                `<button id="btn-${mat.data_index || mat.url}" class="action-btn" title="Start Task">
                    <i class="fa-solid fa-play"></i>
                 </button>` :
                `<span style="color:#ef4444; font-size:12px"><i class="fa-solid fa-lock"></i> Blocked</span>`
            }
            </div>
        `;

        // Checkbox event
        const cb = item.querySelector('.mat-checkbox');
        cb.addEventListener('change', updateBatchUI);

        // Click on item toggles checkbox (unless blocked)
        item.onclick = (e) => {
            // Avoid double toggle if clicking directly on checkbox or button
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
            if (!mat.is_blocked) {
                cb.checked = !cb.checked;
                updateBatchUI();
            }
        };

        if (!mat.is_blocked) {
            item.querySelector('button').onclick = (e) => {
                e.stopPropagation();
                processMaterial(mat);
            };
        }

        containers.materialList.appendChild(item);
    });
}

function updateBatchUI() {
    const selected = document.querySelectorAll('.mat-checkbox:checked').length;
    const btn = document.getElementById('process-selected-btn');
    const countSpan = document.getElementById('selected-count');

    if (selected > 0) {
        btn.style.display = 'inline-flex';
        countSpan.innerText = selected;
    } else {
        btn.style.display = 'none';
    }
}

async function processSelectedMaterials() {
    const checkboxes = document.querySelectorAll('.mat-checkbox:checked');
    const total = checkboxes.length;

    if (total === 0) return;

    showToast(`Queueing ${total} tasks...`, 'info');

    // Find material objects
    const selectedMaterials = [];
    checkboxes.forEach(cb => {
        const url = cb.getAttribute('data-url');
        const mat = state.materials.find(m => m.url === url);
        if (mat) selectedMaterials.push(mat);
    });

    // Start them all
    for (const mat of selectedMaterials) {
        await processMaterial(mat);
    }

    // Clear selection
    checkboxes.forEach(cb => cb.checked = false);
    updateBatchUI();
}

function renderLoading(container) {
    container.innerHTML = '<div class="loading-spinner" style="padding:20px; color:var(--text-muted)"><i class="fa-solid fa-spinner fa-spin"></i> Loading data...</div>';
}

// Polling for Tasks & Logs
let taskInterval = null;

function startLogsPolling() {
    // Start log polling (less frequent)
    if (state.logsInterval) clearInterval(state.logsInterval);
    state.logsInterval = setInterval(async () => {
        if (!document.getElementById('logs-view').classList.contains('active')) return;
        try {
            const res = await fetch(`${API_BASE}/logs`);
            const data = await res.json();
            renderLogs(data.logs);
        } catch (e) {
            console.warn('Log polling error', e);
        }
    }, 2000);

    // Start task polling
    startTaskPolling();
}

function startTaskPolling() {
    if (taskInterval) return; // Already running

    taskInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/tasks`);
            const data = await res.json();
            updateTasksUI(data.tasks);
        } catch (e) {
            console.warn('Task polling error', e);
        }
    }, 1000); // Check every second
}


function updateTasksUI(tasks) {
    // 1. Update Global Indicator
    updateGlobalTaskIndicator(tasks);

    if (!tasks || tasks.length === 0) return;

    tasks.forEach(task => {
        // Find material element by name (simple fallback)
        const items = document.querySelectorAll('.material-item');
        items.forEach(item => {
            if (item.innerText.includes(task.material_name)) {
                const statusSpan = item.querySelector('.status-placeholder');
                const progContainer = item.querySelector('.progress-container');
                const progBar = item.querySelector('.progress-bar');
                const actionBtn = item.querySelector('.action-btn');

                // Update badge
                if (statusSpan) {
                    let badgeClass = 'running';
                    if (task.status === 'completed') badgeClass = 'completed';
                    if (task.status === 'failed') badgeClass = 'failed';
                    if (task.status === 'pending') badgeClass = 'pending'; // New state

                    let statusText = task.status;
                    if (task.status === 'running') statusText = 'Processing...';
                    if (task.status === 'pending') statusText = 'Queued';

                    statusSpan.innerHTML = `<span class="task-status-badge ${badgeClass}">${statusText} (${task.progress || 0}%)</span>`;
                }

                // Update Progress Bar
                if (progContainer && progBar) {
                    progContainer.style.display = 'block';
                    progBar.style.width = `${task.progress}%`;

                    if (task.status === 'pending') {
                        progBar.style.width = '100%';
                        progBar.style.background = 'rgba(255,255,255,0.1)';
                        progBar.className = 'progress-bar striped';
                    } else {
                        progBar.style.background = 'var(--primary)';
                        progBar.className = 'progress-bar';
                    }
                }
            }
        });
    });
}

function updateGlobalTaskIndicator(tasks) {
    let indicator = document.getElementById('global-task-indicator');

    const activeTasks = tasks.filter(t => t.status === 'running' || t.status === 'pending');

    if (activeTasks.length === 0) {
        if (indicator) indicator.classList.remove('visible');
        return;
    }

    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'global-task-indicator';
        indicator.className = 'active-tasks-panel';
        document.body.appendChild(indicator);
    }

    const running = tasks.filter(t => t.status === 'running').length;
    const pending = tasks.filter(t => t.status === 'pending').length;

    indicator.innerHTML = `
        <div style="font-weight:600; margin-bottom:8px; display:flex; justify-content:space-between">
            <span>Tasks Queue</span>
            <span style="font-size:10px; background:var(--bg-card-hover); padding:2px 6px; border-radius:4px">${running + pending} Active</span>
        </div>
        <div style="font-size:11px; opacity:0.8; margin-bottom:12px">
            <div><i class="fa-solid fa-bolt" style="color:var(--primary)"></i> Running: ${running}</div>
            <div><i class="fa-solid fa-clock" style="color:var(--text-muted)"></i> Queued: ${pending}</div>
        </div>
        <div class="task-mini-list" style="max-height:150px; overflow-y:auto">
            ${activeTasks.map(t => `
                <div class="task-mini-item">
                    <div style="display:flex; justify-content:space-between; margin-bottom:2px">
                        <span style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:80%">${t.material_name}</span>
                        <span>${t.progress}%</span>
                    </div>
                    <div style="height:2px; background:rgba(255,255,255,0.1); border-radius:1px; overflow:hidden">
                        <div style="height:100%; background:${t.status === 'pending' ? 'gray' : 'var(--primary)'}; width:${t.progress}%"></div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    indicator.classList.add('visible');
}

function renderLogs(logs) {
    const container = containers.logsOutput;
    // Simple diffing could be better, but for now just replace
    // Ideally append only new ones.

    container.innerHTML = logs.map(line => {
        let cls = '';
        if (line.includes('INFO')) cls = 'info';
        if (line.includes('ERROR')) cls = 'error';
        if (line.includes('WARNING')) cls = 'warning';
        return `<div class="log-line ${cls}">${line}</div>`;
    }).join('');

    if (document.getElementById('auto-scroll').checked) {
        container.scrollTop = container.scrollHeight;
    }
}

// Navigation & UI
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            // Remove active class
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

            // Add active
            item.classList.add('active');
            const tab = item.getAttribute('data-tab');
            document.getElementById(`${tab}-view`).classList.add('active');

            document.getElementById('page-title').innerText = item.querySelector('span').innerText;
        });
    });

    document.getElementById('relogin-btn').addEventListener('click', () => {
        checkAuth();
    });

    document.getElementById('clear-logs').addEventListener('click', () => {
        // Can't really clear server logs file easily safely, just clear UI
        containers.logsOutput.innerHTML = '';
    });
}

function switchToLogs() {
    document.querySelector('.nav-item[data-tab="logs"]').click();
}

function showOverlay(title, subtitle, isError = false) {
    const overlay = document.getElementById('overlay');
    document.getElementById('overlay-text').innerText = title;
    document.getElementById('overlay-subtext').innerText = subtitle;
    overlay.classList.add('visible');

    if (isError) {
        document.querySelector('.loader').style.display = 'none';
        document.getElementById('overlay-text').style.color = '#ef4444';
        // Click to close if error
        overlay.style.pointerEvents = 'all';
        overlay.onclick = () => hideOverlay();
    } else {
        document.querySelector('.loader').style.display = 'inline-block';
        document.getElementById('overlay-text').style.color = 'inherit';
        overlay.onclick = null;
    }
}

function hideOverlay() {
    document.getElementById('overlay').classList.remove('visible');
}

function showToast(msg, type = 'info') {
    // Simple toast
    const toast = document.createElement('div');
    toast.style.position = 'fixed';
    toast.style.bottom = '20px';
    toast.style.right = '20px';
    toast.style.padding = '12px 24px';
    toast.style.background = '#333';
    toast.style.color = '#fff';
    toast.style.borderRadius = '8px';
    toast.style.zIndex = '2000';
    toast.style.boxShadow = '0 5px 15px rgba(0,0,0,0.3)';
    toast.style.borderLeft = `4px solid ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#6366f1'}`;
    toast.innerText = msg;
    toast.style.animation = 'fadeIn 0.3s ease';

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function initTheme() {
    // Already premium dark by default
}
