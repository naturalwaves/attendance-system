import os
from flask import Flask, request, redirect, url_for, flash, jsonify, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'

# Models
class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    schedule_mon_start = db.Column(db.String(5), default='08:00')
    schedule_mon_end = db.Column(db.String(5), default='17:00')
    schedule_tue_start = db.Column(db.String(5), default='08:00')
    schedule_tue_end = db.Column(db.String(5), default='17:00')
    schedule_wed_start = db.Column(db.String(5), default='08:00')
    schedule_wed_end = db.Column(db.String(5), default='17:00')
    schedule_thu_start = db.Column(db.String(5), default='08:00')
    schedule_thu_end = db.Column(db.String(5), default='17:00')
    schedule_fri_start = db.Column(db.String(5), default='08:00')
    schedule_fri_end = db.Column(db.String(5), default='17:00')
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='school_admin')
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Staff(db.Model):
    __tablename__ = 'staff'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    times_late = db.Column(db.Integer, default=0)
    attendance = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime, nullable=True)
    sign_out_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='present')
    is_late = db.Column(db.Boolean, default=False)
    late_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)

db.init_app(app)
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_school_schedule(school, day_of_week):
    days = ['mon', 'tue', 'wed', 'thu', 'fri']
    if day_of_week < 5:
        day = days[day_of_week]
        start = getattr(school, f'schedule_{day}_start')
        end = getattr(school, f'schedule_{day}_end')
        return start, end
    return None, None

def get_flashed_messages_html():
    messages = []
    for category, message in [(m.split('|')[0] if '|' in m else 'info', m.split('|')[1] if '|' in m else m) for m in []]:
        messages.append(f'<div class="alert alert-{category}">{message}</div>')
    return ''.join(messages)

