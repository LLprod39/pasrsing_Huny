"""
Database models for Synergy LMS Web Application
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON

db = SQLAlchemy()


class Semester(db.Model):
    """Semester model"""
    __tablename__ = 'semesters'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    number = db.Column(db.Integer, nullable=False, unique=True)  # Semester number (1, 2, 3, etc.)
    status = db.Column(db.String(50))  # active, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    courses = db.relationship('Course', backref='semester', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'number': self.number,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'courses_count': len(self.courses)
        }


class Course(db.Model):
    """Course model"""
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    name = db.Column(db.String(512), nullable=False)
    url = db.Column(db.String(512), nullable=False, unique=True)
    control_type = db.Column(db.String(100))
    status = db.Column(db.String(50))  # open, closed
    materials_count = db.Column(db.Integer, default=0)
    total_time = db.Column(db.String(50))
    completion_percentage = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_parsed = db.Column(db.DateTime)

    materials = db.relationship('Material', backref='course', lazy=True, cascade='all, delete-orphan')

    def to_dict(self, include_materials=False):
        data = {
            'id': self.id,
            'semester_id': self.semester_id,
            'name': self.name,
            'url': self.url,
            'control_type': self.control_type,
            'status': self.status,
            'materials_count': self.materials_count,
            'total_time': self.total_time,
            'completion_percentage': self.completion_percentage,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_parsed': self.last_parsed.isoformat() if self.last_parsed else None
        }
        if include_materials:
            data['materials'] = [m.to_dict() for m in self.materials]
        return data


class Material(db.Model):
    """Course material model"""
    __tablename__ = 'materials'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    name = db.Column(db.String(512), nullable=False)
    url = db.Column(db.String(512))
    viewing_time = db.Column(db.String(50))
    progress = db.Column(db.String(50))
    is_blocked = db.Column(db.Boolean, default=False)
    level = db.Column(db.Integer, default=0)
    data_index = db.Column(db.String(50))
    type = db.Column(db.String(50))  # video, pdf, section, etc.
    completion_status = db.Column(db.String(50))
    duration_seconds = db.Column(db.Integer)  # For videos
    is_completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'name': self.name,
            'url': self.url,
            'viewing_time': self.viewing_time,
            'progress': self.progress,
            'is_blocked': self.is_blocked,
            'level': self.level,
            'data_index': self.data_index,
            'type': self.type,
            'completion_status': self.completion_status,
            'duration_seconds': self.duration_seconds,
            'is_completed': self.is_completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class AutomationTask(db.Model):
    """Background automation task model"""
    __tablename__ = 'automation_tasks'

    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(50), nullable=False)  # watch_video, confirm_material, complete_course
    material_id = db.Column(db.Integer, db.ForeignKey('materials.id'), nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, running, completed, failed
    progress = db.Column(db.Float, default=0.0)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    material = db.relationship('Material', backref='tasks')
    course = db.relationship('Course', backref='tasks')

    def to_dict(self):
        return {
            'id': self.id,
            'task_type': self.task_type,
            'material_id': self.material_id,
            'course_id': self.course_id,
            'status': self.status,
            'progress': self.progress,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
