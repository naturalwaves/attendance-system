from flask import Flask, render_template_string, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import csv
import io
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    resumption_time = db.Column(db.String(5), default='08:00')
    closing_time = db.Column(db.String(5), default='17:00')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True)
    attendance = db.relationship('Attendance', backref='school', lazy=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    school = db.relationship('School', backref='users')

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(50), default='')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance = db.relationship('Attendance', backref='staff', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime)
    sign_out_time = db.Column(db.DateTime)
    is_late = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_styles():
    return '''
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f6f9; min-height: 100vh; }
            
            /* Top Navigation */
            .top-nav {
                background: linear-gradient(135deg, #800000, #a00000);
                color: white;
                padding: 0;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 1000;
                height: 60px;
            }
            .nav-container {
                max-width: 1400px;
                margin: 0 auto;
                display: flex;
                justify-content: space-between;
                align-items: center;
                height: 100%;
                padding: 0 20px;
            }
            .nav-brand {
                display: flex;
                align-items: center;
                gap: 15px;
                font-size: 1.3rem;
                font-weight: bold;
            }
            .nav-brand img {
                height: 45px;
                width: auto;
            }
            .nav-menu {
                display: flex;
                align-items: center;
                gap: 5px;
            }
            .nav-menu a, .nav-dropdown .dropdown-btn {
                color: white;
                text-decoration: none;
                padding: 8px 16px;
                border-radius: 6px;
                transition: all 0.3s;
                font-size: 0.9rem;
                display: flex;
                align-items: center;
                gap: 8px;
                background: none;
                border: none;
                cursor: pointer;
                font-family: inherit;
            }
            .nav-menu a:hover, .nav-dropdown .dropdown-btn:hover {
                background: rgba(255,255,255,0.2);
            }
            .nav-menu a.active {
                background: rgba(255,255,255,0.25);
            }
            .nav-dropdown {
                position: relative;
            }
            .dropdown-content {
                display: none;
                position: absolute;
                top: 100%;
                right: 0;
                background: white;
                min-width: 180px;
                box-shadow: 0 8px 16px rgba(0,0,0,0.15);
                border-radius: 8px;
                overflow: hidden;
                z-index: 1001;
            }
            .nav-dropdown:hover .dropdown-content {
                display: block;
            }
            .dropdown-content a {
                color: #333 !important;
                padding: 12px 16px;
                display: flex;
                align-items: center;
                gap: 10px;
                border-radius: 0;
            }
            .dropdown-content a:hover {
                background: #f5f5f5 !important;
            }
            
            /* Main Content */
            .main-content {
                margin-top: 60px;
                padding: 30px;
                max-width: 1400px;
                margin-left: auto;
                margin-right: auto;
            }
            
            /* Cards */
            .card {
                background: white;
                border-radius: 12px;
                padding: 25px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                margin-bottom: 25px;
            }
            .card h2 {
                color: #800000;
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #f0f0f0;
            }
            
            /* Stats Grid */
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: white;
                border-radius: 12px;
                padding: 25px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                border-left: 5px solid #800000;
            }
            .stat-card.green { border-left-color: #28a745; }
            .stat-card.blue { border-left-color: #007bff; }
            .stat-card.yellow { border-left-color: #ffc107; }
            .stat-card.red { border-left-color: #dc3545; }
            .stat-card h3 {
                font-size: 0.9rem;
                color: #666;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .stat-card .number {
                font-size: 2.2rem;
                font-weight: bold;
                color: #800000;
            }
            .stat-card.green .number { color: #28a745; }
            .stat-card.blue .number { color: #007bff; }
            .stat-card.yellow .number { color: #ffc107; }
            .stat-card.red .number { color: #dc3545; }
            .stat-card small {
                color: #888;
                font-size: 0.8rem;
            }
            
            /* Tables */
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }
            th, td {
                padding: 14px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }
            th {
                background: #800000;
                color: white;
                font-weight: 600;
            }
            tr:hover {
                background: #f8f9fa;
            }
            
            /* Forms */
            .form-group {
                margin-bottom: 20px;
            }
            .form-group label {
                display: block;
                margin-bottom: 8px;
                font-weight: 600;
                color: #333;
            }
            .form-group input, .form-group select, .form-group textarea {
                width: 100%;
                padding: 12px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                font-size: 1rem;
                transition: border-color 0.3s;
            }
            .form-group input:focus, .form-group select:focus {
                outline: none;
                border-color: #800000;
            }
            
            /* Buttons */
            .btn {
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 0.95rem;
                font-weight: 600;
                transition: all 0.3s;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                text-decoration: none;
            }
            .btn-primary {
                background: linear-gradient(135deg, #800000, #a00000);
                color: white;
            }
            .btn-primary:hover {
                background: linear-gradient(135deg, #600000, #800000);
                transform: translateY(-2px);
            }
            .btn-success {
                background: #28a745;
                color: white;
            }
            .btn-success:hover {
                background: #218838;
            }
            .btn-danger {
                background: #dc3545;
                color: white;
            }
            .btn-danger:hover {
                background: #c82333;
            }
            .btn-secondary {
                background: #6c757d;
                color: white;
            }
            .btn-warning {
                background: #ffc107;
                color: #333;
            }
            .btn-sm {
                padding: 6px 12px;
                font-size: 0.85rem;
            }
            
            /* Filter Bar */
            .filter-bar {
                display: flex;
                gap: 15px;
                margin-bottom: 20px;
                flex-wrap: wrap;
                align-items: end;
            }
            .filter-bar .form-group {
                margin-bottom: 0;
            }
            .filter-bar label {
                font-size: 0.85rem;
                margin-bottom: 5px;
            }
            .filter-bar input, .filter-bar select {
                padding: 10px;
                min-width: 150px;
            }
            
            /* Status Badges */
            .status {
                padding: 5px 12px;
                border-radius: 20px;
                font-size: 0.85rem;
                font-weight: 600;
            }
            .status.signed-in { background: #d4edda; color: #155724; }
            .status.signed-out { background: #cce5ff; color: #004085; }
            .status.absent { background: #f8d7da; color: #721c24; }
            .status.na { background: #e9ecef; color: #6c757d; }
            .status.active { background: #d4edda; color: #155724; }
            .status.inactive { background: #f8d7da; color: #721c24; }
            
            /* Alerts */
            .alert {
                padding: 15px 20px;
                border-radius: 8px;
                margin-bottom: 20px;
            }
            .alert-success {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .alert-danger {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            .alert-info {
                background: #d1ecf1;
                color: #0c5460;
                border: 1px solid #bee5eb;
            }
            
            /* Login Page */
            .login-container {
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #800000, #a00000);
            }
            .login-box {
                background: white;
                padding: 50px;
                border-radius: 16px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                width: 100%;
                max-width: 420px;
            }
            .login-box h1 {
                color: #800000;
                margin-bottom: 10px;
                text-align: center;
            }
            .login-box .subtitle {
                color: #666;
                margin-bottom: 30px;
                text-align: center;
            }
            .login-logo {
                text-align: center;
                margin-bottom: 25px;
            }
            .login-logo img {
                height: 80px;
                width: auto;
            }
            
            /* Actions */
            .actions {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            
            /* Checkbox styling */
            .checkbox-group {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .checkbox-group input[type="checkbox"] {
                width: 18px;
                height: 18px;
            }
            
            /* Reset Section */
            .reset-section {
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin-top: 20px;
            }
            .reset-section h4 {
                color: #856404;
                margin-bottom: 15px;
            }
            .reset-section .btn {
                margin-right: 10px;
                margin-bottom: 10px;
            }
        </style>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    '''