def base_template(title, content, show_nav=True):
    nav_html = ''
    if show_nav and current_user.is_authenticated:
        nav_items = f'''
        <a href="{url_for('dashboard')}">Dashboard</a>
        '''
        if current_user.role == 'super_admin':
            nav_items += f'''
            <a href="{url_for('schools')}">Schools</a>
            <a href="{url_for('users')}">Users</a>
            '''
        if current_user.role in ['super_admin', 'school_admin', 'hr_viewer', 'ceo_viewer']:
            nav_items += f'''
            <a href="{url_for('staff_list')}">Staff</a>
            '''
        nav_items += f'''
        <a href="{url_for('attendance_report')}">Attendance</a>
        <a href="{url_for('late_report')}">Late Report</a>
        <a href="{url_for('absent_report')}">Absent Report</a>
        <a href="{url_for('overtime_report')}">Overtime</a>
        <a href="{url_for('logout')}" style="margin-left:auto;">Logout ({current_user.username})</a>
        '''
        nav_html = f'<nav style="background:#333;padding:10px;display:flex;gap:15px;flex-wrap:wrap;">{nav_items}</nav>'
    
    return f'''<!DOCTYPE html>
<html>
<head>
    <title>{title} - Attendance System</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: Arial, sans-serif; background: #f5f5f5; min-height: 100vh; }}
        nav a {{ color: white; text-decoration: none; padding: 5px 10px; }}
        nav a:hover {{ background: #555; border-radius: 4px; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .btn {{ display: inline-block; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 14px; }}
        .btn-primary {{ background: #007bff; color: white; }}
        .btn-success {{ background: #28a745; color: white; }}
        .btn-danger {{ background: #dc3545; color: white; }}
        .btn-warning {{ background: #ffc107; color: black; }}
        .btn-secondary {{ background: #6c757d; color: white; }}
        .btn:hover {{ opacity: 0.9; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; }}
        tr:hover {{ background: #f5f5f5; }}
        input, select {{ width: 100%; padding: 10px; margin: 5px 0 15px 0; border: 1px solid #ddd; border-radius: 4px; }}
        label {{ font-weight: bold; }}
        .alert {{ padding: 15px; margin-bottom: 20px; border-radius: 4px; }}
        .alert-success {{ background: #d4edda; color: #155724; }}
        .alert-danger {{ background: #f8d7da; color: #721c24; }}
        .alert-info {{ background: #d1ecf1; color: #0c5460; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
        .badge-success {{ background: #28a745; color: white; }}
        .badge-danger {{ background: #dc3545; color: white; }}
        .badge-primary {{ background: #007bff; color: white; }}
        .badge-secondary {{ background: #6c757d; color: white; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }}
        .stat-card {{ background: white; padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stat-card h3 {{ font-size: 2em; color: #007bff; }}
        .form-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            table {{ font-size: 14px; }}
            th, td {{ padding: 8px; }}
        }}
    </style>
</head>
<body>
    {nav_html}
    <div class="container">
        {content}
    </div>
</body>
</html>'''

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    error_msg = ''
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            error_msg = '<div class="alert alert-danger">Invalid username or password.</div>'
    
    content = f'''
    <div style="max-width:400px;margin:50px auto;">
        <div class="card">
            <h2 style="text-align:center;margin-bottom:20px;">Staff Attendance System</h2>
            {error_msg}
            <form method="POST">
                <label>Username</label>
                <input type="text" name="username" required>
                <label>Password</label>
                <input type="password" name="password" required>
                <button type="submit" class="btn btn-primary" style="width:100%;">Login</button>
            </form>
        </div>
    </div>
    '''
    return base_template('Login', content, show_nav=False)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        schools = School.query.all()
        total_staff = Staff.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today).count()
        late_today = Attendance.query.filter_by(date=today, is_late=True).count()
    else:
        schools = [current_user.school] if current_user.school else []
        if current_user.school:
            total_staff = Staff.query.filter_by(school_id=current_user.school_id, is_active=True).count()
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
            today_attendance = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today).count() if staff_ids else 0
            late_today = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today, Attendance.is_late == True).count() if staff_ids else 0
        else:
            total_staff = 0
            today_attendance = 0
            late_today = 0
    
    schools_html = ''
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        rows = ''
        for s in schools:
            staff_count = Staff.query.filter_by(school_id=s.id, is_active=True).count()
            rows += f'<tr><td>{s.name}</td><td>{s.short_name or "-"}</td><td>{staff_count}</td></tr>'
        
        schools_html = f'''
        <div class="card">
            <h3>Schools Overview</h3>
            <table>
                <tr><th>Name</th><th>Short Name</th><th>Staff Count</th></tr>
                {rows}
            </table>
        </div>
        '''
    
    content = f'''
    <h2>Dashboard</h2>
    <div class="stats-grid">
        <div class="stat-card">
            <h3>{total_staff}</h3>
            <p>Total Staff</p>
        </div>
        <div class="stat-card">
            <h3>{today_attendance}</h3>
            <p>Present Today</p>
        </div>
        <div class="stat-card">
            <h3>{late_today}</h3>
            <p>Late Today</p>
        </div>
        <div class="stat-card">
            <h3>{len(schools)}</h3>
            <p>Schools</p>
        </div>
    </div>
    {schools_html}
    '''
    return base_template('Dashboard', content)

