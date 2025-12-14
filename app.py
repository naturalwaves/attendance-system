from flask import Flask, render_template_string, request, redirect, url_for, flash, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import csv
import io
import secrets
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Role constants
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_HR_VIEWER = 'hr_viewer'
ROLE_CEO_VIEWER = 'ceo_viewer'
ROLE_SCHOOL_ADMIN = 'school_admin'
ROLE_STAFF = 'staff'

DEFAULT_SCHEDULE = json.dumps({
    'monday': {'resumption': '08:00', 'closing': '17:00', 'enabled': True},
    'tuesday': {'resumption': '08:00', 'closing': '17:00', 'enabled': True},
    'wednesday': {'resumption': '08:00', 'closing': '17:00', 'enabled': True},
    'thursday': {'resumption': '08:00', 'closing': '17:00', 'enabled': True},
    'friday': {'resumption': '08:00', 'closing': '14:00', 'enabled': True}
})

# Models
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20))
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    schedule = db.Column(db.Text, default=DEFAULT_SCHEDULE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True)
    attendance = db.relationship('Attendance', backref='school', lazy=True)
    
    def get_schedule(self):
        try:
            return json.loads(self.schedule) if self.schedule else json.loads(DEFAULT_SCHEDULE)
        except:
            return json.loads(DEFAULT_SCHEDULE)
    
    def get_day_times(self, day_name):
        schedule = self.get_schedule()
        day = day_name.lower()
        if day in schedule and schedule[day]['enabled']:
            return schedule[day]['resumption'], schedule[day]['closing']
        return None, None
    
    def get_display_name(self):
        return self.short_name if self.short_name else self.name

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default=ROLE_SCHOOL_ADMIN)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=True)
    school = db.relationship('School', backref='users')
    linked_staff = db.relationship('Staff', backref='user_account', foreign_keys=[staff_id])
    
    def can_edit(self):
        return self.role in [ROLE_SUPER_ADMIN, ROLE_SCHOOL_ADMIN]
    
    def can_view_all_schools(self):
        return self.role in [ROLE_SUPER_ADMIN, ROLE_HR_VIEWER, ROLE_CEO_VIEWER]
    
    def is_staff_only(self):
        return self.role == ROLE_STAFF

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(50), default='Academic')
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

# CORS helper
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
    return response