def get_nav(active=''):
    if not current_user.is_authenticated:
        return ''
    
    school_filter_disabled = '' if current_user.is_super_admin else 'disabled'
    
    return f'''
        <nav class="top-nav">
            <div class="nav-container">
                <div class="nav-brand">
                    <img src="https://i.ibb.co/PGPKP3HB/corona-logo-2.png" alt="Logo">
                    <span>Attendance System</span>
                </div>
                <div class="nav-menu">
                    <a href="/dashboard" class="{'active' if active == 'dashboard' else ''}">
                        <i class="fas fa-chart-line"></i> Dashboard
                    </a>
                    <a href="/schools" class="{'active' if active == 'schools' else ''}">
                        <i class="fas fa-school"></i> Schools
                    </a>
                    <a href="/staff" class="{'active' if active == 'staff' else ''}">
                        <i class="fas fa-users"></i> Staff
                    </a>
                    <a href="/bulk-upload" class="{'active' if active == 'bulk-upload' else ''}">
                        <i class="fas fa-file-upload"></i> Bulk Upload
                    </a>
                    <div class="nav-dropdown">
                        <button class="dropdown-btn">
                            <i class="fas fa-file-alt"></i> Reports <i class="fas fa-caret-down"></i>
                        </button>
                        <div class="dropdown-content">
                            <a href="/attendance"><i class="fas fa-calendar-check"></i> Attendance</a>
                            <a href="/late-report"><i class="fas fa-clock"></i> Late Staff</a>
                            <a href="/absent-report"><i class="fas fa-user-times"></i> Absent Staff</a>
                            <a href="/overtime-report"><i class="fas fa-business-time"></i> Overtime</a>
                        </div>
                    </div>
                    <div class="nav-dropdown">
                        <button class="dropdown-btn">
                            <i class="fas fa-cog"></i> Admin <i class="fas fa-caret-down"></i>
                        </button>
                        <div class="dropdown-content">
                            <a href="/admins"><i class="fas fa-user-shield"></i> Manage Admins</a>
                            <a href="/settings"><i class="fas fa-sliders-h"></i> Settings</a>
                            <a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a>
                        </div>
                    </div>
                </div>
            </div>
        </nav>
    '''

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'danger')
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            <div class="login-container">
                <div class="login-box">
                    <div class="login-logo">
                        <img src="https://i.ibb.co/PGPKP3HB/corona-logo-2.png" alt="Corona Schools Logo">
                    </div>
                    <h1>Welcome Back</h1>
                    <p class="subtitle">Staff Attendance Management System</p>
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    <form method="POST">
                        <div class="form-group">
                            <label><i class="fas fa-user"></i> Username</label>
                            <input type="text" name="username" required placeholder="Enter username">
                        </div>
                        <div class="form-group">
                            <label><i class="fas fa-lock"></i> Password</label>
                            <input type="password" name="password" required placeholder="Enter password">
                        </div>
                        <button type="submit" class="btn btn-primary" style="width: 100%;">
                            <i class="fas fa-sign-in-alt"></i> Login
                        </button>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_super_admin:
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    school_ids = [s.id for s in schools]
    today = datetime.now().date()
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    # Get today's attendance
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == today
    ).all()
    
    signed_in_ids = [a.staff_id for a in today_attendance if a.sign_in_time]
    late_count = len([a for a in today_attendance if a.is_late])
    
    # Absent count (exclude Management)
    all_active_staff = Staff.query.filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True,
        Staff.department != 'Management'
    ).all()
    absent_count = len([s for s in all_active_staff if s.id not in signed_in_ids])
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Dashboard - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('dashboard') + '''
            <div class="main-content">
                <h1 style="margin-bottom: 25px; color: #333;">
                    <i class="fas fa-chart-line"></i> Dashboard
                </h1>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <h3><i class="fas fa-school"></i> Total Schools</h3>
                        <div class="number">{{ schools|length }}</div>
                    </div>
                    <div class="stat-card blue">
                        <h3><i class="fas fa-users"></i> Total Staff</h3>
                        <div class="number">{{ total_staff }}</div>
                    </div>
                    <div class="stat-card green">
                        <h3><i class="fas fa-check-circle"></i> Signed In Today</h3>
                        <div class="number">{{ signed_in_count }}</div>
                    </div>
                    <div class="stat-card yellow">
                        <h3><i class="fas fa-clock"></i> Late Today</h3>
                        <div class="number">{{ late_count }}</div>
                    </div>
                    <div class="stat-card red">
                        <h3><i class="fas fa-user-times"></i> Absent Today</h3>
                        <div class="number">{{ absent_count }}</div>
                        <small>Excludes Management</small>
                    </div>
                </div>
                
                <div class="card">
                    <h2><i class="fas fa-school"></i> Schools Overview</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>School Name</th>
                                <th>Total Staff</th>
                                <th>Signed In</th>
                                <th>Late</th>
                                <th>Absent</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for school in schools %}
                            <tr>
                                <td>{{ school.name }}</td>
                                <td>{{ school.staff|selectattr('is_active')|list|length }}</td>
                                <td style="color: #28a745; font-weight: bold;">
                                    {{ school.attendance|selectattr('date', 'equalto', today)|selectattr('sign_in_time')|list|length }}
                                </td>
                                <td style="color: #ffc107; font-weight: bold;">
                                    {{ school.attendance|selectattr('date', 'equalto', today)|selectattr('is_late')|list|length }}
                                </td>
                                <td style="color: #dc3545; font-weight: bold;">
                                    {% set signed_in = school.attendance|selectattr('date', 'equalto', today)|selectattr('sign_in_time')|map(attribute='staff_id')|list %}
                                    {% set active_non_mgmt = school.staff|selectattr('is_active')|rejectattr('department', 'equalto', 'Management')|list %}
                                    {{ active_non_mgmt|rejectattr('id', 'in', signed_in)|list|length }}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', schools=schools, total_staff=total_staff, signed_in_count=len(signed_in_ids), 
        late_count=late_count, absent_count=absent_count, today=today)

@app.route('/schools')
@login_required
def schools():
    if current_user.is_super_admin:
        all_schools = School.query.all()
    else:
        all_schools = School.query.filter_by(id=current_user.school_id).all()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Schools - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('schools') + '''
            <div class="main-content">
                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h2 style="margin: 0; border: none; padding: 0;"><i class="fas fa-school"></i> Schools</h2>
                        {% if current_user.is_super_admin %}
                        <a href="/schools/add" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add School
                        </a>
                        {% endif %}
                    </div>
                    
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    
                    <table>
                        <thead>
                            <tr>
                                <th>School Name</th>
                                <th>Address</th>
                                <th>Resumption Time</th>
                                <th>Closing Time</th>
                                <th>API Key</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for school in schools %}
                            <tr>
                                <td><strong>{{ school.name }}</strong></td>
                                <td>{{ school.address or '-' }}</td>
                                <td>{{ school.resumption_time }}</td>
                                <td>{{ school.closing_time }}</td>
                                <td><code style="background: #f4f4f4; padding: 4px 8px; border-radius: 4px; font-size: 0.85rem;">{{ school.api_key[:16] }}...</code></td>
                                <td class="actions">
                                    <a href="/schools/edit/{{ school.id }}" class="btn btn-sm btn-primary">
                                        <i class="fas fa-edit"></i>
                                    </a>
                                    {% if current_user.is_super_admin %}
                                    <a href="/schools/regenerate-key/{{ school.id }}" class="btn btn-sm btn-warning" onclick="return confirm('Regenerate API key? Kiosk will need to be updated.')">
                                        <i class="fas fa-key"></i>
                                    </a>
                                    <a href="/schools/delete/{{ school.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this school? This cannot be undone.')">
                                        <i class="fas fa-trash"></i>
                                    </a>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', schools=all_schools)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school = School(
            name=request.form.get('name'),
            address=request.form.get('address'),
            api_key=secrets.token_hex(32),
            resumption_time=request.form.get('resumption_time', '08:00'),
            closing_time=request.form.get('closing_time', '17:00')
        )
        db.session.add(school)
        db.session.commit()
        flash('School added successfully', 'success')
        return redirect(url_for('schools'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Add School - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('schools') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-plus"></i> Add New School</h2>
                    <form method="POST">
                        <div class="form-group">
                            <label>School Name *</label>
                            <input type="text" name="name" required>
                        </div>
                        <div class="form-group">
                            <label>Address</label>
                            <input type="text" name="address">
                        </div>
                        <div class="form-group">
                            <label>Resumption Time</label>
                            <input type="time" name="resumption_time" value="08:00">
                        </div>
                        <div class="form-group">
                            <label>Closing Time</label>
                            <input type="time" name="closing_time" value="17:00">
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save School
                        </button>
                        <a href="/schools" class="btn btn-secondary">Cancel</a>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''')

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if not current_user.is_super_admin and current_user.school_id != id:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.address = request.form.get('address')
        school.resumption_time = request.form.get('resumption_time', '08:00')
        school.closing_time = request.form.get('closing_time', '17:00')
        db.session.commit()
        flash('School updated successfully', 'success')
        return redirect(url_for('schools'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Edit School - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('schools') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-edit"></i> Edit School</h2>
                    <form method="POST">
                        <div class="form-group">
                            <label>School Name *</label>
                            <input type="text" name="name" value="{{ school.name }}" required>
                        </div>
                        <div class="form-group">
                            <label>Address</label>
                            <input type="text" name="address" value="{{ school.address or '' }}">
                        </div>
                        <div class="form-group">
                            <label>Resumption Time</label>
                            <input type="time" name="resumption_time" value="{{ school.resumption_time }}">
                        </div>
                        <div class="form-group">
                            <label>Closing Time</label>
                            <input type="time" name="closing_time" value="{{ school.closing_time }}">
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Update School
                        </button>
                        <a href="/schools" class="btn btn-secondary">Cancel</a>
                    </form>
                    
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #eee;">
                        <h3>API Key</h3>
                        <p style="margin: 10px 0;">
                            <code style="background: #f4f4f4; padding: 10px; border-radius: 4px; display: block; word-break: break-all;">{{ school.api_key }}</code>
                        </p>
                        <small style="color: #666;">Use this key for kiosk integration</small>
                    </div>
                </div>
            </div>
        </body>
        </html>
    ''', school=school)

@app.route('/schools/delete/<int:id>')
@login_required
def delete_school(id):
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('School deleted successfully', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/regenerate-key/<int:id>')
@login_required
def regenerate_key(id):
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated successfully', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff():
    if current_user.is_super_admin:
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
        if selected_school_id:
            all_staff = Staff.query.filter_by(school_id=selected_school_id).all()
        else:
            all_staff = Staff.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        all_staff = Staff.query.filter_by(school_id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    today = datetime.now().date()
    today_attendance = {a.staff_id: a for a in Attendance.query.filter(
        Attendance.date == today
    ).all()}
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Staff - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('staff') + '''
            <div class="main-content">
                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h2 style="margin: 0; border: none; padding: 0;"><i class="fas fa-users"></i> Staff</h2>
                        <a href="/staff/add" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add Staff
                        </a>
                    </div>
                    
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end;">
                            <div class="form-group">
                                <label>Filter by School</label>
                                <select name="school_id" onchange="this.form.submit()" {{ 'disabled' if not current_user.is_super_admin else '' }}>
                                    <option value="">All Schools</option>
                                    {% for school in schools %}
                                    <option value="{{ school.id }}" {{ 'selected' if selected_school_id == school.id else '' }}>
                                        {{ school.name }}
                                    </option>
                                    {% endfor %}
                                </select>
                            </div>
                        </form>
                    </div>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>Department</th>
                                <th>School</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for s in staff %}
                            <tr>
                                <td><strong>{{ s.staff_id }}</strong></td>
                                <td>{{ s.first_name }} {{ s.last_name }}</td>
                                <td>{{ s.department or '-' }}</td>
                                <td>{{ s.school.name }}</td>
                                <td>
                                    {% if s.department == 'Management' %}
                                        <span class="status na">N/A</span>
                                    {% elif s.id in today_attendance %}
                                        {% if today_attendance[s.id].sign_out_time %}
                                            <span class="status signed-out">Signed Out</span>
                                        {% else %}
                                            <span class="status signed-in">Signed In</span>
                                        {% endif %}
                                    {% else %}
                                        <span class="status absent">Absent</span>
                                    {% endif %}
                                </td>
                                <td class="actions">
                                    <a href="/staff/toggle/{{ s.id }}" class="btn btn-sm {{ 'btn-warning' if s.is_active else 'btn-success' }}">
                                        <i class="fas {{ 'fa-ban' if s.is_active else 'fa-check' }}"></i>
                                    </a>
                                    <a href="/staff/delete/{{ s.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this staff member?')">
                                        <i class="fas fa-trash"></i>
                                    </a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', staff=all_staff, schools=schools, selected_school_id=selected_school_id, today_attendance=today_attendance)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    if current_user.is_super_admin:
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    if request.method == 'POST':
        school_id = request.form.get('school_id') if current_user.is_super_admin else current_user.school_id
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            first_name=request.form.get('first_name'),
            last_name=request.form.get('last_name'),
            department=request.form.get('department', ''),
            school_id=school_id
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully', 'success')
        return redirect(url_for('staff'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Add Staff - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('staff') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-plus"></i> Add New Staff</h2>
                    <form method="POST">
                        {% if current_user.is_super_admin %}
                        <div class="form-group">
                            <label>School *</label>
                            <select name="school_id" required>
                                <option value="">Select School</option>
                                {% for school in schools %}
                                <option value="{{ school.id }}">{{ school.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="form-group">
                            <label>Staff ID *</label>
                            <input type="text" name="staff_id" required>
                        </div>
                        <div class="form-group">
                            <label>First Name *</label>
                            <input type="text" name="first_name" required>
                        </div>
                        <div class="form-group">
                            <label>Last Name *</label>
                            <input type="text" name="last_name" required>
                        </div>
                        <div class="form-group">
                            <label>Department</label>
                            <input type="text" name="department" placeholder="e.g. Teaching, Admin, Management">
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Staff
                        </button>
                        <a href="/staff" class="btn btn-secondary">Cancel</a>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''', schools=schools)

@app.route('/staff/toggle/<int:id>')
@login_required
def toggle_staff(id):
    staff_member = Staff.query.get_or_404(id)
    
    if not current_user.is_super_admin and current_user.school_id != staff_member.school_id:
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    staff_member.is_active = not staff_member.is_active
    db.session.commit()
    status = 'activated' if staff_member.is_active else 'deactivated'
    flash(f'Staff {status} successfully', 'success')
    return redirect(url_for('staff'))

@app.route('/staff/delete/<int:id>')
@login_required
def delete_staff(id):
    staff_member = Staff.query.get_or_404(id)
    
    if not current_user.is_super_admin and current_user.school_id != staff_member.school_id:
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    db.session.delete(staff_member)
    db.session.commit()
    flash('Staff deleted successfully', 'success')
    return redirect(url_for('staff'))

@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    if current_user.is_super_admin:
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    if request.method == 'POST':
        school_id = request.form.get('school_id') if current_user.is_super_admin else current_user.school_id
        file = request.files.get('file')
        
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file', 'danger')
            return redirect(url_for('bulk_upload'))
        
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            
            count = 0
            for row in reader:
                staff = Staff(
                    staff_id=row.get('ID', row.get('staff_id', '')),
                    first_name=row.get('Firstname', row.get('first_name', '')),
                    last_name=row.get('Surname', row.get('last_name', '')),
                    department=row.get('Department', row.get('department', '')),
                    school_id=school_id
                )
                db.session.add(staff)
                count += 1
            
            db.session.commit()
            flash(f'Successfully uploaded {count} staff records', 'success')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
        
        return redirect(url_for('bulk_upload'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bulk Upload - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('bulk-upload') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-file-upload"></i> Bulk Staff Upload</h2>
                    
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    
                    <form method="POST" enctype="multipart/form-data">
                        {% if current_user.is_super_admin %}
                        <div class="form-group">
                            <label>School *</label>
                            <select name="school_id" required>
                                <option value="">Select School</option>
                                {% for school in schools %}
                                <option value="{{ school.id }}">{{ school.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                        <div class="form-group">
                            <label>CSV File *</label>
                            <input type="file" name="file" accept=".csv" required>
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-upload"></i> Upload
                        </button>
                    </form>
                    
                    <div style="margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 8px;">
                        <h4>CSV Format</h4>
                        <p style="margin: 10px 0;">Your CSV file should have these columns:</p>
                        <code style="display: block; background: #fff; padding: 15px; border-radius: 4px; margin: 10px 0;">
                            Firstname,Surname,ID,Department<br>
                            John,Doe,EMP001,Teaching<br>
                            Jane,Smith,EMP002,Admin
                        </code>
                        <a href="/download-template" class="btn btn-secondary btn-sm" style="margin-top: 10px;">
                            <i class="fas fa-download"></i> Download Template
                        </a>
                    </div>
                </div>
            </div>
        </body>
        </html>
    ''', schools=schools)

@app.route('/download-template')
@login_required
def download_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Firstname', 'Surname', 'ID', 'Department'])
    writer.writerow(['John', 'Doe', 'EMP001', 'Teaching'])
    writer.writerow(['Jane', 'Smith', 'EMP002', 'Admin'])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=staff_template.csv'
    return response

@app.route('/attendance')
@login_required
def attendance():
    if current_user.is_super_admin:
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    query = Attendance.query.filter(
        Attendance.date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
        Attendance.date <= datetime.strptime(date_to, '%Y-%m-%d').date()
    )
    
    if selected_school_id:
        query = query.filter(Attendance.school_id == selected_school_id)
    elif not current_user.is_super_admin:
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.order_by(Attendance.date.desc(), Attendance.sign_in_time.desc()).all()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Attendance - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('attendance') + '''
            <div class="main-content">
                <div class="card">
                    <h2><i class="fas fa-calendar-check"></i> Attendance Records</h2>
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.is_super_admin %}
                            <div class="form-group">
                                <label>School</label>
                                <select name="school_id">
                                    <option value="">All Schools</option>
                                    {% for school in schools %}
                                    <option value="{{ school.id }}" {{ 'selected' if selected_school_id == school.id else '' }}>
                                        {{ school.name }}
                                    </option>
                                    {% endfor %}
                                </select>
                            </div>
                            {% endif %}
                            <div class="form-group">
                                <label>From Date</label>
                                <input type="date" name="date_from" value="{{ date_from }}">
                            </div>
                            <div class="form-group">
                                <label>To Date</label>
                                <input type="date" name="date_to" value="{{ date_to }}">
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-filter"></i> Filter
                            </button>
                            <a href="/attendance?date_from={{ today }}&date_to={{ today }}" class="btn btn-secondary">
                                <i class="fas fa-calendar-day"></i> Today
                            </a>
                            <a href="/attendance/download?school_id={{ selected_school_id or '' }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn btn-success">
                                <i class="fas fa-download"></i> Download CSV
                            </a>
                        </form>
                    </div>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>School</th>
                                <th>Sign In</th>
                                <th>Sign Out</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for record in records %}
                            <tr>
                                <td>{{ record.date.strftime('%Y-%m-%d') }}</td>
                                <td>{{ record.staff.staff_id }}</td>
                                <td>{{ record.staff.first_name }} {{ record.staff.last_name }}</td>
                                <td>{{ record.school.name }}</td>
                                <td>{{ record.sign_in_time.strftime('%H:%M:%S') if record.sign_in_time else '-' }}</td>
                                <td>{{ record.sign_out_time.strftime('%H:%M:%S') if record.sign_out_time else '-' }}</td>
                                <td>
                                    {% if record.is_late %}
                                        <span class="status" style="background: #fff3cd; color: #856404;">Late</span>
                                    {% else %}
                                        <span class="status signed-in">On Time</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', records=records, schools=schools, selected_school_id=selected_school_id,
        date_from=date_from, date_to=date_to, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/attendance/download')
@login_required
def download_attendance():
    school_id = request.args.get('school_id', type=int)
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    query = Attendance.query.filter(
        Attendance.date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
        Attendance.date <= datetime.strptime(date_to, '%Y-%m-%d').date()
    )
    
    if school_id:
        query = query.filter(Attendance.school_id == school_id)
    elif not current_user.is_super_admin:
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Last Name', 'School', 'Sign In', 'Sign Out', 'Late'])
    
    for r in records:
        writer.writerow([
            r.date.strftime('%Y-%m-%d'),
            r.staff.staff_id,
            r.staff.first_name,
            r.staff.last_name,
            r.school.name,
            r.sign_in_time.strftime('%H:%M:%S') if r.sign_in_time else '',
            r.sign_out_time.strftime('%H:%M:%S') if r.sign_out_time else '',
            'Yes' if r.is_late else 'No'
        ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=attendance_{date_from}_to_{date_to}.csv'
    return response

@app.route('/late-report')
@login_required
def late_report():
    if current_user.is_super_admin:
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    # Get all staff for the selected scope
    if selected_school_id:
        staff_query = Staff.query.filter_by(school_id=selected_school_id, is_active=True)
    elif current_user.is_super_admin:
        staff_query = Staff.query.filter_by(is_active=True)
    else:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    
    all_staff = staff_query.all()
    
    # Calculate late statistics for each staff member
    staff_stats = []
    for s in all_staff:
        # Total times late (all time)
        total_late = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
        
        # Total attendance records (all time)
        total_attendance = Attendance.query.filter_by(staff_id=s.id).filter(Attendance.sign_in_time.isnot(None)).count()
        
        # Calculate percentages
        if total_attendance > 0:
            punctuality_pct = round(((total_attendance - total_late) / total_attendance) * 100, 1)
            lateness_pct = round((total_late / total_attendance) * 100, 1)
        else:
            punctuality_pct = 0
            lateness_pct = 0
        
        # Get late records within date range
        late_records = Attendance.query.filter(
            Attendance.staff_id == s.id,
            Attendance.is_late == True,
            Attendance.date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
            Attendance.date <= datetime.strptime(date_to, '%Y-%m-%d').date()
        ).all()
        
        if late_records or request.args.get('show_all'):
            staff_stats.append({
                'staff': s,
                'times_late': total_late,
                'punctuality_pct': punctuality_pct,
                'lateness_pct': lateness_pct,
                'late_records': late_records
            })
    
    # Sort by times late descending
    staff_stats.sort(key=lambda x: x['times_late'], reverse=True)
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Late Staff Report - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('late-report') + '''
            <div class="main-content">
                <div class="card">
                    <h2><i class="fas fa-clock"></i> Late Staff Report</h2>
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.is_super_admin %}
                            <div class="form-group">
                                <label>School</label>
                                <select name="school_id">
                                    <option value="">All Schools</option>
                                    {% for school in schools %}
                                    <option value="{{ school.id }}" {{ 'selected' if selected_school_id == school.id else '' }}>
                                        {{ school.name }}
                                    </option>
                                    {% endfor %}
                                </select>
                            </div>
                            {% endif %}
                            <div class="form-group">
                                <label>From Date</label>
                                <input type="date" name="date_from" value="{{ date_from }}">
                            </div>
                            <div class="form-group">
                                <label>To Date</label>
                                <input type="date" name="date_to" value="{{ date_to }}">
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-filter"></i> Filter
                            </button>
                            <a href="/late-report?date_from={{ today }}&date_to={{ today }}" class="btn btn-secondary">
                                <i class="fas fa-calendar-day"></i> Today
                            </a>
                            <a href="/late-report/download?school_id={{ selected_school_id or '' }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn btn-success">
                                <i class="fas fa-download"></i> Download CSV
                            </a>
                        </form>
                    </div>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>Department</th>
                                <th>School</th>
                                <th>Times Late</th>
                                <th>% Punctuality</th>
                                <th>% Lateness</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for stat in staff_stats %}
                            <tr>
                                <td>{{ stat.staff.staff_id }}</td>
                                <td>{{ stat.staff.first_name }} {{ stat.staff.last_name }}</td>
                                <td>{{ stat.staff.department or '-' }}</td>
                                <td>{{ stat.staff.school.name }}</td>
                                <td><strong style="color: #dc3545;">{{ stat.times_late }}</strong></td>
                                <td><span style="color: #28a745;">{{ stat.punctuality_pct }}%</span></td>
                                <td><span style="color: #dc3545;">{{ stat.lateness_pct }}%</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    
                    {% if current_user.is_super_admin %}
                    <div class="reset-section">
                        <h4><i class="fas fa-exclamation-triangle"></i> Reset Late Counters (Super Admin Only)</h4>
                        <p style="margin-bottom: 15px;">This will reset the late count for all staff. This action cannot be undone.</p>
                        <form method="POST" action="/reset-late-count" style="display: inline;">
                            <input type="hidden" name="scope" value="school">
                            <select name="school_id" required style="padding: 10px; margin-right: 10px;">
                                <option value="">Select School</option>
                                {% for school in schools %}
                                <option value="{{ school.id }}">{{ school.name }}</option>
                                {% endfor %}
                            </select>
                            <button type="submit" class="btn btn-warning" onclick="return confirm('Reset late counters for this school?')">
                                <i class="fas fa-undo"></i> Reset School
                            </button>
                        </form>
                        <form method="POST" action="/reset-late-count" style="display: inline;">
                            <input type="hidden" name="scope" value="all">
                            <button type="submit" class="btn btn-danger" onclick="return confirm('Reset late counters for ALL schools? This cannot be undone!')">
                                <i class="fas fa-undo"></i> Reset All Schools
                            </button>
                        </form>
                    </div>
                    {% endif %}
                </div>
            </div>
        </body>
        </html>
    ''', staff_stats=staff_stats, schools=schools, selected_school_id=selected_school_id,
        date_from=date_from, date_to=date_to, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/reset-late-count', methods=['POST'])
@login_required
def reset_late_count():
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('late_report'))
    
    scope = request.form.get('scope')
    school_id = request.form.get('school_id', type=int)
    
    if scope == 'school' and school_id:
        # Reset late flags for specific school
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        Attendance.query.filter(Attendance.staff_id.in_(staff_ids)).update({Attendance.is_late: False}, synchronize_session=False)
        db.session.commit()
        school = School.query.get(school_id)
        flash(f'Late counters reset for {school.name}', 'success')
    elif scope == 'all':
        # Reset all late flags
        Attendance.query.update({Attendance.is_late: False}, synchronize_session=False)
        db.session.commit()
        flash('Late counters reset for all schools', 'success')
    else:
        flash('Invalid request', 'danger')
    
    return redirect(url_for('late_report'))

@app.route('/late-report/download')
@login_required
def download_late_report():
    school_id = request.args.get('school_id', type=int)
    
    if school_id:
        staff_query = Staff.query.filter_by(school_id=school_id, is_active=True)
    elif current_user.is_super_admin:
        staff_query = Staff.query.filter_by(is_active=True)
    else:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    
    all_staff = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Last Name', 'Department', 'School', 'Times Late', '% Punctuality', '% Lateness'])
    
    for s in all_staff:
        total_late = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
        total_attendance = Attendance.query.filter_by(staff_id=s.id).filter(Attendance.sign_in_time.isnot(None)).count()
        
        if total_attendance > 0:
            punctuality_pct = round(((total_attendance - total_late) / total_attendance) * 100, 1)
            lateness_pct = round((total_late / total_attendance) * 100, 1)
        else:
            punctuality_pct = 0
            lateness_pct = 0
        
        writer.writerow([
            s.staff_id,
            s.first_name,
            s.last_name,
            s.department or '',
            s.school.name,
            total_late,
            f'{punctuality_pct}%',
            f'{lateness_pct}%'
        ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=late_report_{datetime.now().strftime("%Y%m%d")}.csv'
    return response

@app.route('/absent-report')
@login_required
def absent_report():
    if current_user.is_super_admin:
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    # Get all active staff (excluding Management)
    if selected_school_id:
        staff_query = Staff.query.filter(
            Staff.school_id == selected_school_id,
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    elif current_user.is_super_admin:
        staff_query = Staff.query.filter(
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    else:
        staff_query = Staff.query.filter(
            Staff.school_id == current_user.school_id,
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    
    all_staff = staff_query.all()
    
    # Get attendance records within date range
    attendance_records = Attendance.query.filter(
        Attendance.date >= date_from_obj,
        Attendance.date <= date_to_obj
    ).all()
    
    # Create set of (staff_id, date) tuples for signed in staff
    signed_in = set((a.staff_id, a.date) for a in attendance_records if a.sign_in_time)
    
    # Find absent staff for each date
    absent_list = []
    current_date = date_from_obj
    while current_date <= date_to_obj:
        for s in all_staff:
            if (s.id, current_date) not in signed_in:
                absent_list.append({
                    'date': current_date,
                    'staff': s
                })
        current_date += timedelta(days=1)
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Absent Staff Report - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('absent-report') + '''
            <div class="main-content">
                <div class="card">
                    <h2><i class="fas fa-user-times"></i> Absent Staff Report</h2>
                    <p style="color: #666; margin-bottom: 20px;">Excludes Management department</p>
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.is_super_admin %}
                            <div class="form-group">
                                <label>School</label>
                                <select name="school_id">
                                    <option value="">All Schools</option>
                                    {% for school in schools %}
                                    <option value="{{ school.id }}" {{ 'selected' if selected_school_id == school.id else '' }}>
                                        {{ school.name }}
                                    </option>
                                    {% endfor %}
                                </select>
                            </div>
                            {% endif %}
                            <div class="form-group">
                                <label>From Date</label>
                                <input type="date" name="date_from" value="{{ date_from }}">
                            </div>
                            <div class="form-group">
                                <label>To Date</label>
                                <input type="date" name="date_to" value="{{ date_to }}">
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-filter"></i> Filter
                            </button>
                            <a href="/absent-report?date_from={{ today }}&date_to={{ today }}" class="btn btn-secondary">
                                <i class="fas fa-calendar-day"></i> Today
                            </a>
                            <a href="/absent-report/download?school_id={{ selected_school_id or '' }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn btn-success">
                                <i class="fas fa-download"></i> Download CSV
                            </a>
                        </form>
                    </div>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>Department</th>
                                <th>School</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in absent_list %}
                            <tr>
                                <td>{{ item.date.strftime('%Y-%m-%d') }}</td>
                                <td>{{ item.staff.staff_id }}</td>
                                <td>{{ item.staff.first_name }} {{ item.staff.last_name }}</td>
                                <td>{{ item.staff.department or '-' }}</td>
                                <td>{{ item.staff.school.name }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', absent_list=absent_list, schools=schools, selected_school_id=selected_school_id,
        date_from=date_from, date_to=date_to, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/absent-report/download')
@login_required
def download_absent_report():
    school_id = request.args.get('school_id', type=int)
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    if school_id:
        staff_query = Staff.query.filter(
            Staff.school_id == school_id,
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    elif current_user.is_super_admin:
        staff_query = Staff.query.filter(
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    else:
        staff_query = Staff.query.filter(
            Staff.school_id == current_user.school_id,
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    
    all_staff = staff_query.all()
    
    attendance_records = Attendance.query.filter(
        Attendance.date >= date_from_obj,
        Attendance.date <= date_to_obj
    ).all()
    
    signed_in = set((a.staff_id, a.date) for a in attendance_records if a.sign_in_time)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Last Name', 'Department', 'School'])
    
    current_date = date_from_obj
    while current_date <= date_to_obj:
        for s in all_staff:
            if (s.id, current_date) not in signed_in:
                writer.writerow([
                    current_date.strftime('%Y-%m-%d'),
                    s.staff_id,
                    s.first_name,
                    s.last_name,
                    s.department or '',
                    s.school.name
                ])
        current_date += timedelta(days=1)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=absent_report_{date_from}_to_{date_to}.csv'
    return response

@app.route('/overtime-report')
@login_required
def overtime_report():
    if current_user.is_super_admin:
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    query = Attendance.query.filter(
        Attendance.date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
        Attendance.date <= datetime.strptime(date_to, '%Y-%m-%d').date(),
        Attendance.sign_out_time.isnot(None)
    )
    
    if selected_school_id:
        query = query.filter(Attendance.school_id == selected_school_id)
    elif not current_user.is_super_admin:
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.all()
    
    overtime_list = []
    for r in records:
        closing_time = datetime.strptime(r.school.closing_time, '%H:%M').time()
        sign_out_time = r.sign_out_time.time()
        
        if sign_out_time > closing_time:
            closing_dt = datetime.combine(r.date, closing_time)
            signout_dt = datetime.combine(r.date, sign_out_time)
            overtime_minutes = int((signout_dt - closing_dt).total_seconds() / 60)
            overtime_hours = overtime_minutes // 60
            overtime_mins = overtime_minutes % 60
            
            overtime_list.append({
                'record': r,
                'overtime': f'{overtime_hours}h {overtime_mins}m',
                'overtime_minutes': overtime_minutes
            })
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Overtime Report - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('overtime-report') + '''
            <div class="main-content">
                <div class="card">
                    <h2><i class="fas fa-business-time"></i> Overtime Report</h2>
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.is_super_admin %}
                            <div class="form-group">
                                <label>School</label>
                                <select name="school_id">
                                    <option value="">All Schools</option>
                                    {% for school in schools %}
                                    <option value="{{ school.id }}" {{ 'selected' if selected_school_id == school.id else '' }}>
                                        {{ school.name }}
                                    </option>
                                    {% endfor %}
                                </select>
                            </div>
                            {% endif %}
                            <div class="form-group">
                                <label>From Date</label>
                                <input type="date" name="date_from" value="{{ date_from }}">
                            </div>
                            <div class="form-group">
                                <label>To Date</label>
                                <input type="date" name="date_to" value="{{ date_to }}">
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-filter"></i> Filter
                            </button>
                            <a href="/overtime-report?date_from={{ today }}&date_to={{ today }}" class="btn btn-secondary">
                                <i class="fas fa-calendar-day"></i> Today
                            </a>
                            <a href="/overtime-report/download?school_id={{ selected_school_id or '' }}&date_from={{ date_from }}&date_to={{ date_to }}" class="btn btn-success">
                                <i class="fas fa-download"></i> Download CSV
                            </a>
                        </form>
                    </div>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>School</th>
                                <th>Closing Time</th>
                                <th>Sign Out</th>
                                <th>Overtime</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in overtime_list %}
                            <tr>
                                <td>{{ item.record.date.strftime('%Y-%m-%d') }}</td>
                                <td>{{ item.record.staff.staff_id }}</td>
                                <td>{{ item.record.staff.first_name }} {{ item.record.staff.last_name }}</td>
                                <td>{{ item.record.school.name }}</td>
                                <td>{{ item.record.school.closing_time }}</td>
                                <td>{{ item.record.sign_out_time.strftime('%H:%M:%S') }}</td>
                                <td><strong style="color: #28a745;">{{ item.overtime }}</strong></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', overtime_list=overtime_list, schools=schools, selected_school_id=selected_school_id,
        date_from=date_from, date_to=date_to, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/overtime-report/download')
@login_required
def download_overtime_report():
    school_id = request.args.get('school_id', type=int)
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    query = Attendance.query.filter(
        Attendance.date >= datetime.strptime(date_from, '%Y-%m-%d').date(),
        Attendance.date <= datetime.strptime(date_to, '%Y-%m-%d').date(),
        Attendance.sign_out_time.isnot(None)
    )
    
    if school_id:
        query = query.filter(Attendance.school_id == school_id)
    elif not current_user.is_super_admin:
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Last Name', 'School', 'Closing Time', 'Sign Out', 'Overtime'])
    
    for r in records:
        closing_time = datetime.strptime(r.school.closing_time, '%H:%M').time()
        sign_out_time = r.sign_out_time.time()
        
        if sign_out_time > closing_time:
            closing_dt = datetime.combine(r.date, closing_time)
            signout_dt = datetime.combine(r.date, sign_out_time)
            overtime_minutes = int((signout_dt - closing_dt).total_seconds() / 60)
            overtime_hours = overtime_minutes // 60
            overtime_mins = overtime_minutes % 60
            
            writer.writerow([
                r.date.strftime('%Y-%m-%d'),
                r.staff.staff_id,
                r.staff.first_name,
                r.staff.last_name,
                r.school.name,
                r.school.closing_time,
                r.sign_out_time.strftime('%H:%M:%S'),
                f'{overtime_hours}h {overtime_mins}m'
            ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=overtime_report_{date_from}_to_{date_to}.csv'
    return response

@app.route('/admins')
@login_required
def admins():
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    all_users = User.query.all()
    schools = School.query.all()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Manage Admins - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('admins') + '''
            <div class="main-content">
                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h2 style="margin: 0; border: none; padding: 0;"><i class="fas fa-user-shield"></i> Manage Admins</h2>
                        <a href="/admins/add" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add Admin
                        </a>
                    </div>
                    
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Username</th>
                                <th>Role</th>
                                <th>Assigned School</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for user in users %}
                            <tr>
                                <td><strong>{{ user.username }}</strong></td>
                                <td>
                                    {% if user.is_super_admin %}
                                        <span class="status" style="background: #800000; color: white;">Super Admin</span>
                                    {% else %}
                                        <span class="status" style="background: #e9ecef; color: #333;">School Admin</span>
                                    {% endif %}
                                </td>
                                <td>{{ user.school.name if user.school else 'All Schools' }}</td>
                                <td class="actions">
                                    {% if user.id != current_user.id %}
                                    <a href="/admins/delete/{{ user.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this admin?')">
                                        <i class="fas fa-trash"></i>
                                    </a>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
    ''', users=all_users, schools=schools)

@app.route('/admins/add', methods=['GET', 'POST'])
@login_required
def add_admin():
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    schools = School.query.all()
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_super_admin = request.form.get('is_super_admin') == 'on'
        school_id = request.form.get('school_id') if not is_super_admin else None
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('add_admin'))
        
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            is_super_admin=is_super_admin,
            school_id=school_id
        )
        db.session.add(user)
        db.session.commit()
        flash('Admin added successfully', 'success')
        return redirect(url_for('admins'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Add Admin - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
            <script>
                function toggleSchoolSelect() {
                    var checkbox = document.getElementById('is_super_admin');
                    var schoolGroup = document.getElementById('school_group');
                    var schoolSelect = document.getElementById('school_id');
                    if (checkbox.checked) {
                        schoolGroup.style.display = 'none';
                        schoolSelect.required = false;
                    } else {
                        schoolGroup.style.display = 'block';
                        schoolSelect.required = true;
                    }
                }
            </script>
        </head>
        <body>
            ''' + get_nav('admins') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-plus"></i> Add New Admin</h2>
                    <form method="POST">
                        <div class="form-group">
                            <label>Username *</label>
                            <input type="text" name="username" required>
                        </div>
                        <div class="form-group">
                            <label>Password *</label>
                            <input type="password" name="password" required>
                        </div>
                        <div class="form-group">
                            <div class="checkbox-group">
                                <input type="checkbox" name="is_super_admin" id="is_super_admin" onchange="toggleSchoolSelect()">
                                <label for="is_super_admin" style="margin: 0;">Super Admin (Access to all schools)</label>
                            </div>
                        </div>
                        <div class="form-group" id="school_group">
                            <label>Assigned School *</label>
                            <select name="school_id" id="school_id" required>
                                <option value="">Select School</option>
                                {% for school in schools %}
                                <option value="{{ school.id }}">{{ school.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save Admin
                        </button>
                        <a href="/admins" class="btn btn-secondary">Cancel</a>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''', schools=schools)

@app.route('/admins/delete/<int:id>')
@login_required
def delete_admin(id):
    if not current_user.is_super_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if id == current_user.id:
        flash('Cannot delete yourself', 'danger')
        return redirect(url_for('admins'))
    
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Admin deleted successfully', 'success')
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Passwords do not match', 'danger')
        elif len(new_password) < 6:
            flash('Password must be at least 6 characters', 'danger')
        else:
            current_user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Password updated successfully', 'success')
        
        return redirect(url_for('settings'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Settings - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('settings') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-sliders-h"></i> Settings</h2>
                    
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }}">{{ message }}</div>
                        {% endfor %}
                    {% endwith %}
                    
                    <h3 style="margin-top: 20px; margin-bottom: 15px;">Change Password</h3>
                    <form method="POST">
                        <div class="form-group">
                            <label>New Password</label>
                            <input type="password" name="new_password" required minlength="6">
                        </div>
                        <div class="form-group">
                            <label>Confirm Password</label>
                            <input type="password" name="confirm_password" required minlength="6">
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Update Password
                        </button>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''')

# API Endpoint for Kiosk
@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return jsonify({'error': 'API key required'}), 401
    
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Process attendance records
    records = data.get('records', [])
    synced = 0
    
    for record in records:
        staff_id = record.get('staff_id')
        staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
        
        if not staff:
            continue
        
        date_str = record.get('date')
        record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        attendance = Attendance.query.filter_by(
            staff_id=staff.id,
            school_id=school.id,
            date=record_date
        ).first()
        
        if not attendance:
            attendance = Attendance(
                staff_id=staff.id,
                school_id=school.id,
                date=record_date
            )
            db.session.add(attendance)
        
        if record.get('sign_in_time'):
            sign_in = datetime.strptime(f"{date_str} {record['sign_in_time']}", '%Y-%m-%d %H:%M:%S')
            attendance.sign_in_time = sign_in
            
            # Check if late
            resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
            if sign_in.time() > resumption:
                attendance.is_late = True
        
        if record.get('sign_out_time'):
            sign_out = datetime.strptime(f"{date_str} {record['sign_out_time']}", '%Y-%m-%d %H:%M:%S')
            attendance.sign_out_time = sign_out
        
        synced += 1
    
    db.session.commit()
    
    # Return staff list for kiosk
    staff_list = [{
        'staff_id': s.staff_id,
        'first_name': s.first_name,
        'last_name': s.last_name,
        'department': s.department
    } for s in Staff.query.filter_by(school_id=school.id, is_active=True).all()]
    
    return jsonify({
        'success': True,
        'synced': synced,
        'staff': staff_list,
        'school': {
            'name': school.name,
            'resumption_time': school.resumption_time,
            'closing_time': school.closing_time
        }
    })

# Initialize database
with app.app_context():
    db.create_all()
    
    # Create default admin if none exists
    if not User.query.first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            is_super_admin=True
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
