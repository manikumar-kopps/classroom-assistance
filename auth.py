import os
import datetime
from functools import wraps
from flask import session, redirect, url_for, g, current_app, flash, request
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from models import User

def get_jwt_secret():
    return current_app.config.get('JWT_SECRET', os.environ.get('JWT_SECRET', 'default-secret-key'))

def hash_password(password):
    return generate_password_hash(password)

def check_password(password, hashed_password):
    return check_password_hash(hashed_password, password)

def generate_token(user_id, role):
    payload = {
        'user_id': user_id,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm='HS256')

def decode_token(token):
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = session.get('token')
        if not token:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('main.login', next=request.url))
        
        payload = decode_token(token)
        if not payload:
            flash('Session expired or invalid. Please log in again.', 'warning')
            session.pop('token', None)
            return redirect(url_for('main.login', next=request.url))
        
        user = User.query.get(payload['user_id'])
        if not user:
            flash('User not found. Please log in again.', 'warning')
            session.pop('token', None)
            return redirect(url_for('main.login', next=request.url))
        
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if g.current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                if g.current_user.role == 'admin':
                    return redirect(url_for('main.admin_dashboard'))
                elif g.current_user.role == 'teacher':
                    return redirect(url_for('main.teacher_dashboard'))
                elif g.current_user.role == 'student':
                    return redirect(url_for('main.student_dashboard'))
                else:
                    return redirect(url_for('main.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
