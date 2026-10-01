import random
from datetime import datetime, timedelta, date
from models import db, User, Student, Teacher, Class, Subject, Enrollment, Attendance
from auth import hash_password

def seed_database():
    print("Clearing old data and starting database seeding...")
    db.drop_all()
    db.create_all()

    # 1. Admin
    admin_user = User(
        name='System Administrator',
        email='admin@school.edu',
        password_hash=hash_password('admin123'),
        role='admin'
    )
    db.session.add(admin_user)
    db.session.flush()

    # 2. Classes
    classes_data = [
        ('MCA-A', 1, 'Computer Applications'),
        ('MCA-B', 2, 'Computer Applications'),
        ('MCA-C', 3, 'Computer Applications'),
        ('MCA-D', 4, 'Computer Applications'),
    ]
    created_classes = []
    for c_name, sem, dept in classes_data:
        c = Class(class_name=c_name, semester=sem, department=dept)
        db.session.add(c)
        created_classes.append(c)
    db.session.flush()

    # 3. Teachers
    teachers_info = [
        ('Dr. Robert Chen', 'teacher1@school.edu', 'Computer Applications'),
        ('Prof. Sarah Jenkins', 'teacher2@school.edu', 'Computer Applications'),
        ('Dr. Michael Patel', 'teacher3@school.edu', 'Computer Applications'),
        ('Dr. Robert Chen (Alt)', 'robert.chen@school.edu', 'Computer Applications'),
    ]
    created_teachers = []
    for idx, (t_name, t_email, t_dept) in enumerate(teachers_info, 1):
        u = User(
            name=t_name,
            email=t_email,
            password_hash=hash_password(f'teacher123'),
            role='teacher'
        )
        db.session.add(u)
        db.session.flush()
        t = Teacher(user_id=u.user_id, department=t_dept)
        db.session.add(t)
        created_teachers.append(t)
    db.session.flush()

    # 4. Subjects
    subjects_info = [
        ('Python Programming', 'CS101', created_teachers[0].teacher_id),
        ('Data Structures & Algorithms', 'CS102', created_teachers[1].teacher_id),
        ('Database Management Systems', 'CS103', created_teachers[2].teacher_id),
        ('Machine Learning Foundations', 'CS104', created_teachers[0].teacher_id),
        ('Web Application Development', 'CS105', created_teachers[1].teacher_id),
        ('Computer Networks', 'CS106', created_teachers[2].teacher_id),
    ]
    created_subjects = []
    for s_name, s_code, t_id in subjects_info:
        s = Subject(subject_name=s_name, subject_code=s_code, teacher_id=t_id)
        db.session.add(s)
        created_subjects.append(s)
    db.session.flush()

    # 5. Students (20 students distributed among classes)
    first_names = ['John', 'Emma', 'David', 'Sophia', 'James', 'Olivia', 'Daniel', 'Ava', 'Alex', 'Mia',
                   'Ethan', 'Isabella', 'Liam', 'Charlotte', 'Noah', 'Amelia', 'Lucas', 'Harper', 'Mason', 'Evelyn']
    last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Miller', 'Davis', 'Wilson', 'Anderson', 'Taylor',
                  'Thomas', 'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez']

    created_students = []
    for i in range(20):
        s_name = f"{first_names[i]} {last_names[i]}"
        s_email = f"student{i+1}@school.edu"
        assigned_class = created_classes[i % len(created_classes)]
        roll = f"2024MCA{101 + i}"

        u = User(
            name=s_name,
            email=s_email,
            password_hash=hash_password('student123'),
            role='student'
        )
        db.session.add(u)
        db.session.flush()

        student = Student(
            user_id=u.user_id,
            roll_number=roll,
            class_id=assigned_class.class_id,
            department='Computer Applications'
        )
        db.session.add(student)
        created_students.append(student)
    db.session.flush()

    # 6. Enrollments (Enroll students in subjects)
    for student in created_students:
        # Enroll in 4 to 6 subjects
        chosen_subjects = random.sample(created_subjects, k=random.randint(4, 6))
        for subj in chosen_subjects:
            enr = Enrollment(student_id=student.student_id, subject_id=subj.subject_id)
            db.session.add(enr)
    db.session.flush()

    # 7. Realistic Attendance Records over the past 45 school days
    today = date.today()
    all_enrollments = Enrollment.query.all()
    statuses = ['present', 'absent', 'late', 'excused']

    # Pre-assign individual attendance attendance trends (some high attendance, a few below 75%)
    student_bias = {}
    for st in created_students:
        # Make ~3 students deliberately below 75% for testing alerts
        if st.student_id in [created_students[1].student_id, created_students[4].student_id, created_students[8].student_id]:
            student_bias[st.student_id] = [0.60, 0.30, 0.05, 0.05]
        else:
            student_bias[st.student_id] = [0.85, 0.08, 0.05, 0.02]

    # Map subject -> teacher user_id
    subject_teacher_map = {}
    for subj in created_subjects:
        teacher = Teacher.query.get(subj.teacher_id)
        subject_teacher_map[subj.subject_id] = teacher.user_id if teacher else admin_user.user_id

    # Create dates for last 45 calendar days (excluding weekends)
    past_dates = []
    for d in range(45, -1, -1):
        target_date = today - timedelta(days=d)
        if target_date.weekday() < 5:  # Monday to Friday
            past_dates.append(target_date)

    attendance_records = []
    for att_date in past_dates:
        for enr in all_enrollments:
            student = Student.query.get(enr.student_id)
            weights = student_bias.get(student.student_id, [0.85, 0.08, 0.05, 0.02])
            
            # Monday slight dip in attendance
            if att_date.weekday() == 0:
                weights = [weights[0] - 0.08, weights[1] + 0.06, weights[2] + 0.02, weights[3]]
                weights = [max(0.01, w) for w in weights]
                s = sum(weights)
                weights = [w / s for w in weights]

            status = random.choices(statuses, weights=weights)[0]
            marker_user_id = subject_teacher_map.get(enr.subject_id, admin_user.user_id)

            att = Attendance(
                student_id=enr.student_id,
                subject_id=enr.subject_id,
                class_id=student.class_id,
                attendance_date=att_date,
                status=status,
                marked_by=marker_user_id
            )
            attendance_records.append(att)

    # Bulk add attendance
    db.session.bulk_save_objects(attendance_records)
    db.session.commit()

    print("Database seeding completed successfully!")
    print(f"Created {len(created_classes)} classes, {len(created_teachers)} teachers, {len(created_students)} students, {len(created_subjects)} subjects, and {len(attendance_records)} attendance records.")

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_database()