def get_styles():
    return '''
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f6f9; min-height: 100vh; }
            .top-nav { background: linear-gradient(135deg, #800000, #a00000); color: white; padding: 0; box-shadow: 0 2px 10px rgba(0,0,0,0.1); position: fixed; top: 0; left: 0; right: 0; z-index: 1000; height: 60px; }
            .nav-container { max-width: 1400px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; height: 100%; padding: 0 20px; }
            .nav-brand { display: flex; align-items: center; gap: 15px; font-size: 1.3rem; font-weight: bold; }
            .nav-brand img { height: 45px; width: auto; }
            .nav-menu { display: flex; align-items: center; gap: 5px; }
            .nav-menu a, .nav-dropdown .dropdown-btn { color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; transition: all 0.3s; font-size: 0.9rem; display: flex; align-items: center; gap: 8px; background: none; border: none; cursor: pointer; font-family: inherit; }
            .nav-menu a:hover, .nav-dropdown .dropdown-btn:hover { background: rgba(255,255,255,0.2); }
            .nav-menu a.active { background: rgba(255,255,255,0.25); }
            .nav-dropdown { position: relative; }
            .dropdown-content { display: none; position: absolute; top: 100%; right: 0; background: white; min-width: 180px; box-shadow: 0 8px 16px rgba(0,0,0,0.15); border-radius: 8px; overflow: hidden; z-index: 1001; }
            .nav-dropdown:hover .dropdown-content { display: block; }
            .dropdown-content a { color: #333 !important; padding: 12px 16px; display: flex; align-items: center; gap: 10px; border-radius: 0; }
            .dropdown-content a:hover { background: #f5f5f5 !important; }
            .main-content { margin-top: 60px; padding: 30px; max-width: 1400px; margin-left: auto; margin-right: auto; }
            .card { background: white; border-radius: 12px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); margin-bottom: 25px; }
            .card h2 { color: #800000; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; }
            .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .stat-card { background: white; border-radius: 12px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); border-left: 5px solid #800000; }
            .stat-card.green { border-left-color: #28a745; }
            .stat-card.blue { border-left-color: #007bff; }
            .stat-card.yellow { border-left-color: #ffc107; }
            .stat-card.red { border-left-color: #dc3545; }
            .stat-card h3 { font-size: 0.9rem; color: #666; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
            .stat-card .number { font-size: 2.2rem; font-weight: bold; color: #800000; }
            .stat-card.green .number { color: #28a745; }
            .stat-card.blue .number { color: #007bff; }
            .stat-card.yellow .number { color: #ffc107; }
            .stat-card.red .number { color: #dc3545; }
            .stat-card small { color: #888; font-size: 0.8rem; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { padding: 14px; text-align: left; border-bottom: 1px solid #eee; }
            th { background: #800000; color: white; font-weight: 600; }
            tr:hover { background: #f8f9fa; }
            .form-group { margin-bottom: 20px; }
            .form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
            .form-group input, .form-group select, .form-group textarea { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 1rem; transition: border-color 0.3s; }
            .form-group input:focus, .form-group select:focus { outline: none; border-color: #800000; }
            .btn { padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 0.95rem; font-weight: 600; transition: all 0.3s; display: inline-flex; align-items: center; gap: 8px; text-decoration: none; }
            .btn-primary { background: linear-gradient(135deg, #800000, #a00000); color: white; }
            .btn-primary:hover { background: linear-gradient(135deg, #600000, #800000); transform: translateY(-2px); }
            .btn-success { background: #28a745; color: white; }
            .btn-success:hover { background: #218838; }
            .btn-danger { background: #dc3545; color: white; }
            .btn-danger:hover { background: #c82333; }
            .btn-secondary { background: #6c757d; color: white; }
            .btn-warning { background: #ffc107; color: #333; }
            .btn-sm { padding: 6px 12px; font-size: 0.85rem; }
            .filter-bar { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; align-items: end; }
            .filter-bar .form-group { margin-bottom: 0; }
            .filter-bar label { font-size: 0.85rem; margin-bottom: 5px; }
            .filter-bar input, .filter-bar select { padding: 10px; min-width: 150px; }
            .status { padding: 5px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
            .status.signed-in { background: #d4edda; color: #155724; }
            .status.signed-out { background: #cce5ff; color: #004085; }
            .status.absent { background: #f8d7da; color: #721c24; }
            .status.na { background: #e9ecef; color: #6c757d; }
            .status.active { background: #d4edda; color: #155724; }
            .status.inactive { background: #f8d7da; color: #721c24; }
            .alert { padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; }
            .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
            .login-container { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #800000, #a00000); }
            .login-box { background: white; padding: 50px; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 420px; }
            .login-box h1 { color: #800000; margin-bottom: 10px; text-align: center; }
            .login-box .subtitle { color: #666; margin-bottom: 30px; text-align: center; }
            .login-logo { text-align: center; margin-bottom: 25px; }
            .login-logo img { height: 80px; width: auto; }
            .actions { display: flex; gap: 8px; flex-wrap: wrap; }
            .checkbox-group { display: flex; align-items: center; gap: 10px; }
            .checkbox-group input[type="checkbox"] { width: 18px; height: 18px; }
            .reset-section { background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 20px; margin-top: 20px; }
            .reset-section h4 { color: #856404; margin-bottom: 15px; }
            .reset-section .btn { margin-right: 10px; margin-bottom: 10px; }
            .schedule-grid { display: grid; gap: 15px; margin-top: 15px; }
            .schedule-day { display: grid; grid-template-columns: 120px 1fr 1fr auto; gap: 15px; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 8px; }
            .schedule-day label { font-weight: 600; }
            .toggle-switch { display: flex; align-items: center; gap: 10px; padding: 10px 15px; background: #f0f0f0; border-radius: 8px; margin-bottom: 15px; }
            .toggle-switch label { margin: 0; font-weight: normal; cursor: pointer; }
            .toggle-switch input { margin-right: 5px; }
            .role-badge { padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
            .role-super { background: #800000; color: white; }
            .role-hr { background: #17a2b8; color: white; }
            .role-ceo { background: #6f42c1; color: white; }
            .role-school { background: #28a745; color: white; }
            .role-staff { background: #6c757d; color: white; }
        </style>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    '''

def get_nav(active=''):
    if not current_user.is_authenticated:
        return ''
    
    if current_user.is_staff_only():
        return f'''
        <nav class="top-nav">
            <div class="nav-container">
                <div class="nav-brand">
                    <img src="https://i.ibb.co/PGPKP3HB/corona-logo-2.png" alt="Logo">
                    <span>My Attendance</span>
                </div>
                <div class="nav-menu">
                    <a href="/my-attendance" class="{'active' if active == 'my-attendance' else ''}">
                        <i class="fas fa-calendar-check"></i> My Records
                    </a>
                    <a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a>
                </div>
            </div>
        </nav>
        '''
    
    can_edit = current_user.can_edit()
    can_view_all = current_user.can_view_all_schools()
    
    nav_items = f'''
        <a href="/dashboard" class="{'active' if active == 'dashboard' else ''}">
            <i class="fas fa-chart-line"></i> Dashboard
        </a>
    '''
    
    if can_edit or can_view_all:
        nav_items += f'''
            <a href="/schools" class="{'active' if active == 'schools' else ''}">
                <i class="fas fa-school"></i> Schools
            </a>
            <a href="/staff" class="{'active' if active == 'staff' else ''}">
                <i class="fas fa-users"></i> Staff
            </a>
        '''
    
    if can_edit:
        nav_items += f'''
            <a href="/bulk-upload" class="{'active' if active == 'bulk-upload' else ''}">
                <i class="fas fa-file-upload"></i> Bulk Upload
            </a>
        '''
    
    nav_items += '''
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
    '''
    
    if current_user.role == ROLE_SUPER_ADMIN:
        nav_items += '''
            <div class="nav-dropdown">
                <button class="dropdown-btn">
                    <i class="fas fa-cog"></i> Admin <i class="fas fa-caret-down"></i>
                </button>
                <div class="dropdown-content">
                    <a href="/admins"><i class="fas fa-user-shield"></i> Manage Users</a>
                    <a href="/settings"><i class="fas fa-sliders-h"></i> Settings</a>
                    <a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a>
                </div>
            </div>
        '''
    else:
        nav_items += '''
            <a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a>
        '''
    
    return f'''
        <nav class="top-nav">
            <div class="nav-container">
                <div class="nav-brand">
                    <img src="https://i.ibb.co/PGPKP3HB/corona-logo-2.png" alt="Logo">
                    <span>Attendance System</span>
                </div>
                <div class="nav-menu">
                    {nav_items}
                </div>
            </div>
        </nav>
    '''

