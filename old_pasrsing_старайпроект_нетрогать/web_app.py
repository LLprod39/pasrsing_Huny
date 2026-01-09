"""
Synergy LMS Parser - Web Interface Backend
Flask application with WebSocket support for real-time progress updates
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import os
import json
import threading
from datetime import datetime
from test import SynergyLMSOptimizedParser
from config import Credentials
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'synergy_lms_parser_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
parser_instance = None
parsing_thread = None
current_progress = {
    'status': 'idle',
    'current_task': '',
    'progress': 0,
    'total_courses': 0,
    'processed_courses': 0,
    'current_course': '',
    'materials_found': 0,
    'errors': []
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebSocketProgressHandler:
    """Custom progress handler that emits updates via WebSocket"""

    @staticmethod
    def update_status(status, message='', progress=0):
        current_progress['status'] = status
        current_progress['current_task'] = message
        current_progress['progress'] = progress
        socketio.emit('progress_update', current_progress, namespace='/')
        logger.info(f"Progress: {status} - {message} ({progress}%)")

    @staticmethod
    def update_course_progress(course_name, processed, total):
        current_progress['current_course'] = course_name
        current_progress['processed_courses'] = processed
        current_progress['total_courses'] = total
        current_progress['progress'] = int((processed / total) * 100) if total > 0 else 0
        socketio.emit('progress_update', current_progress, namespace='/')

    @staticmethod
    def update_materials(count):
        current_progress['materials_found'] = count
        socketio.emit('progress_update', current_progress, namespace='/')

    @staticmethod
    def add_error(error_msg):
        current_progress['errors'].append({
            'timestamp': datetime.now().isoformat(),
            'message': error_msg
        })
        socketio.emit('progress_update', current_progress, namespace='/')


def run_parser_task(username, password, semester_choice, course_choices):
    """Background task for running the parser"""
    global parser_instance, current_progress

    try:
        WebSocketProgressHandler.update_status('initializing', 'Инициализация парсера...', 5)

        # Инициализируем парсер с настройками по умолчанию (без скачивания)
        parser_instance = SynergyLMSOptimizedParser(
            max_workers=3,
            simulate_watching=True
        )
        
        # Устанавливаем учетные данные
        parser_instance.credentials['username'] = username
        parser_instance.credentials['password'] = password

        WebSocketProgressHandler.update_status('authenticating', 'Авторизация...', 10)

        if not parser_instance.login():
            WebSocketProgressHandler.add_error('Ошибка авторизации')
            WebSocketProgressHandler.update_status('error', 'Ошибка авторизации', 0)
            return

        WebSocketProgressHandler.update_status('loading_data', 'Получение данных о курсах...', 20)
        
        # Получаем все данные (семестры и курсы)
        all_data = parser_instance.get_all_data_optimized()
        
        if "error" in all_data:
            WebSocketProgressHandler.add_error(f"Ошибка получения данных: {all_data['error']}")
            WebSocketProgressHandler.update_status('error', 'Ошибка получения данных', 0)
            return

        semesters_data = all_data.get('semesters', {})
        
        # Преобразуем в список для удобства (как было раньше)
        # Предполагаем, что semester_choice - это индекс или номер семестра
        # Если semester_choice приходит как индекс (0, 1, 2...), нам нужно найти соответствующий номер семестра
        sorted_semester_nums = sorted(semesters_data.keys())
        
        if not sorted_semester_nums or semester_choice >= len(sorted_semester_nums):
            WebSocketProgressHandler.add_error('Семестр не найден')
            WebSocketProgressHandler.update_status('error', 'Семестр не найден', 0)
            return

        target_semester_num = sorted_semester_nums[semester_choice]
        target_semester = semesters_data[target_semester_num]
        courses = target_semester.get('courses', [])

        WebSocketProgressHandler.update_course_progress('', 0, len(course_choices))

        for idx, course_idx in enumerate(course_choices):
            if course_idx >= len(courses):
                continue

            course = courses[course_idx]
            course_name = course['name']
            course_url = course['url']
            
            WebSocketProgressHandler.update_status(
                'processing_course',
                f'Обработка курса: {course_name}',
                30 + int((idx / len(course_choices)) * 60)
            )
            WebSocketProgressHandler.update_course_progress(course_name, idx, len(course_choices))

            # Получаем материалы курса (используем параллельный метод)
            materials, total_time, _ = parser_instance.get_course_materials_parallel(course_url)
            
            WebSocketProgressHandler.update_materials(current_progress['materials_found'] + len(materials))

            # Подготавливаем данные для экспорта
            materials_data = {
                "course_name": course_name,
                "course_url": course_url,
                "timestamp": datetime.now().isoformat(),
                "materials_count": len(materials),
                "total_time": total_time,
                "materials": [m.to_dict() for m in materials]
            }

            # Export results
            output_file = f'materials_{parser_instance._sanitize_filename(course_name)}.json'
            parser_instance.export_to_json(materials_data, output_file)

        WebSocketProgressHandler.update_status('completed', 'Парсинг завершен!', 100)
        WebSocketProgressHandler.update_course_progress('Завершено', len(course_choices), len(course_choices))

    except Exception as e:
        error_msg = f'Критическая ошибка: {str(e)}'
        logger.error(error_msg, exc_info=True)
        WebSocketProgressHandler.add_error(error_msg)
        WebSocketProgressHandler.update_status('error', error_msg, 0)

    finally:
        if parser_instance:
            parser_instance.close()


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/start_parsing', methods=['POST'])
def start_parsing():
    """Start parsing task"""
    global parsing_thread, current_progress

    if parsing_thread and parsing_thread.is_alive():
        return jsonify({'error': 'Парсинг уже выполняется'}), 400

    data = request.json
    username = data.get('username')
    password = data.get('password')
    semester = data.get('semester', 0)
    courses = data.get('courses', [])
    # download = data.get('download', False) # Removed download argument

    if not username or not password:
        return jsonify({'error': 'Необходимо указать логин и пароль'}), 400

    # Reset progress
    current_progress = {
        'status': 'starting',
        'current_task': 'Запуск парсера...',
        'progress': 0,
        'total_courses': len(courses),
        'processed_courses': 0,
        'current_course': '',
        'materials_found': 0,
        'errors': []
    }

    parsing_thread = threading.Thread(
        target=run_parser_task,
        args=(username, password, semester, courses)
    )
    parsing_thread.daemon = True
    parsing_thread.start()

    return jsonify({'status': 'started', 'message': 'Парсинг запущен'})


@app.route('/api/stop_parsing', methods=['POST'])
def stop_parsing():
    """Stop parsing task"""
    global parser_instance

    if parser_instance:
        parser_instance.close()
        WebSocketProgressHandler.update_status('stopped', 'Парсинг остановлен пользователем', 0)
        return jsonify({'status': 'stopped'})

    return jsonify({'error': 'Парсинг не запущен'}), 400


@app.route('/api/status')
def get_status():
    """Get current parsing status"""
    return jsonify(current_progress)


@app.route('/api/results')
def get_results():
    """Get list of exported JSON files"""
    json_files = [f for f in os.listdir('.') if f.startswith('materials_') and f.endswith('.json')]
    results = []

    for file in json_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                results.append({
                    'filename': file,
                    'course_name': data.get('course_name', 'Unknown'),
                    'materials_count': data.get('materials_count', 0),
                    'timestamp': data.get('timestamp', '')
                })
        except:
            pass

    return jsonify(results)


@app.route('/api/download/<filename>')
def download_file(filename):
    """Download exported JSON file"""
    if filename.startswith('materials_') and filename.endswith('.json'):
        return send_file(filename, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404


@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    emit('progress_update', current_progress)
    logger.info('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info('Client disconnected')


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
