from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('admin', 'teacher', 'student', name='user_roles'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student_profile = db.relationship('Student', backref='user', uselist=False, lazy=True)
    teacher_profile = db.relationship('Teacher', backref='user', uselist=False, lazy=True)
    attendances_marked = db.relationship('Attendance', backref='marker', lazy=True)
    
    def __repr__(self):
        return f"<User {self.name} ({self.role})>"
        
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Student(db.Model):
    __tablename__ = 'students'
    
    student_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.class_id'), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    
    # Relationships
    enrollments = db.relationship('Enrollment', backref='student', lazy=True, cascade="all, delete-orphan")
    attendances = db.relationship('Attendance', backref='student', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Student {self.roll_number}>"
        
    def to_dict(self):
        return {
            'student_id': self.student_id,
            'user_id': self.user_id,
            'roll_number': self.roll_number,
            'class_id': self.class_id,
            'department': self.department
        }

class Teacher(db.Model):
    __tablename__ = 'teachers'
    
    teacher_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    
    # Relationships
    subjects = db.relationship('Subject', backref='teacher', lazy=True)
    
    def __repr__(self):
        return f"<Teacher ID {self.teacher_id}>"
        
    def to_dict(self):
        return {
            'teacher_id': self.teacher_id,
            'user_id': self.user_id,
            'department': self.department
        }

class Class(db.Model):
    __tablename__ = 'classes'
    
    class_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    class_name = db.Column(db.String(100), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    
    # Relationships
    students = db.relationship('Student', backref='class_', lazy=True)
    attendances = db.relationship('Attendance', backref='class_', lazy=True)
    
    def __repr__(self):
        return f"<Class {self.class_name} Sem {self.semester}>"
        
    def to_dict(self):
        return {
            'class_id': self.class_id,
            'class_name': self.class_name,
            'semester': self.semester,
            'department': self.department
        }

class Subject(db.Model):
    __tablename__ = 'subjects'
    
    subject_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject_name = db.Column(db.String(100), nullable=False)
    subject_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.teacher_id'), nullable=False)
    
    # Relationships
    enrollments = db.relationship('Enrollment', backref='subject', lazy=True, cascade="all, delete-orphan")
    attendances = db.relationship('Attendance', backref='subject', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Subject {self.subject_code}>"
        
    def to_dict(self):
        return {
            'subject_id': self.subject_id,
            'subject_name': self.subject_name,
            'subject_code': self.subject_code,
            'teacher_id': self.teacher_id
        }

class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    
    enrollment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.student_id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'), nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', name='uq_student_subject_enrollment'),
    )
    
    def __repr__(self):
        return f"<Enrollment Student {self.student_id} Subject {self.subject_id}>"
        
    def to_dict(self):
        return {
            'enrollment_id': self.enrollment_id,
            'student_id': self.student_id,
            'subject_id': self.subject_id
        }

class Attendance(db.Model):
    __tablename__ = 'attendances'
    
    attendance_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.student_id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subject_id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.class_id'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum('present', 'absent', 'late', 'excused', name='attendance_status'), nullable=False)
    marked_by = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'attendance_date', name='uq_student_subject_date_attendance'),
    )
    
    def __repr__(self):
        return f"<Attendance Student {self.student_id} Date {self.attendance_date} Status {self.status}>"
        
    def to_dict(self):
        return {
            'attendance_id': self.attendance_id,
            'student_id': self.student_id,
            'subject_id': self.subject_id,
            'class_id': self.class_id,
            'attendance_date': self.attendance_date.isoformat() if self.attendance_date else None,
            'status': self.status,
            'marked_by': self.marked_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