@app.route('/schools')
@login_required
@role_required('super_admin')
def schools():
    all_schools = School.query.all()
    rows = ''
    for s in all_schools:
        rows += f'''<tr>
            <td>{s.name}</td>
            <td>{s.short_name or "-"}</td>
            <td><code style="font-size:10px;">{s.api_key[:20]}...</code></td>
            <td>
                <a href="{url_for('edit_school', id=s.id)}" class="btn btn-warning btn-sm">Edit</a>
                <a href="{url_for('regenerate_api_key', id=s.id)}" class="btn btn-secondary btn-sm" onclick="return confirm('Regenerate API key?')">New Key</a>
                <a href="{url_for('delete_school', id=s.id)}" class="btn btn-danger btn-sm" onclick="return confirm('Delete this school?')">Delete</a>
            </td>
        </tr>'''
    
    content = f'''
    <h2>Schools</h2>
    <a href="{url_for('add_school')}" class="btn btn-success" style="margin-bottom:20px;">Add School</a>
    <div class="card">
        <table>
            <tr><th>Name</th><th>Short Name</th><th>API Key</th><th>Actions</th></tr>
            {rows}
        </table>
    </div>
    '''
    return base_template('Schools', content)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        api_key = secrets.token_hex(32)
        
        school = School(name=name, short_name=short_name, api_key=api_key)
        
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        
        db.session.add(school)
        db.session.commit()
        return redirect(url_for('schools'))
    
    content = f'''
    <h2>Add School</h2>
    <div class="card">
        <form method="POST">
            <label>School Name</label>
            <input type="text" name="name" required>
            
            <label>Short Name</label>
            <input type="text" name="short_name" placeholder="e.g. VGC">
            
            <h4 style="margin-top:20px;">Schedule</h4>
            <div class="form-row">
                <div>
                    <label>Monday Start</label>
                    <input type="time" name="schedule_mon_start" value="08:00">
                </div>
                <div>
                    <label>Monday End</label>
                    <input type="time" name="schedule_mon_end" value="17:00">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Tuesday Start</label>
                    <input type="time" name="schedule_tue_start" value="08:00">
                </div>
                <div>
                    <label>Tuesday End</label>
                    <input type="time" name="schedule_tue_end" value="17:00">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Wednesday Start</label>
                    <input type="time" name="schedule_wed_start" value="08:00">
                </div>
                <div>
                    <label>Wednesday End</label>
                    <input type="time" name="schedule_wed_end" value="17:00">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Thursday Start</label>
                    <input type="time" name="schedule_thu_start" value="08:00">
                </div>
                <div>
                    <label>Thursday End</label>
                    <input type="time" name="schedule_thu_end" value="17:00">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Friday Start</label>
                    <input type="time" name="schedule_fri_start" value="08:00">
                </div>
                <div>
                    <label>Friday End</label>
                    <input type="time" name="schedule_fri_end" value="17:00">
                </div>
            </div>
            
            <button type="submit" class="btn btn-success" style="margin-top:20px;">Add School</button>
            <a href="{url_for('schools')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return base_template('Add School', content)

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        
        db.session.commit()
        return redirect(url_for('schools'))
    
    content = f'''
    <h2>Edit School</h2>
    <div class="card">
        <form method="POST">
            <label>School Name</label>
            <input type="text" name="name" value="{school.name}" required>
            
            <label>Short Name</label>
            <input type="text" name="short_name" value="{school.short_name or ''}" placeholder="e.g. VGC">
            
            <label>API Key</label>
            <input type="text" value="{school.api_key}" readonly style="background:#f5f5f5;">
            
            <h4 style="margin-top:20px;">Schedule</h4>
            <div class="form-row">
                <div>
                    <label>Monday Start</label>
                    <input type="time" name="schedule_mon_start" value="{school.schedule_mon_start}">
                </div>
                <div>
                    <label>Monday End</label>
                    <input type="time" name="schedule_mon_end" value="{school.schedule_mon_end}">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Tuesday Start</label>
                    <input type="time" name="schedule_tue_start" value="{school.schedule_tue_start}">
                </div>
                <div>
                    <label>Tuesday End</label>
                    <input type="time" name="schedule_tue_end" value="{school.schedule_tue_end}">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Wednesday Start</label>
                    <input type="time" name="schedule_wed_start" value="{school.schedule_wed_start}">
                </div>
                <div>
                    <label>Wednesday End</label>
                    <input type="time" name="schedule_wed_end" value="{school.schedule_wed_end}">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Thursday Start</label>
                    <input type="time" name="schedule_thu_start" value="{school.schedule_thu_start}">
                </div>
                <div>
                    <label>Thursday End</label>
                    <input type="time" name="schedule_thu_end" value="{school.schedule_thu_end}">
                </div>
            </div>
            <div class="form-row">
                <div>
                    <label>Friday Start</label>
                    <input type="time" name="schedule_fri_start" value="{school.schedule_fri_start}">
                </div>
                <div>
                    <label>Friday End</label>
                    <input type="time" name="schedule_fri_end" value="{school.schedule_fri_end}">
                </div>
            </div>
            
            <button type="submit" class="btn btn-success" style="margin-top:20px;">Save Changes</button>
            <a href="{url_for('schools')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return base_template('Edit School', content)

