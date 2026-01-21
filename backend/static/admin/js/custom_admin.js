// Кастомный JavaScript для админ панели

// Автообновление статусов задач
function initJobStatusAutoUpdate() {
    const jobCards = document.querySelectorAll('.job-card[data-job-id]');
    if (jobCards.length === 0) return;

    setInterval(function() {
        jobCards.forEach(function(card) {
            const jobId = card.getAttribute('data-job-id');
            if (!jobId) return;

            fetch(`/admin/api/job/${jobId}/status/`)
                .then(response => {
                    if (!response.ok) throw new Error('Network response was not ok');
                    return response.json();
                })
                .then(data => {
                    updateJobCard(card, data);
                })
                .catch(err => {
                    console.error('Error updating job status:', err);
                });
        });
    }, 5000); // Обновление каждые 5 секунд
}

// Обновление карточки задачи
function updateJobCard(card, data) {
    // Обновить прогресс
    const progressBar = card.querySelector('.progress-bar-fill');
    if (progressBar && data.progress > 0) {
        progressBar.style.width = data.progress + '%';
        if (data.status === 'running') {
            progressBar.classList.add('animated');
        } else {
            progressBar.classList.remove('animated');
        }
    }

    // Обновить статус
    const statusBadge = card.querySelector('.badge-status');
    if (statusBadge) {
        statusBadge.textContent = getStatusText(data.status);
        statusBadge.className = 'badge-status ' + data.status;
    }

    // Обновить класс карточки
    card.className = 'job-card ' + data.status;

    // Обновить сообщение
    const messageEl = card.querySelector('.job-message');
    if (messageEl && data.message) {
        messageEl.textContent = data.message;
    }

    // Показать ошибку если есть
    if (data.error && data.status === 'failed') {
        let errorEl = card.querySelector('.job-error');
        if (!errorEl) {
            errorEl = document.createElement('div');
            errorEl.className = 'job-error alert error';
            card.appendChild(errorEl);
        }
        errorEl.textContent = data.error;
    }
}

// Получить текст статуса
function getStatusText(status) {
    const statusMap = {
        'pending': 'Ожидает',
        'running': 'Выполняется',
        'completed': 'Завершено',
        'failed': 'Ошибка',
        'cancelled': 'Отменено'
    };
    return statusMap[status] || status;
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Автообновление статусов
    if (document.querySelector('.job-card[data-job-id]')) {
        initJobStatusAutoUpdate();
    }

    // Улучшение таблиц
    const tables = document.querySelectorAll('.admin-table, table');
    tables.forEach(table => {
        if (!table.classList.contains('admin-table')) {
            table.classList.add('admin-table');
        }
    });

    // Добавление анимаций для карточек
    const cards = document.querySelectorAll('.admin-card, .stat-card, .student-card');
    cards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-2px)';
        });
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
        });
    });

    // Улучшение форм
    const inputs = document.querySelectorAll('input[type="text"], input[type="email"], textarea, select');
    inputs.forEach(input => {
        if (!input.classList.contains('form-input')) {
            input.classList.add('form-input');
        }
    });
});

// Утилита для показа уведомлений
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert ${type}`;
    notification.textContent = message;
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.zIndex = '9999';
    notification.style.minWidth = '300px';
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// Экспорт функций для использования в других скриптах
window.AdminUtils = {
    initJobStatusAutoUpdate,
    updateJobCard,
    showNotification
};