def get_role_badge(role):
    badges = {
        ROLE_SUPER_ADMIN: '<span class="role-badge role-super">Super Admin</span>',
        ROLE_HR_VIEWER: '<span class="role-badge role-hr">HR Viewer</span>',
        ROLE_CEO_VIEWER: '<span class="role-badge role-ceo">CEO Viewer</span>',
        ROLE_SCHOOL_ADMIN: '<span class="role-badge role-school">School Admin</span>',
        ROLE_STAFF: '<span class="role-badge role-staff">Staff</span>'
    }
    return badges.get(role, role)

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_staff_only():
            return redirect(url_for('my_attendance'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
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
                        <img src="https://i.ibb.co/PGPKP3HB/corona-logo-2.png" alt="Logo">
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

@app.route('/my-attendance')
@login_required
def my_attendance():
    if not current_user.is_staff_only():
        return redirect(url_for('dashboard'))
    
    if not current_user.staff_id:
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>My Attendance</title>
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                ''' + get_styles() + '''
            </head>
            <body>
                ''' + get_nav('my-attendance') + '''
                <div class="main-content">
                    <div class="card">
                        <h2>Account Not Linked</h2>
                        <p>Your account is not linked to a staff record. Please contact your administrator.</p>
                    </div>
                </div>
            </body>
            </html>
        ''')
    
    staff_member = Staff.query.get(current_user.staff_id)
    
    total_late = Attendance.query.filter_by(staff_id=staff_member.id, is_late=True).count()
    total_attendance = Attendance.query.filter_by(staff_id=staff_member.id).filter(Attendance.sign_in_time.isnot(None)).count()
    
    if total_attendance > 0:
        punctuality_pct = round(((total_attendance - total_late) / total_attendance) * 100, 1)
        lateness_pct = round((total_late / total_attendance) * 100, 1)
    else:
        punctuality_pct = 0
        lateness_pct = 0
    
    recent_records = Attendance.query.filter_by(staff_id=staff_member.id).order_by(Attendance.date.desc()).limit(30).all()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>My Attendance</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('my-attendance') + '''
            <div class="main-content">
                <h1 style="margin-bottom: 25px;">Welcome, {{ staff.first_name }}!</h1>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <h3><i class="fas fa-calendar-check"></i> Total Days</h3>
                        <div class="number">{{ total_attendance }}</div>
                    </div>
                    <div class="stat-card yellow">
                        <h3><i class="fas fa-clock"></i> Times Late</h3>
                        <div class="number">{{ total_late }}</div>
                    </div>
                    <div class="stat-card green">
                        <h3><i class="fas fa-check-circle"></i> Punctuality</h3>
                        <div class="number">{{ punctuality_pct }}%</div>
                    </div>
                    <div class="stat-card red">
                        <h3><i class="fas fa-times-circle"></i> Lateness</h3>
                        <div class="number">{{ lateness_pct }}%</div>
                    </div>
                </div>
                
                <div class="card">
                    <h2><i class="fas fa-history"></i> Recent Attendance (Last 30 Days)</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Sign In</th>
                                <th>Sign Out</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for record in records %}
                            <tr>
                                <td>{{ record.date.strftime('%Y-%m-%d') }}</td>
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
    ''', staff=staff_member, total_attendance=total_attendance, total_late=total_late,
        punctuality_pct=punctuality_pct, lateness_pct=lateness_pct, records=recent_records)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    school_ids = [s.id for s in schools]
    today = datetime.now().date()
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == today
    ).all()
    
    signed_in_ids = [a.staff_id for a in today_attendance if a.sign_in_time]
    late_count = len([a for a in today_attendance if a.is_late])
    
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
                                <td><strong>{{ school.name }}</strong></td>
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
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
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
                        {% if current_user.role == 'super_admin' %}
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
                                <th>Short Name</th>
                                <th>API Key</th>
                                {% if current_user.can_edit() %}
                                <th>Actions</th>
                                {% endif %}
                            </tr>
                        </thead>
                        <tbody>
                            {% for school in schools %}
                            <tr>
                                <td><strong>{{ school.name }}</strong></td>
                                <td>{{ school.short_name or '-' }}</td>
                                <td><code style="background: #f4f4f4; padding: 4px 8px; border-radius: 4px; font-size: 0.85rem;">{{ school.api_key[:16] }}...</code></td>
                                {% if current_user.can_edit() %}
                                <td class="actions">
                                    <a href="/schools/edit/{{ school.id }}" class="btn btn-sm btn-primary">
                                        <i class="fas fa-edit"></i>
                                    </a>
                                    {% if current_user.role == 'super_admin' %}
                                    <a href="/schools/regenerate-key/{{ school.id }}" class="btn btn-sm btn-warning" onclick="return confirm('Regenerate API key?')">
                                        <i class="fas fa-key"></i>
                                    </a>
                                    <a href="/schools/delete/{{ school.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this school?')">
                                        <i class="fas fa-trash"></i>
                                    </a>
                                    {% endif %}
                                </td>
                                {% endif %}
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
    if current_user.role != ROLE_SUPER_ADMIN:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        schedule = {}
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            schedule[day] = {
                'resumption': request.form.get(f'{day}_resumption', '08:00'),
                'closing': request.form.get(f'{day}_closing', '17:00'),
                'enabled': request.form.get(f'{day}_enabled') == 'on'
            }
        
        school = School(
            name=request.form.get('name'),
            short_name=request.form.get('short_name'),
            api_key=secrets.token_hex(32),
            schedule=json.dumps(schedule)
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
                <div class="card" style="max-width: 800px;">
                    <h2><i class="fas fa-plus"></i> Add New School</h2>
                    <form method="POST">
                        <div class="form-group">
                            <label>School Name *</label>
                            <input type="text" name="name" required placeholder="e.g. Corona Secondary School Victoria Island">
                        </div>
                        <div class="form-group">
                            <label>Short Name</label>
                            <input type="text" name="short_name" placeholder="e.g. CSVI" maxlength="20">
                        </div>
                        
                        <h3 style="margin: 25px 0 15px;">Weekly Schedule</h3>
                        <div class="schedule-grid">
                            {% for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] %}
                            <div class="schedule-day">
                                <label>{{ day }}</label>
                                <div>
                                    <small>Resumption</small>
                                    <input type="time" name="{{ day.lower() }}_resumption" value="{{ '08:00' if day != 'Friday' else '08:00' }}">
                                </div>
                                <div>
                                    <small>Closing</small>
                                    <input type="time" name="{{ day.lower() }}_closing" value="{{ '17:00' if day != 'Friday' else '14:00' }}">
                                </div>
                                <div class="checkbox-group">
                                    <input type="checkbox" name="{{ day.lower() }}_enabled" id="{{ day.lower() }}_enabled" checked>
                                    <label for="{{ day.lower() }}_enabled">Enabled</label>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                        
                        <div style="margin-top: 25px;">
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-save"></i> Save School
                            </button>
                            <a href="/schools" class="btn btn-secondary">Cancel</a>
                        </div>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''')

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    if not current_user.can_edit():
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    school = School.query.get_or_404(id)
    
    if current_user.role == ROLE_SCHOOL_ADMIN and current_user.school_id != id:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        
        schedule = {}
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            schedule[day] = {
                'resumption': request.form.get(f'{day}_resumption', '08:00'),
                'closing': request.form.get(f'{day}_closing', '17:00'),
                'enabled': request.form.get(f'{day}_enabled') == 'on'
            }
        school.schedule = json.dumps(schedule)
        
        db.session.commit()
        flash('School updated successfully', 'success')
        return redirect(url_for('schools'))
    
    schedule = school.get_schedule()
    
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
                <div class="card" style="max-width: 800px;">
                    <h2><i class="fas fa-edit"></i> Edit School</h2>
                    <form method="POST">
                        <div class="form-group">
                            <label>School Name *</label>
                            <input type="text" name="name" value="{{ school.name }}" required>
                        </div>
                        <div class="form-group">
                            <label>Short Name</label>
                            <input type="text" name="short_name" value="{{ school.short_name or '' }}" placeholder="e.g. CSVI" maxlength="20">
                        </div>
                        
                        <h3 style="margin: 25px 0 15px;">Weekly Schedule</h3>
                        <div class="schedule-grid">
                            {% for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'] %}
                            <div class="schedule-day">
                                <label>{{ day.title() }}</label>
                                <div>
                                    <small>Resumption</small>
                                    <input type="time" name="{{ day }}_resumption" value="{{ schedule[day]['resumption'] }}">
                                </div>
                                <div>
                                    <small>Closing</small>
                                    <input type="time" name="{{ day }}_closing" value="{{ schedule[day]['closing'] }}">
                                </div>
                                <div class="checkbox-group">
                                    <input type="checkbox" name="{{ day }}_enabled" id="{{ day }}_enabled" {{ 'checked' if schedule[day]['enabled'] else '' }}>
                                    <label for="{{ day }}_enabled">Enabled</label>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                        
                        <div style="margin-top: 25px;">
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-save"></i> Update School
                            </button>
                            <a href="/schools" class="btn btn-secondary">Cancel</a>
                        </div>
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
    ''', school=school, schedule=schedule)

@app.route('/schools/delete/<int:id>')
@login_required
def delete_school(id):
    if current_user.role != ROLE_SUPER_ADMIN:
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
    if current_user.role != ROLE_SUPER_ADMIN:
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
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
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
    today_attendance = {a.staff_id: a for a in Attendance.query.filter(Attendance.date == today).all()}
    
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
                        {% if current_user.can_edit() %}
                        <a href="/staff/add" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add Staff
                        </a>
                        {% endif %}
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
                                <select name="school_id" onchange="this.form.submit()" {{ 'disabled' if not current_user.can_view_all_schools() else '' }}>
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
                                {% if current_user.can_edit() %}
                                <th>Actions</th>
                                {% endif %}
                            </tr>
                        </thead>
                        <tbody>
                            {% for s in staff %}
                            <tr>
                                <td><strong>{{ s.staff_id }}</strong></td>
                                <td>{{ s.first_name }} {{ s.last_name }}</td>
                                <td>{{ s.department or '-' }}</td>
                                <td>{{ s.school.get_display_name() }}</td>
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
                                {% if current_user.can_edit() %}
                                <td class="actions">
                                    <a href="/staff/toggle/{{ s.id }}" class="btn btn-sm {{ 'btn-warning' if s.is_active else 'btn-success' }}">
                                        <i class="fas {{ 'fa-ban' if s.is_active else 'fa-check' }}"></i>
                                    </a>
                                    <a href="/staff/delete/{{ s.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this staff member?')">
                                        <i class="fas fa-trash"></i>
                                    </a>
                                </td>
                                {% endif %}
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
    if not current_user.can_edit():
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    if current_user.can_view_all_schools():
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    if request.method == 'POST':
        school_id = request.form.get('school_id') if current_user.can_view_all_schools() else current_user.school_id
        staff_member = Staff(
            staff_id=request.form.get('staff_id'),
            first_name=request.form.get('first_name'),
            last_name=request.form.get('last_name'),
            department=request.form.get('department', 'Academic'),
            school_id=school_id
        )
        db.session.add(staff_member)
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
                        {% if current_user.can_view_all_schools() %}
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
                            <label>Department *</label>
                            <select name="department" required>
                                <option value="Academic">Academic</option>
                                <option value="Admin">Admin</option>
                                <option value="Non-Academic">Non-Academic</option>
                                <option value="Management">Management</option>
                            </select>
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
    if not current_user.can_edit():
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    staff_member = Staff.query.get_or_404(id)
    
    if current_user.role == ROLE_SCHOOL_ADMIN and current_user.school_id != staff_member.school_id:
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
    if not current_user.can_edit():
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    staff_member = Staff.query.get_or_404(id)
    
    if current_user.role == ROLE_SCHOOL_ADMIN and current_user.school_id != staff_member.school_id:
        flash('Access denied', 'danger')
        return redirect(url_for('staff'))
    
    db.session.delete(staff_member)
    db.session.commit()
    flash('Staff deleted successfully', 'success')
    return redirect(url_for('staff'))

@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    if not current_user.can_edit():
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if current_user.can_view_all_schools():
        schools = School.query.all()
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
    
    if request.method == 'POST':
        school_id = request.form.get('school_id') if current_user.can_view_all_schools() else current_user.school_id
        file = request.files.get('file')
        
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file', 'danger')
            return redirect(url_for('bulk_upload'))
        
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            
            count = 0
            for row in reader:
                dept = row.get('Department', row.get('department', 'Academic'))
                if dept not in ['Academic', 'Admin', 'Non-Academic', 'Management']:
                    dept = 'Academic'
                
                staff_member = Staff(
                    staff_id=row.get('ID', row.get('staff_id', '')),
                    first_name=row.get('Firstname', row.get('first_name', '')),
                    last_name=row.get('Surname', row.get('last_name', '')),
                    department=dept,
                    school_id=school_id
                )
                db.session.add(staff_member)
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
                        {% if current_user.can_view_all_schools() %}
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
                            John,Doe,EMP001,Academic<br>
                            Jane,Smith,EMP002,Admin<br>
                            Bob,Johnson,EMP003,Non-Academic<br>
                            Mary,Williams,EMP004,Management
                        </code>
                        <p style="margin: 10px 0; font-size: 0.9rem;"><strong>Valid Departments:</strong> Academic, Admin, Non-Academic, Management</p>
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
    writer.writerow(['John', 'Doe', 'EMP001', 'Academic'])
    writer.writerow(['Jane', 'Smith', 'EMP002', 'Admin'])
    writer.writerow(['Bob', 'Johnson', 'EMP003', 'Non-Academic'])
    writer.writerow(['Mary', 'Williams', 'EMP004', 'Management'])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=staff_template.csv'
    return response

@app.route('/attendance')
@login_required
def attendance():
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
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
    elif not current_user.can_view_all_schools():
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
                            {% if current_user.can_view_all_schools() %}
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
                                <td>{{ record.school.get_display_name() }}</td>
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
    elif not current_user.can_view_all_schools():
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
            r.school.get_display_name(),
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
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    stats_mode = request.args.get('stats_mode', 'all_time')
    
    is_single_day = date_from == date_to
    
    if selected_school_id:
        staff_query = Staff.query.filter_by(school_id=selected_school_id, is_active=True)
    elif current_user.can_view_all_schools():
        staff_query = Staff.query.filter_by(is_active=True)
    else:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    
    all_staff = staff_query.all()
    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    staff_stats = []
    for s in all_staff:
        late_in_period = Attendance.query.filter(
            Attendance.staff_id == s.id,
            Attendance.is_late == True,
            Attendance.date >= date_from_obj,
            Attendance.date <= date_to_obj
        ).count()
        
        if late_in_period > 0 or request.args.get('show_all'):
            if is_single_day or stats_mode == 'all_time':
                total_late = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
                total_attendance = Attendance.query.filter_by(staff_id=s.id).filter(Attendance.sign_in_time.isnot(None)).count()
            else:
                total_late = late_in_period
                total_attendance = Attendance.query.filter(
                    Attendance.staff_id == s.id,
                    Attendance.sign_in_time.isnot(None),
                    Attendance.date >= date_from_obj,
                    Attendance.date <= date_to_obj
                ).count()
            
            if total_attendance > 0:
                punctuality_pct = round(((total_attendance - total_late) / total_attendance) * 100, 1)
                lateness_pct = round((total_late / total_attendance) * 100, 1)
            else:
                punctuality_pct = 0
                lateness_pct = 0
            
            staff_stats.append({
                'staff': s,
                'times_late': total_late,
                'punctuality_pct': punctuality_pct,
                'lateness_pct': lateness_pct,
                'late_in_period': late_in_period
            })
    
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
                        <form method="GET" id="filterForm" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.can_view_all_schools() %}
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
                            <input type="hidden" name="stats_mode" id="stats_mode" value="{{ stats_mode }}">
                            <button type="submit" class="btn btn-primary">
                                <i class="fas fa-filter"></i> Filter
                            </button>
                            <a href="/late-report?date_from={{ today }}&date_to={{ today }}" class="btn btn-secondary">
                                <i class="fas fa-calendar-day"></i> Today
                            </a>
                            <a href="/late-report/download?school_id={{ selected_school_id or '' }}&date_from={{ date_from }}&date_to={{ date_to }}&stats_mode={{ stats_mode }}" class="btn btn-success">
                                <i class="fas fa-download"></i> Download CSV
                            </a>
                        </form>
                    </div>
                    
                    {% if not is_single_day %}
                    <div class="toggle-switch">
                        <label>
                            <input type="radio" name="stats_toggle" value="per_period" {{ 'checked' if stats_mode == 'per_period' else '' }} onchange="document.getElementById('stats_mode').value='per_period'; document.getElementById('filterForm').submit();">
                            Per Period ({{ date_from }} to {{ date_to }})
                        </label>
                        <label style="margin-left: 20px;">
                            <input type="radio" name="stats_toggle" value="all_time" {{ 'checked' if stats_mode == 'all_time' else '' }} onchange="document.getElementById('stats_mode').value='all_time'; document.getElementById('filterForm').submit();">
                            All Time
                        </label>
                    </div>
                    {% endif %}
                    
                    <table>
                        <thead>
                            <tr>
                                <th>Staff ID</th>
                                <th>Name</th>
                                <th>Department</th>
                                <th>School</th>
                                <th>Times Late{% if not is_single_day %} ({{ 'Period' if stats_mode == 'per_period' else 'All Time' }}){% endif %}</th>
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
                                <td>{{ stat.staff.school.get_display_name() }}</td>
                                <td><strong style="color: #dc3545;">{{ stat.times_late }}</strong></td>
                                <td><span style="color: #28a745;">{{ stat.punctuality_pct }}%</span></td>
                                <td><span style="color: #dc3545;">{{ stat.lateness_pct }}%</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    
                    {% if current_user.role == 'super_admin' %}
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
                            <button type="submit" class="btn btn-danger" onclick="return confirm('Reset late counters for ALL schools?')">
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
        date_from=date_from, date_to=date_to, today=datetime.now().strftime('%Y-%m-%d'),
        is_single_day=is_single_day, stats_mode=stats_mode)

@app.route('/reset-late-count', methods=['POST'])
@login_required
def reset_late_count():
    if current_user.role != ROLE_SUPER_ADMIN:
        flash('Access denied', 'danger')
        return redirect(url_for('late_report'))
    
    scope = request.form.get('scope')
    school_id = request.form.get('school_id', type=int)
    
    if scope == 'school' and school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        Attendance.query.filter(Attendance.staff_id.in_(staff_ids)).update({Attendance.is_late: False}, synchronize_session=False)
        db.session.commit()
        school = School.query.get(school_id)
        flash(f'Late counters reset for {school.name}', 'success')
    elif scope == 'all':
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
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    stats_mode = request.args.get('stats_mode', 'all_time')
    
    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    is_single_day = date_from == date_to
    
    if school_id:
        staff_query = Staff.query.filter_by(school_id=school_id, is_active=True)
    elif current_user.can_view_all_schools():
        staff_query = Staff.query.filter_by(is_active=True)
    else:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    
    all_staff = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Last Name', 'Department', 'School', 'Times Late', '% Punctuality', '% Lateness'])
    
    for s in all_staff:
        if is_single_day or stats_mode == 'all_time':
            total_late = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
            total_attendance = Attendance.query.filter_by(staff_id=s.id).filter(Attendance.sign_in_time.isnot(None)).count()
        else:
            total_late = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.is_late == True,
                Attendance.date >= date_from_obj,
                Attendance.date <= date_to_obj
            ).count()
            total_attendance = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.sign_in_time.isnot(None),
                Attendance.date >= date_from_obj,
                Attendance.date <= date_to_obj
            ).count()
        
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
            s.school.get_display_name(),
            total_late,
            f'{punctuality_pct}%',
            f'{lateness_pct}%'
        ])
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=late_report_{date_from}_to_{date_to}.csv'
    return response

@app.route('/absent-report')
@login_required
def absent_report():
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
        schools = School.query.all()
        selected_school_id = request.args.get('school_id', type=int)
    else:
        schools = School.query.filter_by(id=current_user.school_id).all()
        selected_school_id = current_user.school_id
    
    date_from = request.args.get('date_from', datetime.now().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    
    if selected_school_id:
        staff_query = Staff.query.filter(
            Staff.school_id == selected_school_id,
            Staff.is_active == True,
            Staff.department != 'Management'
        )
    elif current_user.can_view_all_schools():
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
    
    absent_list = []
    current_date = date_from_obj
    while current_date <= date_to_obj:
        day_name = current_date.strftime('%A').lower()
        if day_name not in ['saturday', 'sunday']:
            for s in all_staff:
                school_schedule = s.school.get_schedule()
                if day_name in school_schedule and school_schedule[day_name]['enabled']:
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
                    <p style="color: #666; margin-bottom: 20px;">Excludes Management department and weekends</p>
                    
                    <div class="filter-bar">
                        <form method="GET" style="display: flex; gap: 15px; align-items: end; flex-wrap: wrap;">
                            {% if current_user.can_view_all_schools() %}
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
                                <td>{{ item.staff.school.get_display_name() }}</td>
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
    elif current_user.can_view_all_schools():
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
        day_name = current_date.strftime('%A').lower()
        if day_name not in ['saturday', 'sunday']:
            for s in all_staff:
                school_schedule = s.school.get_schedule()
                if day_name in school_schedule and school_schedule[day_name]['enabled']:
                    if (s.id, current_date) not in signed_in:
                        writer.writerow([
                            current_date.strftime('%Y-%m-%d'),
                            s.staff_id,
                            s.first_name,
                            s.last_name,
                            s.department or '',
                            s.school.get_display_name()
                        ])
        current_date += timedelta(days=1)
    
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=absent_report_{date_from}_to_{date_to}.csv'
    return response

@app.route('/overtime-report')
@login_required
def overtime_report():
    if current_user.is_staff_only():
        return redirect(url_for('my_attendance'))
    
    if current_user.can_view_all_schools():
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
    elif not current_user.can_view_all_schools():
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.all()
    
    overtime_list = []
    for r in records:
        day_name = r.date.strftime('%A').lower()
        _, closing_str = r.school.get_day_times(day_name)
        
        if closing_str:
            closing_time = datetime.strptime(closing_str, '%H:%M').time()
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
                    'overtime_minutes': overtime_minutes,
                    'closing_time': closing_str
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
                            {% if current_user.can_view_all_schools() %}
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
                                <td>{{ item.record.school.get_display_name() }}</td>
                                <td>{{ item.closing_time }}</td>
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
    elif not current_user.can_view_all_schools():
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Last Name', 'School', 'Closing Time', 'Sign Out', 'Overtime'])
    
    for r in records:
        day_name = r.date.strftime('%A').lower()
        _, closing_str = r.school.get_day_times(day_name)
        
        if closing_str:
            closing_time = datetime.strptime(closing_str, '%H:%M').time()
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
                    r.school.get_display_name(),
                    closing_str,
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
    if current_user.role != ROLE_SUPER_ADMIN:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    all_users = User.query.all()
    schools = School.query.all()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Manage Users - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
        </head>
        <body>
            ''' + get_nav('admins') + '''
            <div class="main-content">
                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h2 style="margin: 0; border: none; padding: 0;"><i class="fas fa-user-shield"></i> Manage Users</h2>
                        <a href="/admins/add" class="btn btn-primary">
                            <i class="fas fa-plus"></i> Add User
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
                                <td>{{ get_role_badge(user.role)|safe }}</td>
                                <td>{{ user.school.name if user.school else 'All Schools' }}</td>
                                <td class="actions">
                                    {% if user.id != current_user.id %}
                                    <a href="/admins/delete/{{ user.id }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete this user?')">
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
    ''', users=all_users, schools=schools, get_role_badge=get_role_badge)

