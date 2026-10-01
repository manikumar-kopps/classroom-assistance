from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, jsonify, Response, current_app
from models import db, User, Student, Teacher, Class, Subject, Enrollment, Attendance
from auth import login_required, role_required, hash_password, check_password, generate_token
import datetime
import csv
from io import StringIO
from sqlalchemy import func, and_

try:
    from ai_assistant import get_ai_response, build_db_context, generate_ai_insights, detect_attendance_from_image
except ImportError:
    def get_ai_response(question, user_context, db_context):
        return "AI Assistant is being configured. Please check your Azure OpenAI credentials in .env"
    def build_db_context(user, db_session):
        return ""
    def generate_ai_insights(db_session, class_id=None):
        return []
    def detect_attendance_from_image(image_bytes, mime_type, students_roster):
        return {"detected_count": 0, "summary": "AI image detection ready.", "attendance": []}

main = Blueprint('main', __name__)


# ─── Context Processor ────────────────────────────────────────────────
@main.app_context_processor
def inject_current_user():
    """Make current_user available in all templates."""
    return dict(current_user=getattr(g, 'current_user', None))


# ─── Root Redirect ────────────────────────────────────────────────────
@main.route('/')
def index():
    if 'token' in session:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('main.login'))


# ═══════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password(password, user.password_hash):
            token = generate_token(user.user_id, user.role)
            session['token'] = token
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('main.dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@main.route('/logout')
def logout():
    session.pop('token', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.login'))


@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role = request.form.get('role', 'student').strip().lower()
        department = request.form.get('department', '').strip()

        if not all([name, email, password, confirm_password]):
            flash('Please fill in all required fields.', 'danger')
            classes = Class.query.order_by(Class.class_name).all()
            return render_template('register.html', classes=classes)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            classes = Class.query.order_by(Class.class_name).all()
            return render_template('register.html', classes=classes)

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            classes = Class.query.order_by(Class.class_name).all()
            return render_template('register.html', classes=classes)

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            classes = Class.query.order_by(Class.class_name).all()
            return render_template('register.html', classes=classes)

        if role not in ('student', 'teacher'):
            role = 'student'

        try:
            user = User(
                name=name,
                email=email,
                password_hash=hash_password(password),
                role=role
            )
            db.session.add(user)
            db.session.flush()

            if role == 'student':
                roll_number = request.form.get('roll_number', '').strip()
                class_id = request.form.get('class_id')
                if not roll_number or not class_id:
                    db.session.rollback()
                    flash('Roll number and class selection are required for students.', 'danger')
                    classes = Class.query.order_by(Class.class_name).all()
                    return render_template('register.html', classes=classes)

                if Student.query.filter_by(roll_number=roll_number).first():
                    db.session.rollback()
                    flash('This roll number is already registered.', 'danger')
                    classes = Class.query.order_by(Class.class_name).all()
                    return render_template('register.html', classes=classes)

                student = Student(
                    user_id=user.user_id,
                    roll_number=roll_number,
                    class_id=int(class_id),
                    department=department or 'Computer Applications'
                )
                db.session.add(student)
                db.session.flush()

                # Automatically enroll student in existing subjects
                all_subjects = Subject.query.all()
                for subj in all_subjects:
                    enr = Enrollment(student_id=student.student_id, subject_id=subj.subject_id)
                    db.session.add(enr)

            elif role == 'teacher':
                teacher = Teacher(
                    user_id=user.user_id,
                    department=department or 'Computer Applications'
                )
                db.session.add(teacher)

            db.session.commit()
            flash('Account created successfully! You can now sign in.', 'success')
            return redirect(url_for('main.login'))

        except Exception as e:
            db.session.rollback()
            flash(f'Registration error: {str(e)}', 'danger')
            classes = Class.query.order_by(Class.class_name).all()
            return render_template('register.html', classes=classes)

    classes = Class.query.order_by(Class.class_name).all()
    return render_template('register.html', classes=classes)


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD ROUTER
# ═══════════════════════════════════════════════════════════════════════
@main.route('/dashboard')
@login_required
def dashboard():
    role = g.current_user.role
    if role == 'admin':
        return redirect(url_for('main.admin_dashboard'))
    elif role == 'teacher':
        return redirect(url_for('main.teacher_dashboard'))
    elif role == 'student':
        return redirect(url_for('main.student_dashboard'))
    return redirect(url_for('main.login'))


# ═══════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════
@main.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')


# ═══════════════════════════════════════════════════════════════════════
# TEACHER DASHBOARD
# ═══════════════════════════════════════════════════════════════════════
@main.route('/teacher/dashboard')
@login_required
@role_required('teacher')
def teacher_dashboard():
    teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
    if not teacher:
        flash('Teacher profile not found.', 'danger')
        return redirect(url_for('main.login'))

    subjects = Subject.query.filter_by(teacher_id=teacher.teacher_id).all()
    today = datetime.date.today()

    assigned_classes = []
    all_classes = Class.query.all()
    if subjects:
        for subj in subjects:
            for cls in all_classes:
                st_count = Student.query.filter_by(class_id=cls.class_id).count()
                assigned_classes.append({
                    'id': cls.class_id,
                    'name': cls.class_name,
                    'subject': subj.subject_name,
                    'subject_code': subj.subject_code,
                    'subject_id': subj.subject_id,
                    'students_count': st_count
                })
    else:
        all_subjects = Subject.query.all()
        for cls in all_classes:
            st_count = Student.query.filter_by(class_id=cls.class_id).count()
            subj_title = all_subjects[0].subject_name if all_subjects else 'General Subject'
            subj_id = all_subjects[0].subject_id if all_subjects else 1
            assigned_classes.append({
                'id': cls.class_id,
                'name': cls.class_name,
                'subject': subj_title,
                'subject_code': all_subjects[0].subject_code if all_subjects else 'GEN',
                'subject_id': subj_id,
                'students_count': st_count
            })

    my_classes_count = len(all_classes)
    my_subjects_count = len(subjects) if subjects else len(Subject.query.all())

    marked_count = Attendance.query.filter(
        Attendance.marked_by == g.current_user.user_id,
        Attendance.attendance_date == today
    ).count()

    stats = {
        'my_classes': my_classes_count,
        'my_subjects': my_subjects_count,
        'marked_today': 1 if marked_count > 0 else 0,
        'pending_today': max(0, my_subjects_count - (1 if marked_count > 0 else 0))
    }

    subject_ids = [s.subject_id for s in subjects]
    recent_objs = (Attendance.query
                  .filter(Attendance.subject_id.in_(subject_ids))
                  .order_by(Attendance.attendance_date.desc(), Attendance.created_at.desc())
                  .limit(10).all()) if subject_ids else []

    recent_records = []
    for r in recent_objs:
        cls = Class.query.get(r.class_id)
        subj = Subject.query.get(r.subject_id)
        recent_records.append({
            'date': r.attendance_date.strftime('%Y-%m-%d'),
            'class': cls.class_name if cls else 'Class',
            'subject': subj.subject_name if subj else 'Subject',
            'pct': '100%' if r.status in ('present', 'late') else '0%'
        })

    teacher_records = Attendance.query.filter(Attendance.subject_id.in_(subject_ids)).all() if subject_ids else []
    t_present = sum(1 for r in teacher_records if r.status == 'present')
    t_absent = sum(1 for r in teacher_records if r.status == 'absent')
    t_late = sum(1 for r in teacher_records if r.status == 'late')

    chart_data = {
        'present': t_present if t_present > 0 else 80,
        'absent': t_absent if t_absent > 0 else 15,
        'late': t_late if t_late > 0 else 5
    }

    return render_template('teacher_dashboard.html',
                           teacher=teacher,
                           stats=stats,
                           assigned_classes=assigned_classes,
                           recent_records=recent_records,
                           chart_data=chart_data)


# ═══════════════════════════════════════════════════════════════════════
# STUDENT DASHBOARD
# ═══════════════════════════════════════════════════════════════════════
@main.route('/student/dashboard')
@login_required
@role_required('student')
def student_dashboard():
    student = Student.query.filter_by(user_id=g.current_user.user_id).first()
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('main.login'))

    records = Attendance.query.filter_by(student_id=student.student_id).all()
    total = len(records)
    present = sum(1 for r in records if r.status in ('present', 'late'))
    absent = sum(1 for r in records if r.status == 'absent')
    late = sum(1 for r in records if r.status == 'late')
    excused = sum(1 for r in records if r.status == 'excused')
    overall_pct = round((present / total * 100), 1) if total > 0 else 0

    enrollments = Enrollment.query.filter_by(student_id=student.student_id).all()
    stats = {
        'overall': overall_pct,
        'attended': present,
        'missed': absent,
        'subjects': len(enrollments)
    }

    chart_pie = {
        'present': sum(1 for r in records if r.status == 'present'),
        'absent': absent,
        'late': late,
        'excused': excused
    }

    bar_labels = []
    bar_data = []
    for enr in enrollments:
        subj = Subject.query.get(enr.subject_id)
        if subj:
            sub_records = [r for r in records if r.subject_id == subj.subject_id]
            s_total = len(sub_records)
            s_present = sum(1 for r in sub_records if r.status in ('present', 'late'))
            s_pct = round((s_present / s_total * 100), 1) if s_total > 0 else 0
            bar_labels.append(subj.subject_code)
            bar_data.append(s_pct)

    chart_bar = {
        'labels': bar_labels or ['CS101', 'CS102'],
        'data': bar_data or [85, 90]
    }

    monthly = {}
    for r in records:
        key = r.attendance_date.strftime('%b %Y')
        if key not in monthly:
            monthly[key] = {'total': 0, 'present': 0}
        monthly[key]['total'] += 1
        if r.status in ('present', 'late'):
            monthly[key]['present'] += 1

    line_labels = list(monthly.keys())
    line_data = [round(v['present'] / v['total'] * 100, 1) if v['total'] > 0 else 0 for v in monthly.values()]

    chart_line = {
        'labels': line_labels or ['Month 1', 'Month 2'],
        'data': line_data or [85, 88]
    }

    recent_objs = sorted(records, key=lambda r: r.attendance_date, reverse=True)[:10]
    recent_records = []
    status_colors = {'present': 'success', 'absent': 'danger', 'late': 'warning', 'excused': 'info'}
    for r in recent_objs:
        subj = Subject.query.get(r.subject_id)
        recent_records.append({
            'date': r.attendance_date.strftime('%Y-%m-%d'),
            'subject': subj.subject_name if subj else 'Subject',
            'status': r.status.capitalize(),
            'color': status_colors.get(r.status, 'primary')
        })

    return render_template('student_dashboard.html',
                           student=student,
                           stats=stats,
                           chart_pie=chart_pie,
                           chart_bar=chart_bar,
                           chart_line=chart_line,
                           recent_records=recent_records)


# ═══════════════════════════════════════════════════════════════════════
# ADMIN - TEACHER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════
@main.route('/admin/teachers', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_teachers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        department = request.form.get('department', '').strip()

        if not all([name, email, password, department]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('main.manage_teachers'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return redirect(url_for('main.manage_teachers'))

        try:
            user = User(name=name, email=email,
                        password_hash=hash_password(password), role='teacher')
            db.session.add(user)
            db.session.flush()
            teacher = Teacher(user_id=user.user_id, department=department)
            db.session.add(teacher)
            db.session.commit()
            flash(f'Teacher {name} added successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('main.manage_teachers'))

    teachers_query = (db.session.query(Teacher, User)
                .join(User, Teacher.user_id == User.user_id).all())
    teachers_list = []
    for teacher, user in teachers_query:
        teachers_list.append({
            'id': teacher.teacher_id,
            'name': user.name,
            'email': user.email,
            'dept': teacher.department
        })
    return render_template('manage_teachers.html', teachers=teachers_list)


@main.route('/admin/teachers/<int:teacher_id>/edit', methods=['POST'])
@login_required
@role_required('admin')
def edit_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    user = User.query.get(teacher.user_id)
    user.name = request.form.get('name', user.name).strip()
    user.email = request.form.get('email', user.email).strip()
    teacher.department = request.form.get('department', teacher.department).strip()
    new_pw = request.form.get('password', '').strip()
    if new_pw:
        user.password_hash = hash_password(new_pw)
    try:
        db.session.commit()
        flash('Teacher updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_teachers'))


@main.route('/admin/teachers/<int:teacher_id>/delete', methods=['POST', 'GET'])
@login_required
@role_required('admin')
def delete_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    user = User.query.get(teacher.user_id)
    try:
        first_other = Teacher.query.filter(Teacher.teacher_id != teacher.teacher_id).first()
        fallback_id = first_other.teacher_id if first_other else None
        Subject.query.filter_by(teacher_id=teacher.teacher_id).update({'teacher_id': fallback_id})
        db.session.delete(teacher)
        if user:
            db.session.delete(user)
        db.session.commit()
        flash('Teacher deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_teachers'))


# ═══════════════════════════════════════════════════════════════════════
# ADMIN - STUDENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════
@main.route('/admin/students', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_students():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        roll_number = request.form.get('roll_number', '').strip()
        class_id = request.form.get('class_id')
        department = request.form.get('department', '').strip()

        if not all([name, email, password, roll_number, class_id, department]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('main.manage_students'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
            return redirect(url_for('main.manage_students'))

        try:
            user = User(name=name, email=email,
                        password_hash=hash_password(password), role='student')
            db.session.add(user)
            db.session.flush()
            student = Student(user_id=user.user_id, roll_number=roll_number,
                              class_id=int(class_id), department=department)
            db.session.add(student)
            db.session.flush()

            # Auto-enroll in all existing subjects so student is ready for all teacher rosters
            subjects = Subject.query.all()
            for subj in subjects:
                db.session.add(Enrollment(student_id=student.student_id, subject_id=subj.subject_id))

            db.session.commit()
            flash(f'Student {name} added successfully and enrolled.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('main.manage_students'))

    students_query = (db.session.query(Student, User)
                .join(User, Student.user_id == User.user_id).all())
    students_list = []
    for student, user in students_query:
        records = Attendance.query.filter_by(student_id=student.student_id).all()
        total = len(records)
        present = sum(1 for r in records if r.status in ('present', 'late'))
        pct = round((present / total * 100), 1) if total > 0 else 0
        cls = Class.query.get(student.class_id)
        students_list.append({
            'id': student.student_id,
            'roll': student.roll_number,
            'name': user.name,
            'email': user.email,
            'class': cls.class_name if cls else 'N/A',
            'class_id': student.class_id,
            'dept': student.department,
            'att': pct
        })

    classes = Class.query.all()
    return render_template('manage_students.html', students=students_list, classes=classes)


@main.route('/admin/students/<int:student_id>/edit', methods=['POST'])
@login_required
@role_required('admin')
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    user = User.query.get(student.user_id)
    user.name = request.form.get('name', user.name).strip()
    user.email = request.form.get('email', user.email).strip()
    student.roll_number = request.form.get('roll_number', student.roll_number).strip()
    student.class_id = int(request.form.get('class_id', student.class_id))
    student.department = request.form.get('department', student.department).strip()
    new_pw = request.form.get('password', '').strip()
    if new_pw:
        user.password_hash = hash_password(new_pw)
    try:
        db.session.commit()
        flash('Student updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_students'))


@main.route('/admin/students/<int:student_id>/delete', methods=['POST', 'GET'])
@login_required
@role_required('admin')
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    user = User.query.get(student.user_id)
    try:
        Attendance.query.filter_by(student_id=student.student_id).delete()
        Enrollment.query.filter_by(student_id=student.student_id).delete()
        db.session.delete(student)
        if user:
            db.session.delete(user)
        db.session.commit()
        flash('Student deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_students'))


# ═══════════════════════════════════════════════════════════════════════
# ADMIN - CLASS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════
@main.route('/save_class', methods=['GET', 'POST'])
@main.route('/admin/classes', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_classes():
    if request.method == 'POST':
        class_name = request.form.get('name', '').strip() or request.form.get('class_name', '').strip()
        semester = request.form.get('sem', '').strip() or request.form.get('semester', '').strip() or '1'
        department = request.form.get('dept', '').strip() or request.form.get('department', '').strip() or 'General'
        if not class_name:
            flash('Class name is required.', 'danger')
            return redirect(url_for('main.manage_classes'))
        try:
            sem_num = int(''.join(filter(str.isdigit, semester)) or 1)
            cls = Class(class_name=class_name, semester=sem_num, department=department)
            db.session.add(cls)
            db.session.commit()
            flash(f'Class {class_name} created.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('main.manage_classes'))

    classes_list = []
    for cls in Class.query.all():
        count = Student.query.filter_by(class_id=cls.class_id).count()
        classes_list.append({
            'id': cls.class_id,
            'name': cls.class_name,
            'sem': f'Semester {cls.semester}',
            'dept': cls.department,
            'count': count
        })
    return render_template('manage_classes.html', classes=classes_list)


@main.route('/admin/classes/<int:class_id>/edit', methods=['POST'])
@login_required
@role_required('admin')
def edit_class(class_id):
    cls = Class.query.get_or_404(class_id)
    cls.class_name = request.form.get('class_name', '').strip() or request.form.get('name', cls.class_name).strip()
    sem_str = request.form.get('semester', '').strip() or request.form.get('sem', str(cls.semester)).strip()
    cls.semester = int(''.join(filter(str.isdigit, sem_str)) or 1)
    cls.department = request.form.get('department', '').strip() or request.form.get('dept', cls.department).strip()
    try:
        db.session.commit()
        flash('Class updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_classes'))


@main.route('/admin/classes/<int:class_id>/delete', methods=['POST', 'GET'])
@login_required
@role_required('admin')
def delete_class(class_id):
    cls = Class.query.get_or_404(class_id)
    try:
        Attendance.query.filter_by(class_id=cls.class_id).delete()
        students = Student.query.filter_by(class_id=cls.class_id).all()
        fallback_class = Class.query.filter(Class.class_id != cls.class_id).first()
        for s in students:
            if fallback_class:
                s.class_id = fallback_class.class_id
            else:
                Attendance.query.filter_by(student_id=s.student_id).delete()
                Enrollment.query.filter_by(student_id=s.student_id).delete()
                user = User.query.get(s.user_id)
                db.session.delete(s)
                if user:
                    db.session.delete(user)
        db.session.delete(cls)
        db.session.commit()
        flash('Class deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_classes'))


# ═══════════════════════════════════════════════════════════════════════
# ADMIN - SUBJECT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════
@main.route('/save_subject', methods=['GET', 'POST'])
@main.route('/admin/subjects', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_subjects():
    if request.method == 'POST':
        subject_name = request.form.get('name', '').strip() or request.form.get('subject_name', '').strip()
        subject_code = request.form.get('code', '').strip() or request.form.get('subject_code', '').strip()
        teacher_id = request.form.get('teacher_id')
        if not teacher_id:
            first_t = Teacher.query.first()
            teacher_id = first_t.teacher_id if first_t else 1

        if not all([subject_name, subject_code]):
            flash('Subject name and code are required.', 'danger')
            return redirect(url_for('main.manage_subjects'))
        try:
            subj = Subject(subject_name=subject_name, subject_code=subject_code,
                           teacher_id=int(teacher_id))
            db.session.add(subj)
            db.session.flush()
            # Auto-enroll all existing students in this subject
            all_students = Student.query.all()
            for st in all_students:
                db.session.add(Enrollment(student_id=st.student_id, subject_id=subj.subject_id))
            db.session.commit()
            flash(f'Subject {subject_name} created.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('main.manage_subjects'))

    subjects_list = []
    for subj in Subject.query.all():
        teacher = Teacher.query.get(subj.teacher_id)
        teacher_user = User.query.get(teacher.user_id) if teacher else None
        enrolled = Enrollment.query.filter_by(subject_id=subj.subject_id).count()
        subjects_list.append({
            'id': subj.subject_id,
            'code': subj.subject_code,
            'name': subj.subject_name,
            'teacher': teacher_user.name if teacher_user else 'Unassigned',
            'enrolled': enrolled
        })

    teachers = (db.session.query(Teacher, User)
                .join(User, Teacher.user_id == User.user_id).all())
    return render_template('manage_subjects.html', subjects=subjects_list, teachers=teachers)


@main.route('/admin/subjects/<int:subject_id>/edit', methods=['POST'])
@login_required
@role_required('admin')
def edit_subject(subject_id):
    subj = Subject.query.get_or_404(subject_id)
    subj.subject_name = request.form.get('name', subj.subject_name).strip()
    subj.subject_code = request.form.get('code', subj.subject_code).strip()
    if request.form.get('teacher_id'):
        subj.teacher_id = int(request.form.get('teacher_id'))
    try:
        db.session.commit()
        flash('Subject updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_subjects'))


@main.route('/admin/subjects/<int:subject_id>/delete', methods=['POST', 'GET'])
@login_required
@role_required('admin')
def delete_subject(subject_id):
    subj = Subject.query.get_or_404(subject_id)
    try:
        Attendance.query.filter_by(subject_id=subj.subject_id).delete()
        Enrollment.query.filter_by(subject_id=subj.subject_id).delete()
        db.session.delete(subj)
        db.session.commit()
        flash('Subject deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('main.manage_subjects'))


# ═══════════════════════════════════════════════════════════════════════
# TEACHER - CLASSES & MARK ATTENDANCE
# ═══════════════════════════════════════════════════════════════════════
@main.route('/teacher/classes')
@login_required
@role_required('teacher')
def teacher_classes():
    return redirect(url_for('main.teacher_dashboard'))


@main.route('/teacher/students')
@login_required
@role_required('teacher')
def teacher_students():
    class_id = request.args.get('class') or request.args.get('class_id')
    if class_id and class_id.isdigit():
        target_class = Class.query.get(int(class_id))
    else:
        target_class = Class.query.first()

    students = Student.query.filter_by(class_id=target_class.class_id).all() if target_class else []
    return render_template('manage_students.html', students=[{
        'id': s.student_id,
        'roll': s.roll_number,
        'name': User.query.get(s.user_id).name,
        'email': User.query.get(s.user_id).email,
        'class': target_class.class_name if target_class else '',
        'dept': s.department,
        'att': 85
    } for s in students], classes=Class.query.all())


@main.route('/api/class/<int:class_id>/students', methods=['GET'])
@login_required
def api_class_students(class_id):
    """Return JSON roster of students enrolled in this class."""
    students = Student.query.filter_by(class_id=class_id).all()
    roster = []
    for s in students:
        u = User.query.get(s.user_id)
        roster.append({
            'student_id': s.student_id,
            'roll_number': s.roll_number,
            'name': u.name if u else 'Student',
            'department': s.department
        })
    return jsonify(students=roster, total=len(roster))


@main.route('/teacher/mark_attendance', methods=['GET', 'POST'])
@main.route('/teacher/attendance/mark/<int:subject_id>', methods=['GET', 'POST'])
@login_required
@role_required('teacher', 'admin')
def mark_attendance(subject_id=None):
    teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
    subjects = Subject.query.filter_by(teacher_id=teacher.teacher_id).all() if teacher else []
    if not subjects:
        subjects = Subject.query.all()

    if not subjects:
        flash('No subjects found in the system. Please ask an Admin to create subjects.', 'warning')
        return redirect(url_for('main.teacher_dashboard'))

    if subject_id is None:
        subj_req = request.args.get('subject') or request.args.get('subject_id')
        if subj_req and subj_req.isdigit():
            subject = Subject.query.get(int(subj_req)) or subjects[0]
        else:
            subject = subjects[0]
    else:
        subject = Subject.query.get(subject_id) or subjects[0]

    all_classes = Class.query.all()
    class_id_req = request.args.get('class') or request.args.get('class_id')
    if class_id_req and class_id_req.isdigit():
        target_class = Class.query.get(int(class_id_req)) or (all_classes[0] if all_classes else None)
    else:
        target_class = all_classes[0] if all_classes else None

    today_str = request.args.get('date') or datetime.date.today().strftime('%Y-%m-%d')
    try:
        query_date = datetime.date.fromisoformat(today_str)
    except ValueError:
        query_date = datetime.date.today()

    if target_class:
        students_query = (db.session.query(Student, User)
                          .join(User, Student.user_id == User.user_id)
                          .filter(Student.class_id == target_class.class_id)
                          .order_by(Student.roll_number.asc()).all())
    else:
        students_query = (db.session.query(Student, User)
                          .join(User, Student.user_id == User.user_id)
                          .order_by(Student.roll_number.asc()).all())

    students_list = []
    for st, u in students_query:
        existing_att = Attendance.query.filter_by(
            student_id=st.student_id,
            subject_id=subject.subject_id,
            attendance_date=query_date
        ).first()
        students_list.append({
            'id': st.student_id,
            'roll': st.roll_number,
            'name': u.name,
            'status': existing_att.status if existing_att else 'present'
        })

    if request.method == 'POST':
        date_str = request.form.get('date', today_str)
        try:
            att_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            att_date = datetime.date.today()

        marked_count = 0
        for s in students_list:
            s_id = s['id']
            status_val = request.form.get(f'status_{s_id}', 'present').lower()
            if status_val not in ('present', 'absent', 'late', 'excused'):
                status_val = 'present'

            student_obj = Student.query.get(s_id)
            existing = Attendance.query.filter_by(
                student_id=s_id,
                subject_id=subject.subject_id,
                attendance_date=att_date
            ).first()

            if existing:
                existing.status = status_val
                existing.marked_by = g.current_user.user_id
                existing.updated_at = datetime.datetime.utcnow()
            else:
                att = Attendance(
                    student_id=s_id,
                    subject_id=subject.subject_id,
                    class_id=student_obj.class_id if student_obj else (target_class.class_id if target_class else 1),
                    attendance_date=att_date,
                    status=status_val,
                    marked_by=g.current_user.user_id
                )
                db.session.add(att)
            marked_count += 1

        db.session.commit()
        flash(f'Attendance recorded for {marked_count} students.', 'success')
        return redirect(url_for('main.mark_attendance', class_id=target_class.class_id if target_class else 1, subject_id=subject.subject_id, date=date_str))

    class_info = {
        'id': target_class.class_id if target_class else 1,
        'name': target_class.class_name if target_class else 'Class'
    }
    subject_info = {
        'id': subject.subject_id,
        'name': subject.subject_name
    }

    return render_template('mark_attendance.html',
                           classes=all_classes,
                           subjects=subjects,
                           current_class_id=target_class.class_id if target_class else 1,
                           current_subject_id=subject.subject_id,
                           class_info=class_info,
                           subject_info=subject_info,
                           today_date=today_str,
                           students=students_list)


# ═══════════════════════════════════════════════════════════════════════
# TEACHER - AI IMAGE & LIVE CAMERA SCANNING ATTENDANCE
# ═══════════════════════════════════════════════════════════════════════
@main.route('/teacher/attendance/scan', methods=['GET'])
@main.route('/attendance/scan', methods=['GET'])
@login_required
@role_required('teacher', 'admin')
def scan_attendance():
    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        subjects = Subject.query.filter_by(teacher_id=teacher.teacher_id).all() if teacher else Subject.query.all()
    else:
        subjects = Subject.query.all()
        
    classes = Class.query.all()
    today_str = datetime.date.today().strftime('%Y-%m-%d')

    return render_template('scan_attendance.html',
                           subjects=subjects,
                           classes=classes,
                           today_date=today_str)


@main.route('/api/teacher/attendance/detect-image', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def api_detect_image_attendance():
    """Detect attendees from an uploaded classroom photo or live webcam capture."""
    file = request.files.get('image')
    if not file:
        return jsonify(error='No image uploaded.'), 400

    class_id = request.form.get('class_id')
    subject_id = request.form.get('subject_id')

    if not class_id or not subject_id:
        return jsonify(error='Please select class and subject.'), 400

    subject = Subject.query.get(int(subject_id))
    cls = Class.query.get(int(class_id))
    if not subject or not cls:
        return jsonify(error='Class or Subject not found.'), 404

    students_query = (db.session.query(Student, User)
                      .join(User, Student.user_id == User.user_id)
                      .filter(Student.class_id == cls.class_id).all())

    roster = []
    for st, u in students_query:
        roster.append({
            'student_id': st.student_id,
            'roll_number': st.roll_number,
            'name': u.name
        })

    if not roster:
        return jsonify(error='No students found in this class.'), 400

    image_bytes = file.read()
    mime_type = file.mimetype or 'image/jpeg'

    try:
        detection_result = detect_attendance_from_image(image_bytes, mime_type, roster)
        detection_result['success'] = True
        return jsonify(detection_result)
    except Exception as e:
        return jsonify(error=f'Detection error: {str(e)}', success=False), 500


@main.route('/api/teacher/attendance/submit-scan', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def api_submit_scan_attendance():
    """Submit attendance records generated from AI image or scanner."""
    data = request.get_json() or {}
    class_id = data.get('class_id')
    subject_id = data.get('subject_id')
    date_str = data.get('date') or datetime.date.today().strftime('%Y-%m-%d')
    records = data.get('attendance') or data.get('records') or []

    if not class_id or not subject_id or not records:
        return jsonify(error='Missing required attendance payload.', success=False), 400

    try:
        att_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        att_date = datetime.date.today()

    saved_count = 0
    for item in records:
        s_id = item.get('student_id')
        status_val = (item.get('status') or 'present').lower()
        if status_val not in ('present', 'absent', 'late', 'excused'):
            status_val = 'present'

        existing = Attendance.query.filter_by(
            student_id=s_id,
            subject_id=int(subject_id),
            attendance_date=att_date
        ).first()

        if existing:
            existing.status = status_val
            existing.marked_by = g.current_user.user_id
            existing.updated_at = datetime.datetime.utcnow()
        else:
            att = Attendance(
                student_id=s_id,
                subject_id=int(subject_id),
                class_id=int(class_id),
                attendance_date=att_date,
                status=status_val,
                marked_by=g.current_user.user_id
            )
            db.session.add(att)
        saved_count += 1

    db.session.commit()
    return jsonify(success=True, saved_count=saved_count, message=f'Attendance recorded for {saved_count} students.')


@main.route('/api/teacher/attendance/scan-code', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def api_scan_code():
    """Live QR/Barcode scanner instant check-in."""
    data = request.get_json() or {}
    code = data.get('code', '').strip()
    class_id = data.get('class_id')
    subject_id = data.get('subject_id')
    date_str = data.get('date') or datetime.date.today().strftime('%Y-%m-%d')

    if not code:
        return jsonify(error='No code scanned.'), 400

    student = None
    if code.isdigit():
        student = Student.query.get(int(code))
    if not student:
        student = Student.query.filter(func.lower(Student.roll_number) == code.lower()).first()

    if not student:
        return jsonify(error=f'Student "{code}" not found.'), 404

    user = User.query.get(student.user_id)
    try:
        att_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        att_date = datetime.date.today()

    if subject_id:
        existing = Attendance.query.filter_by(
            student_id=student.student_id,
            subject_id=int(subject_id),
            attendance_date=att_date
        ).first()

        if existing:
            existing.status = 'present'
            existing.marked_by = g.current_user.user_id
            existing.updated_at = datetime.datetime.utcnow()
        else:
            att = Attendance(
                student_id=student.student_id,
                subject_id=int(subject_id),
                class_id=student.class_id,
                attendance_date=att_date,
                status='present',
                marked_by=g.current_user.user_id
            )
            db.session.add(att)
        db.session.commit()

    return jsonify({
        'success': True,
        'student_id': student.student_id,
        'roll_number': student.roll_number,
        'name': user.name if user else 'Student',
        'status': 'present',
        'message': f'✓ {user.name if user else student.roll_number} marked Present'
    })


# ═══════════════════════════════════════════════════════════════════════
# ATTENDANCE HISTORY (Teacher & Admin)
# ═══════════════════════════════════════════════════════════════════════
@main.route('/attendance/history')
@main.route('/admin/history')
@main.route('/teacher/history')
@login_required
@role_required('admin', 'teacher')
def attendance_history():
    date_from = request.args.get('date_start', '') or request.args.get('date_from', '')
    date_to = request.args.get('date_end', '') or request.args.get('date_to', '')
    class_name_or_id = request.args.get('class', '') or request.args.get('class_id', '')
    subject_id = request.args.get('subject_id', '')
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = Attendance.query

    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        if teacher:
            subject_ids = [s.subject_id for s in Subject.query.filter_by(teacher_id=teacher.teacher_id).all()]
            query = query.filter(Attendance.subject_id.in_(subject_ids))

    if date_from:
        try:
            query = query.filter(Attendance.attendance_date >= datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Attendance.attendance_date <= datetime.date.fromisoformat(date_to))
        except ValueError:
            pass
    if class_name_or_id:
        if class_name_or_id.isdigit():
            query = query.filter_by(class_id=int(class_name_or_id))
        else:
            cls = Class.query.filter_by(class_name=class_name_or_id).first()
            if cls:
                query = query.filter_by(class_id=cls.class_id)
    if subject_id:
        query = query.filter_by(subject_id=int(subject_id))
    if status_filter:
        query = query.filter_by(status=status_filter.lower())

    total = query.count()
    records_db = (query.order_by(Attendance.attendance_date.desc(), Attendance.created_at.desc())
               .offset((page - 1) * per_page).limit(per_page).all())

    records_list = []
    for r in records_db:
        student = Student.query.get(r.student_id)
        user = User.query.get(student.user_id) if student else None
        subj = Subject.query.get(r.subject_id)
        cls = Class.query.get(r.class_id)
        marker = User.query.get(r.marked_by)
        records_list.append({
            'id': r.attendance_id,
            'date': r.attendance_date.strftime('%Y-%m-%d'),
            'name': user.name if user else 'Unknown',
            'roll': student.roll_number if student else '',
            'class': cls.class_name if cls else '',
            'subject': subj.subject_name if subj else '',
            'status': r.status.capitalize(),
            'teacher': marker.name if marker else 'Teacher'
        })

    classes = Class.query.all()
    subjects = Subject.query.all()
    total_pages = (total + per_page - 1) // per_page

    return render_template('attendance_history.html', records=records_list,
                           classes=classes, subjects=subjects,
                           page=page, total_pages=total_pages, total=total)


# ═══════════════════════════════════════════════════════════════════════
# ATTENDANCE ANALYTICS
# ═══════════════════════════════════════════════════════════════════════
@main.route('/attendance/analytics')
@main.route('/admin/analytics')
@login_required
@role_required('admin', 'teacher')
def attendance_analytics():
    classes = Class.query.all()
    subjects = Subject.query.all()
    return render_template('attendance_analytics.html', classes=classes, subjects=subjects)


# ═══════════════════════════════════════════════════════════════════════
# STUDENT VIEWS
# ═══════════════════════════════════════════════════════════════════════
@main.route('/student/attendance')
@login_required
@role_required('student')
def student_attendance():
    student = Student.query.filter_by(user_id=g.current_user.user_id).first()
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('main.login'))

    records = Attendance.query.filter_by(student_id=student.student_id).order_by(
        Attendance.attendance_date.desc()).all()
    enrollments = Enrollment.query.filter_by(student_id=student.student_id).all()

    subjects_list = []
    for enr in enrollments:
        subj = Subject.query.get(enr.subject_id)
        if not subj:
            continue
        sub_records = [r for r in records if r.subject_id == subj.subject_id]
        sub_total = len(sub_records)
        sub_present = sum(1 for r in sub_records if r.status in ('present', 'late'))
        sub_pct = round((sub_present / sub_total * 100), 1) if sub_total > 0 else 0
        subjects_list.append({
            'name': subj.subject_name,
            'pct': sub_pct,
            'attended': sub_present,
            'total': sub_total
        })

    records_list = []
    for r in records[:30]:
        subj = Subject.query.get(r.subject_id)
        marker = User.query.get(r.marked_by)
        records_list.append({
            'date': r.attendance_date.strftime('%Y-%m-%d'),
            'subject': subj.subject_name if subj else 'Subject',
            'teacher': marker.name if marker else 'Teacher',
            'status': r.status.capitalize()
        })

    return render_template('student_attendance.html', subjects=subjects_list, records=records_list)


@main.route('/profile')
@main.route('/student/profile')
@main.route('/teacher/profile')
@login_required
def profile():
    profile_data = {}
    if g.current_user.role == 'student':
        student = Student.query.filter_by(user_id=g.current_user.user_id).first()
        if student:
            cls = Class.query.get(student.class_id)
            records = Attendance.query.filter_by(student_id=student.student_id).all()
            total = len(records)
            present = sum(1 for r in records if r.status in ('present', 'late'))
            pct = round((present / total * 100), 1) if total > 0 else 0
            profile_data = {
                'roll_number': student.roll_number,
                'class_name': cls.class_name if cls else 'N/A',
                'department': student.department,
                'overall_att': f'{pct}%'
            }
    elif g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        if teacher:
            sub_count = Subject.query.filter_by(teacher_id=teacher.teacher_id).count()
            profile_data = {
                'department': teacher.department,
                'subjects_count': sub_count
            }
    return render_template('profile.html', profile_data=profile_data)


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════
@main.route('/reports')
@main.route('/admin/reports')
@main.route('/teacher/reports')
@login_required
@role_required('admin', 'teacher')
def reports():
    classes = Class.query.all()
    subjects = Subject.query.all()
    students_list = (db.session.query(Student, User)
                     .join(User, Student.user_id == User.user_id).all())
    return render_template('reports.html', classes=classes, subjects=subjects,
                           students_list=students_list)


# ═══════════════════════════════════════════════════════════════════════
# AI ASSISTANT PAGE
# ═══════════════════════════════════════════════════════════════════════
@main.route('/ai-assistant')
@main.route('/ai/assistant')
@login_required
def ai_assistant():
    return render_template('ai_assistant.html')


# ═══════════════════════════════════════════════════════════════════════
# SETTINGS (Admin)
# ═══════════════════════════════════════════════════════════════════════
@main.route('/settings', methods=['GET', 'POST'])
@main.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def settings():
    if request.method == 'POST':
        threshold = request.form.get('threshold', '75')
        current_app.config['ATTENDANCE_THRESHOLD'] = int(''.join(filter(str.isdigit, threshold)) or 75)
        flash('Settings updated successfully.', 'success')
    threshold = current_app.config.get('ATTENDANCE_THRESHOLD', 75)
    settings_data = {
        'threshold': threshold,
        'school_name': 'Modern Academy'
    }
    return render_template('settings.html', settings=settings_data, threshold=threshold)


# ═══════════════════════════════════════════════════════════════════════
# CHANGE PASSWORD
# ═══════════════════════════════════════════════════════════════════════
@main.route('/profile/password', methods=['POST'])
@main.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    if not check_password(current_pw, g.current_user.password_hash):
        flash('Current password is incorrect.', 'danger')
    elif new_pw and confirm_pw and new_pw != confirm_pw:
        flash('New passwords do not match.', 'danger')
    elif len(new_pw) < 6:
        flash('Password must be at least 6 characters.', 'danger')
    else:
        g.current_user.password_hash = hash_password(new_pw)
        db.session.commit()
        flash('Password changed successfully.', 'success')

    return redirect(url_for('main.profile'))


# ═══════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════
@main.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    """Dashboard statistics for charts and widgets."""
    today = datetime.date.today()

    total_students = Student.query.count()
    total_teachers = Teacher.query.count()
    total_classes = Class.query.count()

    all_records = Attendance.query.all()
    total_att = len(all_records)
    total_present = sum(1 for r in all_records if r.status in ('present', 'late'))
    overall_attendance = round((total_present / total_att * 100), 1) if total_att > 0 else 0

    stats = {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_classes': total_classes,
        'overall_attendance': overall_attendance
    }

    # Bar chart (attendance by class)
    classes = Class.query.all()
    bar_labels = []
    bar_data = []
    for cls in classes:
        c_records = [r for r in all_records if r.class_id == cls.class_id]
        c_total = len(c_records)
        c_present = sum(1 for r in c_records if r.status in ('present', 'late'))
        c_pct = round((c_present / c_total * 100), 1) if c_total > 0 else 0
        bar_labels.append(cls.class_name)
        bar_data.append(c_pct)

    # Pie chart (today's breakdown, fallback to all records)
    today_records = [r for r in all_records if r.attendance_date == today]
    target_records = today_records if len(today_records) > 0 else all_records
    pie_data = [
        sum(1 for r in target_records if r.status == 'present'),
        sum(1 for r in target_records if r.status == 'absent'),
        sum(1 for r in target_records if r.status == 'late'),
        sum(1 for r in target_records if r.status == 'excused'),
    ]

    # Line chart (Monthly trend)
    monthly = {}
    for r in all_records:
        key = r.attendance_date.strftime('%b %Y')
        if key not in monthly:
            monthly[key] = {'total': 0, 'present': 0}
        monthly[key]['total'] += 1
        if r.status in ('present', 'late'):
            monthly[key]['present'] += 1
    line_labels = list(monthly.keys())
    line_data = [round(v['present'] / v['total'] * 100, 1) if v['total'] > 0 else 0 for v in monthly.values()]

    # Recent records
    recent_objs = sorted(all_records, key=lambda r: (r.attendance_date, r.created_at), reverse=True)[:10]
    recent = []
    status_colors = {'present': 'success', 'absent': 'danger', 'late': 'warning', 'excused': 'info'}
    for r in recent_objs:
        st = Student.query.get(r.student_id)
        u = User.query.get(st.user_id) if st else None
        cls = Class.query.get(r.class_id)
        recent.append({
            'date': r.attendance_date.strftime('%Y-%m-%d'),
            'name': u.name if u else 'Student',
            'cls': cls.class_name if cls else 'Class',
            'status': r.status.capitalize(),
            'color': status_colors.get(r.status, 'primary')
        })

    # Alerts (students below threshold)
    threshold = int(current_app.config.get('ATTENDANCE_THRESHOLD', 75))
    low_list = _get_low_attendance_students(threshold)
    alerts = []
    for l in low_list[:6]:
        alerts.append({
            'name': l['student_name'],
            'cls': l['class_name'],
            'att': f"{l['percentage']}%"
        })

    return jsonify({
        'stats': stats,
        'bar_labels': bar_labels,
        'bar_data': bar_data,
        'pie_data': pie_data,
        'line_labels': line_labels,
        'line_data': line_data,
        'recent': recent,
        'alerts': alerts,
        'class_stats': [{'name': bar_labels[i], 'percentage': bar_data[i]} for i in range(len(bar_labels))],
        'today_stats': {'present': pie_data[0], 'absent': pie_data[1], 'late': pie_data[2], 'excused': pie_data[3]},
        'monthly_trend': [{'month': line_labels[i], 'percentage': line_data[i]} for i in range(len(line_labels))]
    })


@main.route('/api/attendance/analytics')
@login_required
def api_attendance_analytics():
    """Detailed analytics data."""
    class_id = request.args.get('class_id')
    subject_id = request.args.get('subject_id')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = Attendance.query

    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        if teacher:
            sub_ids = [s.subject_id for s in Subject.query.filter_by(teacher_id=teacher.teacher_id).all()]
            query = query.filter(Attendance.subject_id.in_(sub_ids))

    if class_id and class_id.isdigit():
        query = query.filter_by(class_id=int(class_id))
    if subject_id and subject_id.isdigit():
        query = query.filter_by(subject_id=int(subject_id))
    if date_from:
        try:
            query = query.filter(Attendance.attendance_date >= datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Attendance.attendance_date <= datetime.date.fromisoformat(date_to))
        except ValueError:
            pass

    records = query.all()
    total = len(records)
    present = sum(1 for r in records if r.status in ('present', 'late'))
    avg_pct = round((present / total * 100), 1) if total > 0 else 0

    status_dist = {
        'present': sum(1 for r in records if r.status == 'present'),
        'absent': sum(1 for r in records if r.status == 'absent'),
        'late': sum(1 for r in records if r.status == 'late'),
        'excused': sum(1 for r in records if r.status == 'excused'),
    }

    subject_wise = {}
    for r in records:
        sid = r.subject_id
        if sid not in subject_wise:
            subj = Subject.query.get(sid)
            subject_wise[sid] = {
                'name': subj.subject_name if subj else 'Unknown',
                'total': 0, 'present': 0
            }
        subject_wise[sid]['total'] += 1
        if r.status in ('present', 'late'):
            subject_wise[sid]['present'] += 1

    subject_data = []
    for sid, data in subject_wise.items():
        pct = round((data['present'] / data['total'] * 100), 1) if data['total'] > 0 else 0
        subject_data.append({'name': data['name'], 'percentage': pct, 'total': data['total']})

    day_analysis = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    day_totals = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    for r in records:
        dow = r.attendance_date.weekday()
        day_totals[dow] += 1
        if r.status == 'absent':
            day_analysis[dow] += 1
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    day_data = []
    for i in range(7):
        absence_rate = round((day_analysis[i] / day_totals[i] * 100), 1) if day_totals[i] > 0 else 0
        day_data.append({'day': day_names[i], 'absence_rate': absence_rate})

    threshold = int(current_app.config.get('ATTENDANCE_THRESHOLD', 75))
    low_students = _get_low_attendance_students(threshold)

    best = max(subject_data, key=lambda x: x['percentage']) if subject_data else None
    worst = min(subject_data, key=lambda x: x['percentage']) if subject_data else None

    return jsonify({
        'total_records': total,
        'avg_percentage': avg_pct,
        'status_distribution': status_dist,
        'subject_wise': subject_data,
        'day_analysis': day_data,
        'low_students': low_students,
        'best_subject': best,
        'worst_subject': worst
    })


@main.route('/api/ai/chat', methods=['POST'])
@login_required
def api_ai_chat():
    """AI assistant chat endpoint."""
    data = request.get_json() or {}
    question = data.get('question', '').strip() or data.get('message', '').strip()
    if not question:
        return jsonify(error='Please enter a question.', reply='Please enter a question.'), 400

    try:
        user_context = {
            'user_id': g.current_user.user_id,
            'role': g.current_user.role,
            'name': g.current_user.name
        }

        if g.current_user.role == 'student':
            student = Student.query.filter_by(user_id=g.current_user.user_id).first()
            if student:
                user_context['student_id'] = student.student_id
        elif g.current_user.role == 'teacher':
            teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
            if teacher:
                user_context['teacher_id'] = teacher.teacher_id

        db_context = build_db_context(g.current_user, db.session)
        response_text = get_ai_response(question, user_context, db_context)
        return jsonify(reply=response_text, response=response_text)
    except Exception as e:
        return jsonify(error=str(e), reply=f"Error: {str(e)}"), 500


@main.route('/api/ai/insights')
@login_required
@role_required('admin', 'teacher')
def api_ai_insights():
    """AI-generated attendance insights."""
    class_id = request.args.get('class_id')
    try:
        insights = generate_ai_insights(db.session, class_id=class_id)
        return jsonify(insights=insights)
    except Exception as e:
        return jsonify(error=str(e)), 500


@main.route('/api/reports/generate')
@login_required
@role_required('admin', 'teacher')
def api_generate_report():
    """Generate comprehensive report data by type, class, subject, and date range."""
    report_type = request.args.get('type', 'class_summary')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    class_id = request.args.get('class_id', '')
    subject_id = request.args.get('subject_id', '')
    student_id = request.args.get('student_id', '')

    query = Attendance.query

    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        if teacher:
            sub_ids = [s.subject_id for s in Subject.query.filter_by(teacher_id=teacher.teacher_id).all()]
            query = query.filter(Attendance.subject_id.in_(sub_ids))

    if date_from:
        try:
            query = query.filter(Attendance.attendance_date >= datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Attendance.attendance_date <= datetime.date.fromisoformat(date_to))
        except ValueError:
            pass
    if class_id and class_id.isdigit():
        query = query.filter_by(class_id=int(class_id))
    if subject_id and subject_id.isdigit():
        query = query.filter_by(subject_id=int(subject_id))
    if student_id and student_id.isdigit():
        query = query.filter_by(student_id=int(student_id))

    records = query.order_by(Attendance.attendance_date.desc()).all()

    # Individual records
    raw_records = []
    for r in records:
        student = Student.query.get(r.student_id)
        user = User.query.get(student.user_id) if student else None
        subj = Subject.query.get(r.subject_id)
        cls = Class.query.get(r.class_id)
        raw_records.append({
            'date': r.attendance_date.isoformat(),
            'student_name': user.name if user else 'Unknown',
            'roll_number': student.roll_number if student else '',
            'class': cls.class_name if cls else '',
            'class_id': r.class_id,
            'subject': subj.subject_name if subj else '',
            'subject_id': r.subject_id,
            'status': r.status.capitalize()
        })

    # Class summary aggregation
    class_summary = []
    classes_target = Class.query.filter_by(class_id=int(class_id)).all() if (class_id and class_id.isdigit()) else Class.query.order_by(Class.class_name).all()
    for c in classes_target:
        c_records = [r for r in records if r.class_id == c.class_id]
        c_students = Student.query.filter_by(class_id=c.class_id).count()
        c_total = len(c_records)
        c_present = sum(1 for r in c_records if r.status in ('present', 'late'))
        c_absent = sum(1 for r in c_records if r.status == 'absent')
        c_late = sum(1 for r in c_records if r.status == 'late')
        c_pct = round((c_present / c_total * 100), 1) if c_total > 0 else 0
        class_summary.append({
            'class_id': c.class_id,
            'class_name': c.class_name,
            'department': c.department,
            'semester': c.semester,
            'student_count': c_students,
            'total_records': c_total,
            'present_count': c_present,
            'absent_count': c_absent,
            'late_count': c_late,
            'percentage': c_pct
        })

    # Subject summary aggregation
    subject_summary = []
    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        subj_query = Subject.query.filter_by(teacher_id=teacher.teacher_id) if teacher else Subject.query
    else:
        subj_query = Subject.query
    if subject_id and subject_id.isdigit():
        subj_query = subj_query.filter_by(subject_id=int(subject_id))
    subjects_target = subj_query.order_by(Subject.subject_name).all()

    for s in subjects_target:
        s_records = [r for r in records if r.subject_id == s.subject_id]
        t = Teacher.query.get(s.teacher_id) if s.teacher_id else None
        tu = User.query.get(t.user_id) if t else None
        s_total = len(s_records)
        s_present = sum(1 for r in s_records if r.status in ('present', 'late'))
        s_absent = sum(1 for r in s_records if r.status == 'absent')
        s_pct = round((s_present / s_total * 100), 1) if s_total > 0 else 0
        subject_summary.append({
            'subject_id': s.subject_id,
            'subject_code': s.subject_code,
            'subject_name': s.subject_name,
            'teacher': tu.name if tu else 'Unassigned',
            'total_records': s_total,
            'present_count': s_present,
            'absent_count': s_absent,
            'percentage': s_pct
        })

    # Student summary & defaulters
    student_summary = []
    defaulters = []
    threshold = int(current_app.config.get('ATTENDANCE_THRESHOLD', 75))

    st_query = Student.query
    if class_id and class_id.isdigit():
        st_query = st_query.filter_by(class_id=int(class_id))
    if student_id and student_id.isdigit():
        st_query = st_query.filter_by(student_id=int(student_id))
    students_target = st_query.all()

    for st in students_target:
        st_records = [r for r in records if r.student_id == st.student_id]
        u = User.query.get(st.user_id)
        c = Class.query.get(st.class_id)
        st_total = len(st_records)
        st_present = sum(1 for r in st_records if r.status in ('present', 'late'))
        st_absent = sum(1 for r in st_records if r.status == 'absent')
        st_pct = round((st_present / st_total * 100), 1) if st_total > 0 else 0
        entry = {
            'student_id': st.student_id,
            'student_name': u.name if u else 'Unknown',
            'roll_number': st.roll_number,
            'class_name': c.class_name if c else 'N/A',
            'department': st.department,
            'total_records': st_total,
            'present_count': st_present,
            'absent_count': st_absent,
            'percentage': st_pct,
            'is_defaulter': st_pct < threshold and st_total > 0
        }
        student_summary.append(entry)
        if entry['is_defaulter']:
            defaulters.append(entry)

    return jsonify({
        'success': True,
        'report_type': report_type,
        'total_records': len(records),
        'records': raw_records,
        'class_summary': class_summary,
        'subject_summary': subject_summary,
        'student_summary': student_summary,
        'defaulters': defaulters
    })


@main.route('/api/reports/export/<fmt>')
@login_required
@role_required('admin', 'teacher')
def api_export_report(fmt):
    """Export report as CSV or printable PDF/HTML."""
    report_type = request.args.get('type', 'class_summary')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    class_id = request.args.get('class_id', '')
    subject_id = request.args.get('subject_id', '')
    student_id = request.args.get('student_id', '')

    query = Attendance.query
    if g.current_user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
        if teacher:
            sub_ids = [s.subject_id for s in Subject.query.filter_by(teacher_id=teacher.teacher_id).all()]
            query = query.filter(Attendance.subject_id.in_(sub_ids))

    if date_from:
        try:
            query = query.filter(Attendance.attendance_date >= datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Attendance.attendance_date <= datetime.date.fromisoformat(date_to))
        except ValueError:
            pass
    if class_id and class_id.isdigit():
        query = query.filter_by(class_id=int(class_id))
    if subject_id and subject_id.isdigit():
        query = query.filter_by(subject_id=int(subject_id))
    if student_id and student_id.isdigit():
        query = query.filter_by(student_id=int(student_id))

    records = query.order_by(Attendance.attendance_date.desc()).all()

    # Build rows based on report_type
    if report_type == 'class_summary':
        rows = [['Class Name', 'Department', 'Semester', 'Total Records', 'Present', 'Absent', 'Attendance %']]
        classes_target = Class.query.filter_by(class_id=int(class_id)).all() if (class_id and class_id.isdigit()) else Class.query.order_by(Class.class_name).all()
        for c in classes_target:
            c_records = [r for r in records if r.class_id == c.class_id]
            c_total = len(c_records)
            c_present = sum(1 for r in c_records if r.status in ('present', 'late'))
            c_absent = sum(1 for r in c_records if r.status == 'absent')
            c_pct = round((c_present / c_total * 100), 1) if c_total > 0 else 0
            rows.append([c.class_name, c.department, f'Sem {c.semester}', c_total, c_present, c_absent, f'{c_pct}%'])

    elif report_type == 'subject_wise':
        rows = [['Subject Code', 'Subject Name', 'Teacher', 'Total Records', 'Present', 'Absent', 'Attendance %']]
        if g.current_user.role == 'teacher':
            teacher = Teacher.query.filter_by(user_id=g.current_user.user_id).first()
            subj_query = Subject.query.filter_by(teacher_id=teacher.teacher_id) if teacher else Subject.query
        else:
            subj_query = Subject.query
        if subject_id and subject_id.isdigit():
            subj_query = subj_query.filter_by(subject_id=int(subject_id))
        for s in subj_query.order_by(Subject.subject_name).all():
            s_records = [r for r in records if r.subject_id == s.subject_id]
            t = Teacher.query.get(s.teacher_id) if s.teacher_id else None
            tu = User.query.get(t.user_id) if t else None
            s_total = len(s_records)
            s_present = sum(1 for r in s_records if r.status in ('present', 'late'))
            s_absent = sum(1 for r in s_records if r.status == 'absent')
            s_pct = round((s_present / s_total * 100), 1) if s_total > 0 else 0
            rows.append([s.subject_code, s.subject_name, tu.name if tu else 'Unassigned', s_total, s_present, s_absent, f'{s_pct}%'])

    elif report_type == 'student_detailed':
        rows = [['Student Name', 'Roll Number', 'Class', 'Department', 'Total Records', 'Attended', 'Missed', 'Attendance %']]
        st_query = Student.query
        if class_id and class_id.isdigit():
            st_query = st_query.filter_by(class_id=int(class_id))
        for st in st_query.order_by(Student.roll_number).all():
            st_records = [r for r in records if r.student_id == st.student_id]
            u = User.query.get(st.user_id)
            c = Class.query.get(st.class_id)
            st_total = len(st_records)
            st_present = sum(1 for r in st_records if r.status in ('present', 'late'))
            st_absent = sum(1 for r in st_records if r.status == 'absent')
            st_pct = round((st_present / st_total * 100), 1) if st_total > 0 else 0
            rows.append([u.name if u else 'Unknown', st.roll_number, c.class_name if c else 'N/A', st.department, st_total, st_present, st_absent, f'{st_pct}%'])

    elif report_type == 'defaulters':
        rows = [['Student Name', 'Roll Number', 'Class', 'Total Records', 'Attended', 'Missed', 'Attendance %', 'Alert Status']]
        threshold = int(current_app.config.get('ATTENDANCE_THRESHOLD', 75))
        st_query = Student.query
        if class_id and class_id.isdigit():
            st_query = st_query.filter_by(class_id=int(class_id))
        for st in st_query.order_by(Student.roll_number).all():
            st_records = [r for r in records if r.student_id == st.student_id]
            st_total = len(st_records)
            st_present = sum(1 for r in st_records if r.status in ('present', 'late'))
            st_absent = sum(1 for r in st_records if r.status == 'absent')
            st_pct = round((st_present / st_total * 100), 1) if st_total > 0 else 0
            if st_pct < threshold and st_total > 0:
                u = User.query.get(st.user_id)
                c = Class.query.get(st.class_id)
                rows.append([u.name if u else 'Unknown', st.roll_number, c.class_name if c else 'N/A', st_total, st_present, st_absent, f'{st_pct}%', f'Below {threshold}%'])

    else: # daily attendance log
        rows = [['Date', 'Student Name', 'Roll Number', 'Class', 'Subject', 'Status']]
        for r in records:
            student = Student.query.get(r.student_id)
            user = User.query.get(student.user_id) if student else None
            subj = Subject.query.get(r.subject_id)
            cls = Class.query.get(r.class_id)
            rows.append([
                r.attendance_date.isoformat(),
                user.name if user else 'Unknown',
                student.roll_number if student else '',
                cls.class_name if cls else '',
                subj.subject_name if subj else '',
                r.status.capitalize()
            ])

    if fmt == 'csv':
        si = StringIO()
        writer = csv.writer(si)
        writer.writerows(rows)
        return Response(
            si.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=attendance_report_{report_type}.csv'}
        )
    elif fmt == 'pdf':
        title = report_type.replace('_', ' ').title()
        gen_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        html = f"""<!DOCTYPE html><html><head><title>{title} Report</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 30px; color: #1e293b; }}
            .header {{ border-bottom: 2px solid #3b82f6; padding-bottom: 12px; margin-bottom: 20px; }}
            .header h1 {{ margin: 0 0 5px 0; font-size: 24px; color: #1e293b; }}
            .header p {{ margin: 0; color: #64748b; font-size: 13px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
            th, td {{ border: 1px solid #cbd5e1; padding: 10px 12px; text-align: left; }}
            th {{ background: #f1f5f9; color: #1e293b; font-weight: 600; }}
            tr:nth-child(even) {{ background: #f8fafc; }}
            .footer {{ margin-top: 30px; font-size: 11px; color: #94a3b8; text-align: right; }}
            @media print {{ body {{ margin: 0; }} }}
        </style></head><body>
        <div class="header">
            <h1>Classroom Attendance Assistant — {title}</h1>
            <p>Generated: {gen_time} • Generated By: {g.current_user.name} ({g.current_user.role.capitalize()})</p>
        </div>
        <table><thead><tr>"""
        for h in rows[0]:
            html += f'<th>{h}</th>'
        html += '</tr></thead><tbody>'
        for row in rows[1:]:
            html += '<tr>'
            for cell in row:
                html += f'<td>{cell}</td>'
            html += '</tr>'
        html += f'</tbody></table><div class="footer">Total Records: {len(rows)-1}</div></body></html>'
        return Response(html, mimetype='text/html',
                        headers={'Content-Disposition': f'inline; filename=attendance_report_{report_type}.html'})
    else:
        return jsonify(error='Unsupported format. Use csv or pdf.'), 400


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════
def _get_low_attendance_students(threshold=75):
    """Get students with attendance below threshold."""
    students = Student.query.all()
    low = []
    for student in students:
        records = Attendance.query.filter_by(student_id=student.student_id).all()
        total = len(records)
        if total == 0:
            continue
        present = sum(1 for r in records if r.status in ('present', 'late'))
        pct = round((present / total * 100), 1)
        if pct < threshold:
            user = User.query.get(student.user_id)
            cls = Class.query.get(student.class_id)
            low.append({
                'student_name': user.name if user else 'Unknown',
                'roll_number': student.roll_number,
                'class_name': cls.class_name if cls else '',
                'percentage': pct
            })
    return sorted(low, key=lambda x: x['percentage'])
