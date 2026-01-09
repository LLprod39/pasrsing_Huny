"""
Flask Web Application for Synergy LMS Automation
"""
import os
import logging
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from models import db, Semester, Course, Material, AutomationTask
from parser_service import ParserService
from automation_service import AutomationService

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///synergy_lms.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'synergy-lms-secret-key-change-in-production'

# Initialize database
db.init_app(app)

# Initialize services
parser_service = ParserService()
automation_service = AutomationService()

# Create tables on startup
with app.app_context():
    db.create_all()


# ==================== WEB ROUTES ====================

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


# ==================== API ROUTES ====================

# --- Semesters ---

@app.route('/api/semesters', methods=['GET'])
def get_semesters():
    """Get all semesters"""
    semesters = Semester.query.order_by(Semester.created_at.desc()).all()
    return jsonify([s.to_dict() for s in semesters])


@app.route('/api/semesters/sync', methods=['POST'])
def sync_semesters():
    """Sync semesters from LMS"""
    try:
        semesters_data = parser_service.fetch_semesters()

        for sem_data in semesters_data:
            semester = Semester.query.filter_by(number=sem_data['number']).first()
            if not semester:
                semester = Semester(
                    name=sem_data['name'],
                    url=sem_data['url'],
                    number=sem_data['number'],
                    status=sem_data.get('status', 'active')
                )
                db.session.add(semester)
            else:
                semester.name = sem_data['name']
                semester.url = sem_data['url']
                semester.status = sem_data.get('status', 'active')

        db.session.commit()
        return jsonify({'success': True, 'count': len(semesters_data)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sync-all', methods=['POST'])
def sync_all_data():
    """Полная синхронизация всех данных: семестры, курсы и материалы"""
    try:
        logger.info("Starting full data sync...")
        
        # Парсим все данные
        data = parser_service.parse_all_data()
        
        # Сохраняем семестры
        for sem_data in data['semesters']:
            semester = Semester.query.filter_by(number=sem_data['number']).first()
            if not semester:
                semester = Semester(
                    name=sem_data['name'],
                    url=sem_data['url'],
                    number=sem_data['number'],
                    status=sem_data.get('status', 'active')
                )
                db.session.add(semester)
            else:
                semester.name = sem_data['name']
                semester.url = sem_data['url']
                semester.status = sem_data.get('status', 'active')
        
        db.session.flush()  # Получаем ID семестров
        
        # Сохраняем курсы
        for sem_data in data['semesters']:
            semester = Semester.query.filter_by(number=sem_data['number']).first()
            if not semester:
                continue
                
            for course_data in sem_data['courses']:
                course = Course.query.filter_by(url=course_data['url']).first()
                if not course:
                    course = Course(
                        semester_id=semester.id,
                        name=course_data['name'],
                        url=course_data['url'],
                        control_type=course_data.get('control_type'),
                        status=course_data.get('status', 'open'),
                        materials_count=len(course_data.get('materials', [])),
                        total_time=course_data.get('total_time'),
                        completion_percentage=course_data.get('completion_percentage', 0.0)
                    )
                    db.session.add(course)
                else:
                    course.name = course_data['name']
                    course.control_type = course_data.get('control_type')
                    course.status = course_data.get('status', 'open')
                    course.materials_count = len(course_data.get('materials', []))
                    course.total_time = course_data.get('total_time')
                    course.completion_percentage = course_data.get('completion_percentage', 0.0)
        
        db.session.flush()  # Получаем ID курсов
        
        # Сохраняем материалы
        for sem_data in data['semesters']:
            for course_data in sem_data['courses']:
                course = Course.query.filter_by(url=course_data['url']).first()
                if not course:
                    continue
                
                # Удаляем старые материалы
                Material.query.filter_by(course_id=course.id).delete()
                
                # Добавляем новые материалы
                for mat_data in course_data.get('materials', []):
                    material = Material(
                        course_id=course.id,
                        name=mat_data['name'],
                        url=mat_data.get('url'),
                        viewing_time=mat_data.get('viewing_time'),
                        progress=mat_data.get('progress'),
                        is_blocked=mat_data.get('is_blocked', False),
                        level=mat_data.get('level', 0),
                        data_index=mat_data.get('data_index'),
                        type=mat_data.get('type'),
                        completion_status=mat_data.get('completion_status'),
                        duration_seconds=mat_data.get('duration_seconds'),
                        is_completed=mat_data.get('is_completed', False)
                    )
                    db.session.add(material)
        
        db.session.commit()
        
        logger.info(f"Full sync completed: {data['total_semesters']} semesters, {data['total_courses']} courses, {data['total_materials']} materials")
        
        return jsonify({
            'success': True,
            'message': f"Successfully synced {data['total_semesters']} semesters, {data['total_courses']} courses, {data['total_materials']} materials",
            'stats': {
                'semesters': data['total_semesters'],
                'courses': data['total_courses'],
                'materials': data['total_materials']
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Full sync failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/semesters/<int:semester_id>', methods=['GET'])
def get_semester(semester_id):
    """Get semester by ID with courses"""
    semester = Semester.query.get_or_404(semester_id)
    data = semester.to_dict()
    data['courses'] = [c.to_dict() for c in semester.courses]
    return jsonify(data)


# --- Courses ---

@app.route('/api/courses', methods=['GET'])
def get_courses():
    """Get all courses or filter by semester"""
    semester_id = request.args.get('semester_id', type=int)

    if semester_id:
        courses = Course.query.filter_by(semester_id=semester_id).all()
    else:
        courses = Course.query.all()

    return jsonify([c.to_dict() for c in courses])


@app.route('/api/courses/<int:course_id>', methods=['GET'])
def get_course(course_id):
    """Get course by ID with materials"""
    course = Course.query.get_or_404(course_id)
    return jsonify(course.to_dict(include_materials=True))


@app.route('/api/semesters/<int:semester_id>/courses/sync', methods=['POST'])
def sync_semester_courses(semester_id):
    """Sync courses for a specific semester"""
    try:
        semester = Semester.query.get_or_404(semester_id)
        courses_data = parser_service.fetch_courses(semester.number)

        for course_data in courses_data:
            course = Course.query.filter_by(url=course_data['url']).first()
            if not course:
                course = Course(
                    semester_id=semester.id,
                    name=course_data['name'],
                    url=course_data['url'],
                    control_type=course_data.get('control_type'),
                    status=course_data.get('status', 'open'),
                    materials_count=course_data.get('materials_count', 0),
                    total_time=course_data.get('total_time'),
                    completion_percentage=course_data.get('completion_percentage', 0.0)
                )
                db.session.add(course)
            else:
                # Update only changed fields
                course.name = course_data['name']
                course.control_type = course_data.get('control_type')
                course.status = course_data.get('status', 'open')
                course.materials_count = course_data.get('materials_count', 0)
                course.total_time = course_data.get('total_time')
                course.completion_percentage = course_data.get('completion_percentage', 0.0)

        db.session.commit()
        return jsonify({'success': True, 'count': len(courses_data)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/courses/<int:course_id>/sync', methods=['POST'])
def sync_course_materials(course_id):
    """Sync materials for a specific course"""
    try:
        course = Course.query.get_or_404(course_id)
        materials_data = parser_service.fetch_materials(course.url)

        # Track existing materials by URL
        existing_materials = {m.url: m for m in course.materials if m.url}

        for mat_data in materials_data:
            material_url = mat_data.get('url')

            if material_url and material_url in existing_materials:
                # Update existing material
                material = existing_materials[material_url]
                material.name = mat_data['name']
                material.viewing_time = mat_data.get('viewing_time')
                material.progress = mat_data.get('progress')
                material.is_blocked = mat_data.get('is_blocked', False)
                material.level = mat_data.get('level', 0)
                material.data_index = mat_data.get('data_index')
                material.type = mat_data.get('type')
                material.completion_status = mat_data.get('completion_status')
            else:
                # Create new material
                material = Material(
                    course_id=course.id,
                    name=mat_data['name'],
                    url=material_url,
                    viewing_time=mat_data.get('viewing_time'),
                    progress=mat_data.get('progress'),
                    is_blocked=mat_data.get('is_blocked', False),
                    level=mat_data.get('level', 0),
                    data_index=mat_data.get('data_index'),
                    type=mat_data.get('type'),
                    completion_status=mat_data.get('completion_status')
                )
                db.session.add(material)

        from datetime import datetime
        course.last_parsed = datetime.utcnow()
        course.materials_count = len(materials_data)

        db.session.commit()
        return jsonify({'success': True, 'count': len(materials_data)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Materials ---

@app.route('/api/materials/<int:material_id>', methods=['GET'])
def get_material(material_id):
    """Get material by ID"""
    material = Material.query.get_or_404(material_id)
    return jsonify(material.to_dict())


@app.route('/api/materials/<int:material_id>', methods=['PATCH'])
def update_material(material_id):
    """Update material"""
    material = Material.query.get_or_404(material_id)
    data = request.json

    if 'is_completed' in data:
        material.is_completed = data['is_completed']
    if 'progress' in data:
        material.progress = data['progress']
    if 'completion_status' in data:
        material.completion_status = data['completion_status']

    db.session.commit()
    return jsonify(material.to_dict())


# --- Automation ---

@app.route('/api/automation/tasks', methods=['GET'])
def get_automation_tasks():
    """Get all automation tasks"""
    status = request.args.get('status')

    query = AutomationTask.query
    if status:
        query = query.filter_by(status=status)

    tasks = query.order_by(AutomationTask.created_at.desc()).limit(100).all()
    return jsonify([t.to_dict() for t in tasks])


@app.route('/api/automation/watch-video/<int:material_id>', methods=['POST'])
def watch_video(material_id):
    """Start video watching automation"""
    try:
        material = Material.query.get_or_404(material_id)

        # Create automation task
        task = AutomationTask(
            task_type='watch_video',
            material_id=material.id,
            course_id=material.course_id,
            status='pending'
        )
        db.session.add(task)
        db.session.commit()

        # Start automation in background
        automation_service.watch_video(task.id, material)

        return jsonify({'success': True, 'task_id': task.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/automation/confirm-material/<int:material_id>', methods=['POST'])
def confirm_material(material_id):
    """Confirm material completion"""
    try:
        material = Material.query.get_or_404(material_id)

        task = AutomationTask(
            task_type='confirm_material',
            material_id=material.id,
            course_id=material.course_id,
            status='pending'
        )
        db.session.add(task)
        db.session.commit()

        automation_service.confirm_material(task.id, material)

        return jsonify({'success': True, 'task_id': task.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/automation/complete-course/<int:course_id>', methods=['POST'])
def complete_course(course_id):
    """Auto-complete all materials in course"""
    try:
        course = Course.query.get_or_404(course_id)

        task = AutomationTask(
            task_type='complete_course',
            course_id=course.id,
            status='pending'
        )
        db.session.add(task)
        db.session.commit()

        automation_service.complete_course(task.id, course)

        return jsonify({'success': True, 'task_id': task.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/automation/tasks/<int:task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get automation task status"""
    task = AutomationTask.query.get_or_404(task_id)
    return jsonify(task.to_dict())


@app.route('/api/automation/tasks/<int:task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    """Cancel automation task"""
    try:
        task = AutomationTask.query.get_or_404(task_id)

        if task.status in ['pending', 'running']:
            automation_service.cancel_task(task_id)
            task.status = 'cancelled'
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Task cannot be cancelled'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