@app.route('/admins/add', methods=['GET', 'POST'])
@login_required
def add_admin():
    if current_user.role != ROLE_SUPER_ADMIN:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    schools = School.query.all()
    all_staff = Staff.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        school_id = request.form.get('school_id') if role in [ROLE_SCHOOL_ADMIN, ROLE_STAFF] else None
        staff_id = request.form.get('staff_id') if role == ROLE_STAFF else None
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('add_admin'))
        
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            school_id=school_id,
            staff_id=staff_id
        )
        db.session.add(user)
        db.session.commit()
        flash('User added successfully', 'success')
        return redirect(url_for('admins'))
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Add User - Attendance System</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            ''' + get_styles() + '''
            <script>
                function toggleFields() {
                    var role = document.getElementById('role').value;
                    var schoolGroup = document.getElementById('school_group');
                    var staffGroup = document.getElementById('staff_group');
                    
                    if (role === 'super_admin' || role === 'hr_viewer' || role === 'ceo_viewer') {
                        schoolGroup.style.display = 'none';
                        staffGroup.style.display = 'none';
                    } else if (role === 'school_admin') {
                        schoolGroup.style.display = 'block';
                        staffGroup.style.display = 'none';
                    } else if (role === 'staff') {
                        schoolGroup.style.display = 'block';
                        staffGroup.style.display = 'block';
                    }
                }
            </script>
        </head>
        <body>
            ''' + get_nav('admins') + '''
            <div class="main-content">
                <div class="card" style="max-width: 600px;">
                    <h2><i class="fas fa-plus"></i> Add New User</h2>
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
                            <label>Role *</label>
                            <select name="role" id="role" required onchange="toggleFields()">
                                <option value="super_admin">Super Admin (Full Access)</option>
                                <option value="hr_viewer">HR Viewer (View All Schools)</option>
                                <option value="ceo_viewer">CEO Viewer (View All Schools)</option>
                                <option value="school_admin">School Admin (Edit Own School)</option>
                                <option value="staff">Staff (View Own Records)</option>
                            </select>
                        </div>
                        <div class="form-group" id="school_group" style="display: none;">
                            <label>Assigned School *</label>
                            <select name="school_id" id="school_id">
                                <option value="">Select School</option>
                                {% for school in schools %}
                                <option value="{{ school.id }}">{{ school.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="form-group" id="staff_group" style="display: none;">
                            <label>Link to Staff Record *</label>
                            <select name="staff_id" id="staff_id">
                                <option value="">Select Staff Member</option>
                                {% for s in all_staff %}
                                <option value="{{ s.id }}">{{ s.first_name }} {{ s.last_name }} ({{ s.staff_id }}) - {{ s.school.get_display_name() }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-save"></i> Save User
                        </button>
                        <a href="/admins" class="btn btn-secondary">Cancel</a>
                    </form>
                </div>
            </div>
        </body>
        </html>
    ''', schools=schools, all_staff=all_staff)

@app.route('/admins/delete/<int:id>')
@login_required
def delete_admin(id):
    if current_user.role != ROLE_SUPER_ADMIN:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if id == current_user.id:
        flash('Cannot delete yourself', 'danger')
        return redirect(url_for('admins'))
    
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully', 'success')
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

# API Endpoint for Kiosk (with CORS support)
@app.route('/api/sync', methods=['POST', 'OPTIONS'])
def api_sync():
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        response = make_response()
        response = add_cors_headers(response)
        return response
    
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        response = jsonify({'error': 'API key required'})
        response = add_cors_headers(response)
        return response, 401
    
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        response = jsonify({'error': 'Invalid API key'})
        response = add_cors_headers(response)
        return response, 401
    
    data = request.get_json()
    
    if not data:
        response = jsonify({'error': 'No data provided'})
        response = add_cors_headers(response)
        return response, 400
    
    records = data.get('records', [])
    synced = 0
    
    for record in records:
        staff_id_str = record.get('staff_id')
        staff_member = Staff.query.filter_by(staff_id=staff_id_str, school_id=school.id).first()
        
        if not staff_member:
            continue
        
        date_str = record.get('date')
        record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        day_name = record_date.strftime('%A').lower()
        
        attendance = Attendance.query.filter_by(
            staff_id=staff_member.id,
            school_id=school.id,
            date=record_date
        ).first()
        
        if not attendance:
            attendance = Attendance(
                staff_id=staff_member.id,
                school_id=school.id,
                date=record_date
            )
            db.session.add(attendance)
        
        if record.get('sign_in_time'):
            sign_in = datetime.strptime(f"{date_str} {record['sign_in_time']}", '%Y-%m-%d %H:%M:%S')
            attendance.sign_in_time = sign_in
            
            resumption_str, _ = school.get_day_times(day_name)
            if resumption_str:
                resumption = datetime.strptime(resumption_str, '%H:%M').time()
                if sign_in.time() > resumption:
                    attendance.is_late = True
        
        if record.get('sign_out_time'):
            sign_out = datetime.strptime(f"{date_str} {record['sign_out_time']}", '%Y-%m-%d %H:%M:%S')
            attendance.sign_out_time = sign_out
        
        synced += 1
    
    db.session.commit()
    
    staff_list = [{
        'staff_id': s.staff_id,
        'first_name': s.first_name,
        'last_name': s.last_name,
        'department': s.department
    } for s in Staff.query.filter_by(school_id=school.id, is_active=True).all()]
    
    schedule = school.get_schedule()
    
    response = jsonify({
        'success': True,
        'synced': synced,
        'staff': staff_list,
        'school': {
            'name': school.name,
            'short_name': school.short_name,
            'schedule': schedule
        }
    })
    response = add_cors_headers(response)
    return response

# Initialize database
with app.app_context():
    db.create_all()
    
    if not User.query.first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role=ROLE_SUPER_ADMIN
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