@app.route('/schools/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    return redirect(url_for('schools'))

@app.route('/schools/regenerate-key/<int:id>')
@login_required
@role_required('super_admin')
def regenerate_api_key(id):
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff_list():
    today = date.today()
    
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        staff = Staff.query.all()
    else:
        staff = Staff.query.filter_by(school_id=current_user.school_id).all()
    
    rows = ''
    for s in staff:
        attendance_today = Attendance.query.filter_by(staff_id=s.id, date=today).first()
        
        if s.department == 'Management':
            status = 'N/A'
            status_color = 'secondary'
        elif attendance_today:
            if attendance_today.sign_out_time:
                status = 'Signed Out'
                status_color = 'primary'
            else:
                status = 'Signed In'
                status_color = 'success'
        else:
            status = 'Absent'
            status_color = 'danger'
        
        active_badge = '<span class="badge badge-success">Active</span>' if s.is_active else '<span class="badge badge-danger">Inactive</span>'
        
        actions = f'<a href="{url_for("toggle_staff", id=s.id)}" class="btn btn-warning btn-sm">{"Deactivate" if s.is_active else "Activate"}</a>'
        if current_user.role == 'super_admin':
            actions += f' <a href="{url_for("delete_staff", id=s.id)}" class="btn btn-danger btn-sm" onclick="return confirm(\'Delete this staff?\')">Delete</a>'
        
        rows += f'''<tr>
            <td>{s.staff_id}</td>
            <td>{s.name}</td>
            <td>{s.school.short_name or s.school.name}</td>
            <td>{s.department}</td>
            <td><span class="badge badge-{status_color}">{status}</span></td>
            <td>{active_badge}</td>
            <td>{actions}</td>
        </tr>'''
    
    add_btn = ''
    if current_user.role in ['super_admin', 'school_admin']:
        add_btn = f'''
        <a href="{url_for('add_staff')}" class="btn btn-success">Add Staff</a>
        <a href="{url_for('bulk_upload')}" class="btn btn-primary">Bulk Upload</a>
        '''
    
    content = f'''
    <h2>Staff List</h2>
    <div style="margin-bottom:20px;">{add_btn}</div>
    <div class="card" style="overflow-x:auto;">
        <table>
            <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Department</th><th>Status</th><th>Active</th><th>Actions</th></tr>
            {rows}
        </table>
    </div>
    '''
    return base_template('Staff', content)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        department = request.form.get('department')
        school_id = request.form.get('school_id')
        
        if current_user.role == 'school_admin':
            school_id = current_user.school_id
        
        existing = Staff.query.filter_by(staff_id=staff_id).first()
        if existing:
            return base_template('Add Staff', '<div class="alert alert-danger">Staff ID already exists!</div><a href="' + url_for('add_staff') + '">Try again</a>')
        
        staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
        db.session.add(staff)
        db.session.commit()
        return redirect(url_for('staff_list'))
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
        school_options = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    else:
        school_options = f'<option value="{current_user.school_id}">{current_user.school.name}</option>'
    
    content = f'''
    <h2>Add Staff</h2>
    <div class="card">
        <form method="POST">
            <label>Staff ID</label>
            <input type="text" name="staff_id" required>
            
            <label>Full Name</label>
            <input type="text" name="name" required>
            
            <label>School</label>
            <select name="school_id" required>
                {school_options}
            </select>
            
            <label>Department</label>
            <select name="department" required>
                <option value="Academic">Academic</option>
                <option value="Admin">Admin</option>
                <option value="Non-Academic">Non-Academic</option>
                <option value="Management">Management</option>
            </select>
            
            <button type="submit" class="btn btn-success">Add Staff</button>
            <a href="{url_for('staff_list')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return base_template('Add Staff', content)

@app.route('/staff/toggle/<int:id>')
@login_required
@role_required('super_admin', 'school_admin')
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin' and staff.school_id != current_user.school_id:
        return redirect(url_for('staff_list'))
    staff.is_active = not staff.is_active
    db.session.commit()
    return redirect(url_for('staff_list'))

@app.route('/staff/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    return redirect(url_for('staff_list'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def bulk_upload():
    message = ''
    if request.method == 'POST':
        if 'file' not in request.files:
            message = '<div class="alert alert-danger">No file selected!</div>'
        else:
            file = request.files['file']
            if file.filename == '' or not file.filename.endswith('.csv'):
                message = '<div class="alert alert-danger">Please upload a CSV file!</div>'
            else:
                school_id = request.form.get('school_id')
                if current_user.role == 'school_admin':
                    school_id = current_user.school_id
                
                try:
                    stream = io.StringIO(file.stream.read().decode('UTF-8'))
                    reader = csv.DictReader(stream)
                    added = 0
                    skipped = 0
                    
                    for row in reader:
                        staff_id = row.get('staff_id', '').strip()
                        name = row.get('name', '').strip()
                        department = row.get('department', '').strip()
                        
                        if not staff_id or not name:
                            skipped += 1
                            continue
                        
                        if Staff.query.filter_by(staff_id=staff_id).first():
                            skipped += 1
                            continue
                        
                        if department not in ['Academic', 'Admin', 'Non-Academic', 'Management']:
                            department = 'Academic'
                        
                        staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
                        db.session.add(staff)
                        added += 1
                    
                    db.session.commit()
                    message = f'<div class="alert alert-success">Upload complete! Added: {added}, Skipped: {skipped}</div>'
                except Exception as e:
                    message = f'<div class="alert alert-danger">Error: {str(e)}</div>'
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
        school_options = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    else:
        school_options = f'<option value="{current_user.school_id}">{current_user.school.name}</option>'
    
    content = f'''
    <h2>Bulk Upload Staff</h2>
    {message}
    <div class="card">
        <p>Upload a CSV file with columns: <strong>staff_id, name, department</strong></p>
        <p>Department must be: Academic, Admin, Non-Academic, or Management</p>
        <form method="POST" enctype="multipart/form-data">
            <label>School</label>
            <select name="school_id" required>
                {school_options}
            </select>
            
            <label>CSV File</label>
            <input type="file" name="file" accept=".csv" required>
            
            <button type="submit" class="btn btn-success">Upload</button>
            <a href="{url_for('staff_list')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return base_template('Bulk Upload', content)

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    all_users = User.query.all()
    rows = ''
    for u in all_users:
        school_name = u.school.name if u.school else '-'
        rows += f'''<tr>
            <td>{u.username}</td>
            <td>{u.role}</td>
            <td>{school_name}</td>
            <td>{"Active" if u.is_active else "Inactive"}</td>
            <td>
                <a href="{url_for('delete_user', id=u.id)}" class="btn btn-danger btn-sm" onclick="return confirm('Delete this user?')">Delete</a>
            </td>
        </tr>'''
    
    content = f'''
    <h2>Users</h2>
    <a href="{url_for('add_user')}" class="btn btn-success" style="margin-bottom:20px;">Add User</a>
    <div class="card">
        <table>
            <tr><th>Username</th><th>Role</th><th>School</th><th>Status</th><th>Actions</th></tr>
            {rows}
        </table>
    </div>
    '''
    return base_template('Users', content)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        school_id = request.form.get('school_id') or None
        
        if User.query.filter_by(username=username).first():
            return base_template('Add User', '<div class="alert alert-danger">Username already exists!</div><a href="' + url_for('add_user') + '">Try again</a>')
        
        user = User(username=username, role=role, school_id=school_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('users'))
    
    schools = School.query.all()
    school_options = '<option value="">-- No School --</option>' + ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    
    content = f'''
    <h2>Add User</h2>
    <div class="card">
        <form method="POST">
            <label>Username</label>
            <input type="text" name="username" required>
            
            <label>Password</label>
            <input type="password" name="password" required>
            
            <label>Role</label>
            <select name="role" required>
                <option value="super_admin">Super Admin</option>
                <option value="hr_viewer">HR Viewer</option>
                <option value="ceo_viewer">CEO Viewer</option>
                <option value="school_admin">School Admin</option>
                <option value="staff">Staff</option>
            </select>
            
            <label>School (for School Admin/Staff)</label>
            <select name="school_id">
                {school_options}
            </select>
            
            <button type="submit" class="btn btn-success">Add User</button>
            <a href="{url_for('users')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return base_template('Add User', content)

@app.route('/users/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('users'))

@app.route('/reports/attendance')
@login_required
def attendance_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter_by(date=datetime.strptime(selected_date, '%Y-%m-%d').date())
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    attendance = query.all()
    
    rows = ''
    for a in attendance:
        late_badge = '<span class="badge badge-danger">Late</span>' if a.is_late else '<span class="badge badge-success">On Time</span>'
        rows += f'''<tr>
            <td>{a.staff.staff_id}</td>
            <td>{a.staff.name}</td>
            <td>{a.staff.school.short_name or a.staff.school.name}</td>
            <td>{a.sign_in_time.strftime('%H:%M') if a.sign_in_time else '-'}</td>
            <td>{a.sign_out_time.strftime('%H:%M') if a.sign_out_time else '-'}</td>
            <td>{late_badge}</td>
            <td>{a.late_minutes} mins</td>
        </tr>'''
    
    school_options = '<option value="">All Schools</option>'
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        for s in School.query.all():
            selected = 'selected' if str(s.id) == school_id else ''
            school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <h2>Attendance Report</h2>
    <div class="card">
        <form method="GET" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">
            <div>
                <label>Date</label>
                <input type="date" name="date" value="{selected_date}">
            </div>
            <div>
                <label>School</label>
                <select name="school_id">{school_options}</select>
            </div>
            <button type="submit" class="btn btn-primary">Filter</button>
            <a href="{url_for('download_attendance', date=selected_date, school_id=school_id)}" class="btn btn-success">Download CSV</a>
        </form>
    </div>
    <div class="card" style="overflow-x:auto;">
        <table>
            <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Sign In</th><th>Sign Out</th><th>Status</th><th>Late</th></tr>
            {rows if rows else '<tr><td colspan="7">No attendance records found.</td></tr>'}
        </table>
    </div>
    '''
    return base_template('Attendance Report', content)

@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter_by(date=datetime.strptime(selected_date, '%Y-%m-%d').date())
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    attendance = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late Minutes'])
    
    for a in attendance:
        writer.writerow([
            a.staff.staff_id,
            a.staff.name,
            a.staff.school.short_name or a.staff.school.name,
            a.staff.department,
            a.sign_in_time.strftime('%H:%M') if a.sign_in_time else '',
            a.sign_out_time.strftime('%H:%M') if a.sign_out_time else '',
            'Late' if a.is_late else 'On Time',
            a.late_minutes
        ])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=attendance_{selected_date}.csv'})

@app.route('/reports/late')
@login_required
def late_report():
    period = request.args.get('period', 'all')
    school_id = request.args.get('school_id', '')
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    staff_data = staff_query.all()
    
    rows = ''
    for s in staff_data:
        if s.department == 'Management':
            continue
        if s.times_late > 0:
            total_att = Attendance.query.filter_by(staff_id=s.id).count()
            late_count = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
            punctuality = round(((total_att - late_count) / total_att) * 100, 1) if total_att > 0 else 100
            lateness = round((late_count / total_att) * 100, 1) if total_att > 0 else 0
            
            rows += f'''<tr>
                <td>{s.staff_id}</td>
                <td>{s.name}</td>
                <td>{s.school.short_name or s.school.name}</td>
                <td>{s.times_late}</td>
                <td>{punctuality}%</td>
                <td>{lateness}%</td>
            </tr>'''
    
    school_options = '<option value="">All Schools</option>'
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        for s in School.query.all():
            selected = 'selected' if str(s.id) == school_id else ''
            school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    reset_form = ''
    if current_user.role == 'super_admin':
        reset_form = f'''
        <form method="POST" action="{url_for('reset_late_counter')}" style="margin-top:20px;">
            <select name="school_id">
                <option value="">All Schools</option>
                {''.join([f'<option value="{s.id}">{s.name}</option>' for s in School.query.all()])}
            </select>
            <button type="submit" class="btn btn-danger" onclick="return confirm('Reset all late counters?')">Reset Late Counters</button>
        </form>
        '''
    
    content = f'''
    <h2>Late Staff Report</h2>
    <div class="card">
        <form method="GET" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">
            <div>
                <label>Period</label>
                <select name="period">
                    <option value="all" {"selected" if period=="all" else ""}>All Time</option>
                    <option value="today" {"selected" if period=="today" else ""}>Today</option>
                    <option value="week" {"selected" if period=="week" else ""}>This Week</option>
                    <option value="month" {"selected" if period=="month" else ""}>This Month</option>
                </select>
            </div>
            <div>
                <label>School</label>
                <select name="school_id">{school_options}</select>
            </div>
            <button type="submit" class="btn btn-primary">Filter</button>
            <a href="{url_for('download_late_report', school_id=school_id)}" class="btn btn-success">Download CSV</a>
        </form>
        {reset_form}
    </div>
    <div class="card" style="overflow-x:auto;">
        <table>
            <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Times Late</th><th>% Punctuality</th><th>% Lateness</th></tr>
            {rows if rows else '<tr><td colspan="6">No late records found.</td></tr>'}
        </table>
    </div>
    '''
    return base_template('Late Report', content)

@app.route('/reports/late/download')
@login_required
def download_late_report():
    school_id = request.args.get('school_id', '')
    
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    staff_data = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
    
    for s in staff_data:
        if s.department == 'Management':
            continue
        if s.times_late > 0:
            total_att = Attendance.query.filter_by(staff_id=s.id).count()
            late_count = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
            punctuality = round(((total_att - late_count) / total_att) * 100, 1) if total_att > 0 else 100
            lateness = round((late_count / total_att) * 100, 1) if total_att > 0 else 0
            writer.writerow([s.staff_id, s.name, s.school.short_name or s.school.name, s.department, s.times_late, punctuality, lateness])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=late_report_{date.today()}.csv'})

@app.route('/reports/late/reset', methods=['POST'])
@login_required
@role_required('super_admin')
def reset_late_counter():
    school_id = request.form.get('school_id', '')
    
    if school_id:
        staff = Staff.query.filter_by(school_id=school_id).all()
    else:
        staff = Staff.query.all()
    
    for s in staff:
        s.times_late = 0
    
    db.session.commit()
    return redirect(url_for('late_report'))

@app.route('/reports/absent')
@login_required
def absent_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    check_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    all_staff = staff_query.all()
    
    rows = ''
    for s in all_staff:
        if s.department == 'Management':
            continue
        attendance = Attendance.query.filter_by(staff_id=s.id, date=check_date).first()
        if not attendance:
            rows += f'''<tr>
                <td>{s.staff_id}</td>
                <td>{s.name}</td>
                <td>{s.school.short_name or s.school.name}</td>
                <td>{s.department}</td>
            </tr>'''
    
    school_options = '<option value="">All Schools</option>'
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        for s in School.query.all():
            selected = 'selected' if str(s.id) == school_id else ''
            school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <h2>Absent Staff Report</h2>
    <div class="card">
        <form method="GET" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">
            <div>
                <label>Date</label>
                <input type="date" name="date" value="{selected_date}">
            </div>
            <div>
                <label>School</label>
                <select name="school_id">{school_options}</select>
            </div>
            <button type="submit" class="btn btn-primary">Filter</button>
            <a href="{url_for('download_absent_report', date=selected_date, school_id=school_id)}" class="btn btn-success">Download CSV</a>
        </form>
    </div>
    <div class="card" style="overflow-x:auto;">
        <table>
            <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Department</th></tr>
            {rows if rows else '<tr><td colspan="4">No absent staff found.</td></tr>'}
        </table>
    </div>
    '''
    return base_template('Absent Report', content)

@app.route('/reports/absent/download')
@login_required
def download_absent_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    check_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    all_staff = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department'])
    
    for s in all_staff:
        if s.department == 'Management':
            continue
        attendance = Attendance.query.filter_by(staff_id=s.id, date=check_date).first()
        if not attendance:
            writer.writerow([s.staff_id, s.name, s.school.short_name or s.school.name, s.department])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=absent_{selected_date}.csv'})

@app.route('/reports/overtime')
@login_required
def overtime_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter(
        Attendance.date == datetime.strptime(selected_date, '%Y-%m-%d').date(),
        Attendance.overtime_minutes > 0
    )
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    overtime = query.all()
    
    rows = ''
    for o in overtime:
        rows += f'''<tr>
            <td>{o.staff.staff_id}</td>
            <td>{o.staff.name}</td>
            <td>{o.staff.school.short_name or o.staff.school.name}</td>
            <td>{o.sign_out_time.strftime('%H:%M') if o.sign_out_time else '-'}</td>
            <td>{o.overtime_minutes} mins</td>
        </tr>'''
    
    school_options = '<option value="">All Schools</option>'
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        for s in School.query.all():
            selected = 'selected' if str(s.id) == school_id else ''
            school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <h2>Overtime Report</h2>
    <div class="card">
        <form method="GET" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">
            <div>
                <label>Date</label>
                <input type="date" name="date" value="{selected_date}">
            </div>
            <div>
                <label>School</label>
                <select name="school_id">{school_options}</select>
            </div>
            <button type="submit" class="btn btn-primary">Filter</button>
            <a href="{url_for('download_overtime_report', date=selected_date, school_id=school_id)}" class="btn btn-success">Download CSV</a>
        </form>
    </div>
    <div class="card" style="overflow-x:auto;">
        <table>
            <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Sign Out</th><th>Overtime</th></tr>
            {rows if rows else '<tr><td colspan="5">No overtime records found.</td></tr>'}
        </table>
    </div>
    '''
    return base_template('Overtime Report', content)

@app.route('/reports/overtime/download')
@login_required
def download_overtime_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter(
        Attendance.date == datetime.strptime(selected_date, '%Y-%m-%d').date(),
        Attendance.overtime_minutes > 0
    )
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    overtime = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department', 'Sign Out', 'Overtime (mins)'])
    
    for o in overtime:
        writer.writerow([
            o.staff.staff_id,
            o.staff.name,
            o.staff.school.short_name or o.staff.school.name,
            o.staff.department,
            o.sign_out_time.strftime('%H:%M') if o.sign_out_time else '',
            o.overtime_minutes
        ])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=overtime_{selected_date}.csv'})

# API for Kiosk
@app.route('/api/sync', methods=['GET', 'POST', 'OPTIONS'])
def api_sync():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        return response
    
    if request.method == 'GET':
        response = jsonify({'status': 'API is working', 'message': 'Use POST with X-API-Key header'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        response = jsonify({'error': 'API key required'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 401
    
    school = School.query.filter_by(api_key=api_key).first()
    
    if not school:
        response = jsonify({'error': 'Invalid API key'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 401
    
    data = request.get_json()
    
    if not data:
        response = jsonify({'error': 'No data provided'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 400
    
    action = data.get('action')
    
    if action == 'get_staff':
        staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
        staff_list_data = [{'id': s.staff_id, 'name': s.name, 'department': s.department} for s in staff]
        response = jsonify({'staff': staff_list_data, 'school_name': school.name})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    elif action == 'sync_attendance':
        records = data.get('records', [])
        synced = 0
        errors = []
        
        for record in records:
            try:
                staff = Staff.query.filter_by(staff_id=record['staff_id'], school_id=school.id).first()
                
                if not staff:
                    errors.append(f"Staff {record['staff_id']} not found")
                    continue
                
                record_date = datetime.strptime(record['date'], '%Y-%m-%d').date()
                record_time = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
                
                attendance = Attendance.query.filter_by(staff_id=staff.id, date=record_date).first()
                
                if record['type'] == 'sign_in':
                    if not attendance:
                        day_of_week = record_date.weekday()
                        start_time, end_time = get_school_schedule(school, day_of_week)
                        
                        is_late = False
                        late_minutes = 0
                        
                        if start_time:
                            scheduled_start = datetime.strptime(start_time, '%H:%M').time()
                            if record_time.time() > scheduled_start:
                                is_late = True
                                delta = datetime.combine(record_date, record_time.time()) - datetime.combine(record_date, scheduled_start)
                                late_minutes = int(delta.total_seconds() / 60)
                                staff.times_late += 1
                        
                        attendance = Attendance(
                            staff_id=staff.id,
                            date=record_date,
                            sign_in_time=record_time,
                            is_late=is_late,
                            late_minutes=late_minutes
                        )
                        db.session.add(attendance)
                        synced += 1
                
                elif record['type'] == 'sign_out':
                    if attendance and not attendance.sign_out_time:
                        attendance.sign_out_time = record_time
                        
                        day_of_week = record_date.weekday()
                        start_time, end_time = get_school_schedule(school, day_of_week)
                        
                        if end_time:
                            scheduled_end = datetime.strptime(end_time, '%H:%M').time()
                            if record_time.time() > scheduled_end:
                                delta = datetime.combine(record_date, record_time.time()) - datetime.combine(record_date, scheduled_end)
                                attendance.overtime_minutes = int(delta.total_seconds() / 60)
                        
                        synced += 1
            
            except Exception as e:
                errors.append(str(e))
        
        db.session.commit()
        
        response = jsonify({'success': True, 'synced': synced, 'errors': errors})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    elif action == 'check_status':
        staff_id = data.get('staff_id')
        staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
        
        if not staff:
            response = jsonify({'error': 'Staff not found'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 404
        
        today_date = date.today()
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today_date).first()
        
        if attendance:
            if attendance.sign_out_time:
                status = 'signed_out'
            else:
                status = 'signed_in'
        else:
            status = 'not_signed_in'
        
        response = jsonify({'staff_name': staff.name, 'status': status})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    response = jsonify({'error': 'Invalid action'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 400

@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='super_admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        return 'Database initialized successfully!'
    except Exception as e:
        return f'Error: {str(e)}'

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
