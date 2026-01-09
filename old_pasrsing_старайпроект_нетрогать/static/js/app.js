// API Base URL
const API_BASE = '';

// State
let currentSemester = null;
let currentCourse = null;
let tasks = [];
let taskUpdateInterval = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    loadSemesters();
    setupEventListeners();
    startTaskPolling();
});

// Setup event listeners
function setupEventListeners() {
    document.getElementById('syncAll').addEventListener('click', syncAllData);
    document.getElementById('syncSemesters').addEventListener('click', syncSemesters);
    document.getElementById('syncCourses').addEventListener('click', () => syncCourses(currentSemester.id));
    document.getElementById('backToCourses').addEventListener('click', showCoursesView);
    document.getElementById('syncMaterials').addEventListener('click', () => syncMaterials(currentCourse.id));
    document.getElementById('autoCompleteCourse').addEventListener('click', () => autoCompleteCourse(currentCourse.id));
}

// API calls
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(API_BASE + endpoint, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        showError(error.message);
        throw error;
    }
}

// Load semesters
async function loadSemesters() {
    const container = document.getElementById('semestersList');
    container.innerHTML = '<div class="loading">Загрузка семестров...</div>';

    try {
        const semesters = await apiCall('/api/semesters');

        if (semesters.length === 0) {
            container.innerHTML = '<p class="empty-state">Нет семестров. Нажмите "Синхронизировать"</p>';
            return;
        }

        container.innerHTML = semesters.map(sem => `
            <div class="semester-item" data-id="${sem.id}" onclick="selectSemester(${sem.id})">
                <div class="semester-name">${sem.name}</div>
                <div class="semester-meta">${sem.courses_count} курсов</div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = '<p class="empty-state">Ошибка загрузки семестров</p>';
    }
}

// Sync all data (semesters, courses, materials)
async function syncAllData() {
    const btn = document.getElementById('syncAll');
    const status = document.getElementById('syncStatus');

    btn.disabled = true;
    status.textContent = '🚀 Полная синхронизация...';

    try {
        const result = await apiCall('/api/sync-all', { method: 'POST' });
        if (result.success) {
            status.textContent = `✓ ${result.message}`;
            setTimeout(() => status.textContent = '', 5000);
            await loadSemesters();
        } else {
            status.textContent = `✗ Ошибка: ${result.error}`;
        }
    } catch (error) {
        status.textContent = '✗ Ошибка синхронизации';
    } finally {
        btn.disabled = false;
    }
}

// Sync semesters only
async function syncSemesters() {
    const btn = document.getElementById('syncSemesters');
    const status = document.getElementById('syncStatus');

    btn.disabled = true;
    status.textContent = 'Синхронизация...';

    try {
        const result = await apiCall('/api/semesters/sync', { method: 'POST' });
        status.textContent = `✓ Синхронизировано ${result.count} семестров`;
        setTimeout(() => status.textContent = '', 3000);
        await loadSemesters();
    } catch (error) {
        status.textContent = '✗ Ошибка синхронизации';
    } finally {
        btn.disabled = false;
    }
}

// Select semester
async function selectSemester(semesterId) {
    // Update UI
    document.querySelectorAll('.semester-item').forEach(item => {
        item.classList.toggle('active', item.dataset.id == semesterId);
    });

    // Load semester data
    const semester = await apiCall(`/api/semesters/${semesterId}`);
    currentSemester = semester;

    // Enable sync button
    document.getElementById('syncCourses').disabled = false;

    // Load courses
    await loadCourses(semesterId);
}

// Sync courses
async function syncCourses(semesterId) {
    const btn = document.getElementById('syncCourses');
    const container = document.getElementById('coursesList');

    btn.disabled = true;
    container.innerHTML = '<div class="loading">Синхронизация курсов...</div>';

    try {
        const result = await apiCall(`/api/semesters/${semesterId}/courses/sync`, { method: 'POST' });
        await loadCourses(semesterId);
    } catch (error) {
        container.innerHTML = '<p class="empty-state">Ошибка синхронизации курсов</p>';
    } finally {
        btn.disabled = false;
    }
}

// Load courses
async function loadCourses(semesterId) {
    const container = document.getElementById('coursesList');
    container.innerHTML = '<div class="loading">Загрузка курсов...</div>';

    try {
        const courses = await apiCall(`/api/courses?semester_id=${semesterId}`);

        if (courses.length === 0) {
            container.innerHTML = '<p class="empty-state">Нет курсов. Нажмите "Синхронизировать"</p>';
            return;
        }

        container.innerHTML = courses.map(course => `
            <div class="course-card ${course.status === 'closed' ? 'closed' : ''}" onclick="selectCourse(${course.id})">
                <div class="course-name">${course.name}</div>
                <div class="course-meta">
                    <div>📚 Материалов: ${course.materials_count}</div>
                    <div>⏱ Время: ${course.total_time || 'N/A'}</div>
                    <div>📝 ${course.control_type || 'N/A'}</div>
                    <div>✅ Прогресс: ${course.completion_percentage.toFixed(1)}%</div>
                </div>
                <div class="course-progress-bar">
                    <div class="course-progress-fill" style="width: ${course.completion_percentage}%"></div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = '<p class="empty-state">Ошибка загрузки курсов</p>';
    }
}

// Select course
async function selectCourse(courseId) {
    const course = await apiCall(`/api/courses/${courseId}`);
    currentCourse = course;

    // Show materials view
    document.getElementById('coursesView').classList.add('hidden');
    document.getElementById('materialsView').classList.remove('hidden');

    // Update header
    document.getElementById('courseTitle').textContent = course.name;
    document.getElementById('courseProgress').textContent = `✅ Прогресс: ${course.completion_percentage.toFixed(1)}%`;
    document.getElementById('courseMaterialsCount').textContent = `📚 Материалов: ${course.materials_count}`;

    // Load materials
    await loadMaterials(course);
}

// Show courses view
function showCoursesView() {
    document.getElementById('materialsView').classList.add('hidden');
    document.getElementById('coursesView').classList.remove('hidden');
    currentCourse = null;
}

// Sync materials
async function syncMaterials(courseId) {
    const btn = document.getElementById('syncMaterials');
    const container = document.getElementById('materialsList');

    btn.disabled = true;
    container.innerHTML = '<div class="loading">Синхронизация материалов...</div>';

    try {
        await apiCall(`/api/courses/${courseId}/sync`, { method: 'POST' });
        const course = await apiCall(`/api/courses/${courseId}`);
        currentCourse = course;
        await loadMaterials(course);
    } catch (error) {
        container.innerHTML = '<p class="empty-state">Ошибка синхронизации материалов</p>';
    } finally {
        btn.disabled = false;
    }
}

// Load materials
function loadMaterials(course) {
    const container = document.getElementById('materialsList');

    if (!course.materials || course.materials.length === 0) {
        container.innerHTML = '<p class="empty-state">Нет материалов. Нажмите "Синхронизировать"</p>';
        return;
    }

    container.innerHTML = course.materials.map(material => {
        const typeIcon = getTypeIcon(material.type);
        const statusClass = material.is_blocked ? 'blocked' : material.is_completed ? 'completed' : '';
        const sectionClass = material.type === 'section' ? 'section' : '';

        let actions = '';
        if (material.type === 'video' && !material.is_blocked) {
            actions = `<button class="btn btn-success btn-small" onclick="watchVideo(${material.id})">▶ Просмотреть</button>`;
        }
        if (!material.is_blocked && material.type !== 'section') {
            actions += `<button class="btn btn-secondary btn-small" onclick="confirmMaterial(${material.id})">✓ Подтвердить</button>`;
        }

        return `
            <div class="material-item ${statusClass} ${sectionClass}" style="margin-left: ${material.level * 20}px">
                <div class="material-info">
                    <div class="material-name">${typeIcon} ${material.name}</div>
                    <div class="material-meta">
                        ${material.viewing_time ? `<span>⏱ ${material.viewing_time}</span>` : ''}
                        ${material.progress ? `<span>📊 ${material.progress}</span>` : ''}
                        ${material.is_blocked ? '<span style="color: #e53e3e">🔒 Заблокировано</span>' : ''}
                        ${material.is_completed ? '<span style="color: #38a169">✓ Завершено</span>' : ''}
                    </div>
                </div>
                <div class="material-actions">
                    ${actions}
                </div>
            </div>
        `;
    }).join('');
}

// Get type icon
function getTypeIcon(type) {
    const icons = {
        'video': '🎥',
        'pdf': '📄',
        'test': '📝',
        'section': '📁'
    };
    return icons[type] || '📌';
}

// Watch video
async function watchVideo(materialId) {
    try {
        const result = await apiCall(`/api/automation/watch-video/${materialId}`, { method: 'POST' });
        if (result.success) {
            showSuccess('Запущен просмотр видео');
            loadTasks();
        }
    } catch (error) {
        showError('Ошибка запуска просмотра видео');
    }
}

// Confirm material
async function confirmMaterial(materialId) {
    try {
        const result = await apiCall(`/api/automation/confirm-material/${materialId}`, { method: 'POST' });
        if (result.success) {
            showSuccess('Запущено подтверждение материала');
            loadTasks();
        }
    } catch (error) {
        showError('Ошибка подтверждения материала');
    }
}

// Auto complete course
async function autoCompleteCourse(courseId) {
    if (!confirm('Автоматически пройти все материалы курса?')) {
        return;
    }

    try {
        const result = await apiCall(`/api/automation/complete-course/${courseId}`, { method: 'POST' });
        if (result.success) {
            showSuccess('Запущено автоматическое прохождение курса');
            loadTasks();
        }
    } catch (error) {
        showError('Ошибка запуска автоматического прохождения');
    }
}

// Tasks polling
function startTaskPolling() {
    loadTasks();
    taskUpdateInterval = setInterval(loadTasks, 3000);
}

// Load tasks
async function loadTasks() {
    try {
        const allTasks = await apiCall('/api/automation/tasks?status=pending');
        const runningTasks = await apiCall('/api/automation/tasks?status=running');
        tasks = [...allTasks, ...runningTasks];

        renderTasks();
    } catch (error) {
        console.error('Failed to load tasks:', error);
    }
}

// Render tasks
function renderTasks() {
    const container = document.getElementById('tasksList');

    if (tasks.length === 0) {
        container.innerHTML = '<p class="empty-state">Нет активных задач</p>';
        return;
    }

    container.innerHTML = tasks.map(task => {
        const typeNames = {
            'watch_video': '🎥 Просмотр видео',
            'confirm_material': '✓ Подтверждение',
            'complete_course': '🎓 Прохождение курса'
        };

        return `
            <div class="task-item ${task.status}">
                <div class="task-type">${typeNames[task.task_type] || task.task_type}</div>
                <div class="task-progress">Статус: ${getStatusText(task.status)}</div>
                ${task.progress > 0 ? `
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${task.progress}%"></div>
                    </div>
                ` : ''}
                ${task.error_message ? `<div style="color: #e53e3e; font-size: 11px; margin-top: 4px">${task.error_message}</div>` : ''}
            </div>
        `;
    }).join('');
}

// Get status text
function getStatusText(status) {
    const statusTexts = {
        'pending': 'Ожидание',
        'running': 'Выполняется',
        'completed': 'Завершено',
        'failed': 'Ошибка',
        'cancelled': 'Отменено'
    };
    return statusTexts[status] || status;
}

// Notifications
function showSuccess(message) {
    const status = document.getElementById('syncStatus');
    status.textContent = `✓ ${message}`;
    status.style.color = '#38a169';
    setTimeout(() => status.textContent = '', 3000);
}

function showError(message) {
    const status = document.getElementById('syncStatus');
    status.textContent = `✗ ${message}`;
    status.style.color = '#e53e3e';
    setTimeout(() => status.textContent = '', 5000);
}
