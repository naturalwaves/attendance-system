from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:bigdaddy8624@db.ytavcjojzfbshstoewmc.supabase.co:5432/postgres')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    last_sync = db.Column(db.DateTime)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    action = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    local_id = db.Column(db.Integer)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

BASE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} | Staff Attendance</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', Arial, sans-serif; background: #f5f5f5; color: #333; }
        .navbar { background: #ffffff; padding: 0.75rem 2rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; box-shadow: 0 2px 10px rgba(0,0,0,0.08); border-bottom: 3px solid #c41e3a; }
        .navbar .logo-section { display: flex; align-items: center; gap: 12px; }
        .navbar .logo-section img { height: 45px; }
        .navbar .logo-section h1 { color: #c41e3a; font-size: 1.3rem; font-weight: 700; }
        .navbar nav { display: flex; align-items: center; gap: 0.5rem; }
        .navbar a { color: #555; text-decoration: none; padding: 0.5rem 1rem; border-radius: 6px; font-weight: 500; transition: all 0.2s; }
        .navbar a:hover { color: #c41e3a; background: #fff5f5; }
        .navbar a.active { color: #c41e3a; background: #fff0f0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .page-header { margin-bottom: 1.5rem; }
        .page-header h2 { color: #333; font-size: 1.75rem; font-weight: 700; }
        .card { background: #ffffff; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: 1px solid #eee; }
        .card h2 { color: #c41e3a; margin-bottom: 1rem; font-size: 1.1rem; font-weight: 600; }
        .btn { padding: 0.6rem 1.2rem; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; display: inline-block; margin: 0.2rem; font-weight: 500; font-size: 0.9rem; transition: all 0.2s; }
        .btn-primary { background: #c41e3a; color: white; }
        .btn-primary:hover { background: #a01830; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover { background: #5a6268; }
        input, select { padding: 0.6rem 0.8rem; border: 1px solid #ddd; border-radius: 8px; background: #fff; color: #333; margin: 0.2rem 0; font-size: 0.95rem; transition: border-color 0.2s; }
        input:focus, select:focus { outline: none; border-color: #c41e3a; box-shadow: 0 0 0 3px rgba(196,30,58,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 1rem; text-align: left; border-bottom: 1px solid #eee; }
        th { color: #666; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; background: #fafafa; }
        tr:hover { background: #fafafa; }
        .flash { padding: 1rem 1.25rem; border-radius: 8px; margin-bottom: 1rem; font-weight: 500; }
        .flash.error { background: #fff5f5; border: 1px solid #ffcdd2; color: #c41e3a; }
        .flash.success { background: #f0fff4; border: 1px solid #c6f6d5; color: #28a745; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.25rem; }
        .stat-card { background: #ffffff; border-radius: 12px; padding: 1.5rem; text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: 1px solid #eee; transition: transform 0.2s, box-shadow 0.2s; }
        .stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        .stat-card h3 { color: #666; font-size: 0.9rem; font-weight: 600; margin-bottom: 0.5rem; }
        .stat-card .number { font-size: 2.75rem; color: #c41e3a; font-weight: 700; }
        .stat-card .label { color: #888; font-size: 0.85rem; margin-top: 0.25rem; }
        .form-group { margin-bottom: 1.25rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; color: #555; font-weight: 500; font-size: 0.9rem; }
        .badge { padding: 0.35rem 0.75rem; border-radius: 50px; font-size: 0.8rem; color: white; font-weight: 500; }
        .badge-success { background: #28a745; }
        .badge-danger { background: #dc3545; }
        .badge-in { background: #28a745; }
        .badge-out { background: #6c757d; }
        code { background: #f5f5f5; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.85rem; color: #666; }
        hr { border: none; border-top: 1px solid #eee; margin: 1.5rem 0; }
        .filter-bar { display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; padding: 1rem; background: #fafafa; border-radius: 8px; margin-bottom: 1rem; }
        .empty-state { text-align: center; padding: 3rem; color: #888; }
        .empty-state p { font-size: 1rem; }
    </style>
</head>
<body>
    {% if current_user.is_authenticated %}
    <div class="navbar">
        <div class="logo-section">
            <img src="https://i.imgur.com/yARMhzG.png" alt="Logo">
            <h1>Staff Attendance</h1>
        </div>
        <nav>
            <a href="{{ url_for('dashboard') }}" class="{{ 'active' if request.endpoint == 'dashboard' else '' }}">Dashboard</a>
            <a href="{{ url_for('today') }}" class="{{ 'active' if request.endpoint == 'today' else '' }}">Today</a>
            <a href="{{ url_for('attendance') }}" class="{{ 'active' if request.endpoint == 'attendance' else '' }}">Reports</a>
            <a href="{{ url_for('staff') }}" class="{{ 'active' if request.endpoint in ['staff', 'add_staff'] else '' }}">Staff</a>
            {% if current_user.role == 'superadmin' %}
            <a href="{{ url_for('schools') }}" class="{{ 'active' if request.endpoint in ['schools', 'add_school', 'edit_school'] else '' }}">Schools</a>
            <a href="{{ url_for('admins') }}" class="{{ 'active' if request.endpoint == 'admins' else '' }}">Admins</a>
            {% endif %}
            <a href="{{ url_for('settings') }}" class="{{ 'active' if request.endpoint == 'settings' else '' }}">Settings</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </nav>
    </div>
    {% endif %}
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
        <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
        {% endwith %}
        {{ content|safe }}
    </div>
</body>
</html>
'''

def render(title, content):
    return render_template_string(BASE_HTML, title=title, content=content)

def init_db():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='superadmin')
        db.session.add(admin)
        db.session.commit()

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
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login | Staff Attendance</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Inter', Arial, sans-serif; background: linear-gradient(135deg, #f5f5f5 0%, #e0e0e0 100%); color: #333; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
            .login-container { width: 100%; max-width: 420px; padding: 2rem; }
            .card { background: #ffffff; border-radius: 16px; padding: 2.5rem; box-shadow: 0 10px 40px rgba(0,0,0,0.1); border-top: 4px solid #c41e3a; }
            .logo-section { text-align: center; margin-bottom: 2rem; }
            .logo-section img { height: 70px; margin-bottom: 1rem; }
            .logo-section h2 { color: #333; font-size: 1.5rem; font-weight: 700; }
            .logo-section p { color: #888; font-size: 0.9rem; margin-top: 0.5rem; }
            .btn { width: 100%; padding: 0.85rem; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 1rem; transition: all 0.2s; }
            .btn-primary { background: #c41e3a; color: white; }
            .btn-primary:hover { background: #a01830; }
            input { width: 100%; padding: 0.85rem; border: 1px solid #ddd; border-radius: 8px; background: #fff; color: #333; font-size: 1rem; transition: border-color 0.2s; }
            input:focus { outline: none; border-color: #c41e3a; box-shadow: 0 0 0 3px rgba(196,30,58,0.1); }
            .form-group { margin-bottom: 1.25rem; }
            .form-group label { display: block; margin-bottom: 0.5rem; color: #555; font-weight: 500; }
            .flash { padding: 1rem; border-radius: 8px; margin-bottom: 1rem; font-weight: 500; }
            .flash.error { background: #fff5f5; border: 1px solid #ffcdd2; color: #c41e3a; }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="card">
                <div class="logo-section">
                    <img src="https://i.imgur.com/yARMhzG.png" alt="Logo">
                    <h2>Staff Attendance</h2>
                    <p>Sign in to continue</p>
                </div>
                {% with messages = get_flashed_messages(with_categories=true) %}
                {% for category, message in messages %}
                <div class="flash {{ category }}">{{ message }}</div>
                {% endfor %}
                {% endwith %}
                <form method="POST">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" name="username" required placeholder="Enter your username">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" name="password" required placeholder="Enter your password">
                    </div>
                    <button type="submit" class="btn btn-primary">Sign In</button>
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
    schools = School.query.all() if current_user.role == 'superadmin' else School.query.filter_by(id=current_user.school_id).all()
    stats_html = ''
    for school in schools:
        total_staff = Staff.query.filter_by(school_id=school.id, active=True).count()
        today = datetime.now().date()
        signed_in_today = db.session.query(Attendance.staff_id).filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.timestamp) == today,
            Attendance.action == 'IN'
        ).distinct().count()
        stats_html += f'''
        <div class="stat-card">
            <h3>{school.name}</h3>
            <div class="number">{signed_in_today}</div>
            <div class="label">Signed In Today</div>
            <div style="margin-top: 0.75rem; font-size: 0.85rem; color: #888;">{total_staff} total staff</div>
        </div>
        '''
    if not stats_html:
        stats_html = '<div class="card"><p style="text-align:center; color:#888;">No schools yet. Go to Schools to add one.</p></div>'
    content = f'''
    <div class="page-header">
        <h2>Dashboard</h2>
    </div>
    <div class="stats-grid">{stats_html}</div>
    '''
    return render('Dashboard', content)

@app.route('/schools')
@login_required
def schools():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    schools = School.query.all()
    rows = ''
    for school in schools:
        rows += f'''
        <tr>
            <td><strong>{school.name}</strong></td>
            <td><code>{school.code}</code></td>
            <td><code>{school.api_key[:20]}...</code></td>
            <td>{school.last_sync.strftime('%Y-%m-%d %H:%M') if school.last_sync else '<span style="color:#888;">Never</span>'}</td>
            <td>
                <a href="{url_for('edit_school', school_id=school.id)}" class="btn btn-secondary">Edit</a>
                <form method="POST" action="{url_for('delete_school', school_id=school.id)}" style="display:inline;" onsubmit="return confirm('Delete this school and all its data?');">
                    <button type="submit" class="btn btn-danger">Delete</button>
                </form>
            </td>
        </tr>
        '''
    empty_state = '<tr><td colspan="5" class="empty-state"><p>No schools yet. Click "Add School" to get started.</p></td></tr>'
    content = f'''
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: center;">
        <h2>Schools</h2>
        <a href="{url_for('add_school')}" class="btn btn-success">+ Add School</a>
    </div>
    <div class="card">
        <table>
            <thead>
                <tr><th>Name</th><th>Code</th><th>API Key</th><th>Last Sync</th><th>Actions</th></tr>
            </thead>
            <tbody>{rows if rows else empty_state}</tbody>
        </table>
    </div>
    '''
    return render('Schools', content)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        if School.query.filter_by(code=code).first():
            flash('School code already exists', 'error')
        else:
            new_school = School(name=name, code=code, api_key=secrets.token_hex(32))
            db.session.add(new_school)
            db.session.commit()
            flash('School added successfully', 'success')
            return redirect(url_for('schools'))
    content = f'''
    <div class="page-header">
        <h2>Add School</h2>
    </div>
    <div class="card" style="max-width: 500px;">
        <form method="POST">
            <div class="form-group">
                <label>School Name</label>
                <input type="text" name="name" required style="width: 100%;" placeholder="e.g. Sunshine Primary School">
            </div>
            <div class="form-group">
                <label>School Code</label>
                <input type="text" name="code" required style="width: 100%;" placeholder="e.g. SPS001">
            </div>
            <button type="submit" class="btn btn-success">Add School</button>
            <a href="{url_for('schools')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return render('Add School', content)

@app.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_school(school_id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        school.name = request.form.get('name')
        db.session.commit()
        flash('School updated', 'success')
        return redirect(url_for('schools'))
    content = f'''
    <div class="page-header">
        <h2>Edit School</h2>
    </div>
    <div class="card" style="max-width: 500px;">
        <form method="POST">
            <div class="form-group">
                <label>School Name</label>
                <input type="text" name="name" value="{school.name}" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>School Code</label>
                <input type="text" value="{school.code}" readonly style="width: 100%; background: #f5f5f5;">
            </div>
            <div class="form-group">
                <label>API Key (for kiosk setup)</label>
                <input type="text" value="{school.api_key}" readonly style="width: 100%; background: #f5f5f5;" onclick="this.select();">
            </div>
            <button type="submit" class="btn btn-primary">Save Changes</button>
            <a href="{url_for('schools')}" class="btn btn-secondary">Cancel</a>
        </form>
        <hr>
        <form method="POST" action="{url_for('regenerate_api_key', school_id=school.id)}" onsubmit="return confirm('Regenerate API key? The kiosk will need reconfiguring.');">
            <button type="submit" class="btn btn-danger">Regenerate API Key</button>
        </form>
    </div>
    '''
    return render('Edit School', content)

@app.route('/schools/<int:school_id>/delete', methods=['POST'])
@login_required
def delete_school(school_id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(school_id)
    Staff.query.filter_by(school_id=school_id).delete()
    Attendance.query.filter_by(school_id=school_id).delete()
    User.query.filter_by(school_id=school_id).delete()
    db.session.delete(school)
    db.session.commit()
    flash('School deleted', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/<int:school_id>/regenerate-key', methods=['POST'])
@login_required
def regenerate_api_key(school_id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(school_id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated', 'success')
    return redirect(url_for('edit_school', school_id=school_id))

@app.route('/staff')
@login_required
def staff():
    schools = School.query.all() if current_user.role == 'superadmin' else School.query.filter_by(id=current_user.school_id).all()
    staff_list = Staff.query.all() if current_user.role == 'superadmin' else Staff.query.filter_by(school_id=current_user.school_id).all()
    rows = ''
    for s in staff_list:
        school = School.query.get(s.school_id)
        status = '<span class="badge badge-success">Active</span>' if s.active else '<span class="badge badge-danger">Inactive</span>'
        rows += f'''
        <tr>
            <td><strong>{s.staff_id}</strong></td>
            <td>{s.name}</td>
            <td>{s.department or '<span style="color:#888;">-</span>'}</td>
            <td>{school.name if school else '-'}</td>
            <td>{status}</td>
            <td>
                <form method="POST" action="{url_for('toggle_staff', id=s.id)}" style="display:inline;">
                    <button type="submit" class="btn btn-secondary">Toggle</button>
                </form>
                <form method="POST" action="{url_for('delete_staff', id=s.id)}" style="display:inline;" onsubmit="return confirm('Delete this staff member?');">
                    <button type="submit" class="btn btn-danger">Delete</button>
                </form>
            </td>
        </tr>
        '''
    empty_state = '<tr><td colspan="6" class="empty-state"><p>No staff members yet. Click "Add Staff" to get started.</p></td></tr>'
    content = f'''
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: center;">
        <h2>Staff</h2>
        <a href="{url_for('add_staff')}" class="btn btn-success">+ Add Staff</a>
    </div>
    <div class="card">
        <table>
            <thead>
                <tr><th>Staff ID</th><th>Name</th><th>Department</th><th>School</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>{rows if rows else empty_state}</tbody>
        </table>
    </div>
    '''
    return render('Staff', content)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all() if current_user.role == 'superadmin' else School.query.filter_by(id=current_user.school_id).all()
    if request.method == 'POST':
        new_staff = Staff(staff_id=request.form.get('staff_id'), name=request.form.get('name'), department=request.form.get('department'), school_id=request.form.get('school_id', type=int))
        db.session.add(new_staff)
        db.session.commit()
        flash('Staff added', 'success')
        return redirect(url_for('staff'))
    options = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    content = f'''
    <div class="page-header">
        <h2>Add Staff</h2>
    </div>
    <div class="card" style="max-width: 500px;">
        <form method="POST">
            <div class="form-group">
                <label>School</label>
                <select name="school_id" required style="width: 100%;">{options}</select>
            </div>
            <div class="form-group">
                <label>Staff ID</label>
                <input type="text" name="staff_id" required style="width: 100%;" placeholder="e.g. EMP001">
            </div>
            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="name" required style="width: 100%;" placeholder="e.g. John Smith">
            </div>
            <div class="form-group">
                <label>Department (optional)</label>
                <input type="text" name="department" style="width: 100%;" placeholder="e.g. Administration">
            </div>
            <button type="submit" class="btn btn-success">Add Staff</button>
            <a href="{url_for('staff')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return render('Add Staff', content)

@app.route('/staff/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_staff(id):
    staff_member = Staff.query.get_or_404(id)
    staff_member.active = not staff_member.active
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/staff/<int:id>/delete', methods=['POST'])
@login_required
def delete_staff(id):
    staff_member = Staff.query.get_or_404(id)
    db.session.delete(staff_member)
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/attendance')
@login_required
def attendance():
    schools = School.query.all() if current_user.role == 'superadmin' else School.query.filter_by(id=current_user.school_id).all()
    school_id = request.args.get('school_id', type=int)
    date_from = request.args.get('date_from', (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', datetime.now().strftime('%Y-%m-%d'))
    
    query = Attendance.query.filter(
        db.func.date(Attendance.timestamp) >= date_from,
        db.func.date(Attendance.timestamp) <= date_to
    )
    if school_id:
        query = query.filter(Attendance.school_id == school_id)
    elif current_user.role != 'superadmin':
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.order_by(Attendance.timestamp.desc()).all()
    
    rows = ''
    for r in records:
        staff = Staff.query.filter_by(staff_id=r.staff_id, school_id=r.school_id).first()
        school = School.query.get(r.school_id)
        action_badge = '<span class="badge badge-in">IN</span>' if r.action == 'IN' else '<span class="badge badge-out">OUT</span>'
        rows += f'''
        <tr>
            <td>{r.timestamp.strftime('%Y-%m-%d')}</td>
            <td>{r.timestamp.strftime('%H:%M:%S')}</td>
            <td><strong>{r.staff_id}</strong></td>
            <td>{staff.name if staff else '<span style="color:#888;">Unknown</span>'}</td>
            <td>{school.name if school else '-'}</td>
            <td>{action_badge}</td>
        </tr>
        '''
    
    school_options = ''.join([f'<option value="{s.id}" {"selected" if school_id == s.id else ""}>{s.name}</option>' for s in schools])
    empty_state = '<tr><td colspan="6" class="empty-state"><p>No attendance records found.</p></td></tr>'
    
    content = f'''
    <div class="page-header">
        <h2>Attendance Reports</h2>
    </div>
    <div class="card">
        <form method="GET" class="filter-bar">
            <select name="school_id" style="padding: 0.6rem;">
                <option value="">All Schools</option>
                {school_options}
            </select>
            <input type="date" name="date_from" value="{date_from}">
            <span style="color: #888;">to</span>
            <input type="date" name="date_to" value="{date_to}">
            <button type="submit" class="btn btn-primary">Filter</button>
        </form>
    </div>
    <div class="card">
        <table>
            <thead>
                <tr><th>Date</th><th>Time</th><th>Staff ID</th><th>Name</th><th>School</th><th>Action</th></tr>
            </thead>
            <tbody>{rows if rows else empty_state}</tbody>
        </table>
    </div>
    '''
    return render('Attendance Reports', content)

@app.route('/today')
@login_required
def today():
    today_date = datetime.now().date()
    
    query = Attendance.query.filter(db.func.date(Attendance.timestamp) == today_date)
    if current_user.role != 'superadmin':
        query = query.filter(Attendance.school_id == current_user.school_id)
    
    records = query.order_by(Attendance.timestamp.desc()).all()
    
    rows = ''
    for r in records:
        staff = Staff.query.filter_by(staff_id=r.staff_id, school_id=r.school_id).first()
        school = School.query.get(r.school_id)
        action_badge = '<span class="badge badge-in">IN</span>' if r.action == 'IN' else '<span class="badge badge-out">OUT</span>'
        rows += f'''
        <tr>
            <td>{r.timestamp.strftime('%H:%M:%S')}</td>
            <td><strong>{r.staff_id}</strong></td>
            <td>{staff.name if staff else '<span style="color:#888;">Unknown</span>'}</td>
            <td>{school.name if school else '-'}</td>
            <td>{action_badge}</td>
        </tr>
        '''
    
    empty_state = '<tr><td colspan="5" class="empty-state"><p>No activity today yet.</p></td></tr>'
    
    content = f'''
    <div class="page-header">
        <h2>Today's Activity</h2>
        <p style="color: #888; margin-top: 0.5rem;">{today_date.strftime('%A, %d %B %Y')}</p>
    </div>
    <div class="card">
        <table>
            <thead>
                <tr><th>Time</th><th>Staff ID</th><th>Name</th><th>School</th><th>Action</th></tr>
            </thead>
            <tbody>{rows if rows else empty_state}</tbody>
        </table>
    </div>
    '''
    return render('Today', content)

@app.route('/admins')
@login_required
def admins():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    all_admins = User.query.all()
    schools = School.query.all()
    rows = ''
    for admin in all_admins:
        school = School.query.get(admin.school_id) if admin.school_id else None
        rows += f'''
        <tr>
            <td><strong>{admin.username}</strong></td>
            <td><span class="badge" style="background: {'#c41e3a' if admin.role == 'superadmin' else '#6c757d'};">{admin.role}</span></td>
            <td>{school.name if school else '<span style="color:#888;">All Schools</span>'}</td>
            <td>
                {'<form method="POST" action="' + url_for('delete_admin', id=admin.id) + '" style="display:inline;" onsubmit="return confirm(\'Delete this admin?\');"><button type="submit" class="btn btn-danger">Delete</button></form>' if admin.id != current_user.id else '<span style="color:#888;">Current User</span>'}
            </td>
        </tr>
        '''
    options = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    content = f'''
    <div class="page-header">
        <h2>Admin Users</h2>
    </div>
    <div class="card">
        <h2>Add New Admin</h2>
        <form method="POST" action="{url_for('add_admin')}">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" name="username" required style="width: 100%;">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" name="password" required style="width: 100%;">
                </div>
                <div class="form-group">
                    <label>Role</label>
                    <select name="role" style="width: 100%;">
                        <option value="superadmin">Super Admin</option>
                        <option value="schooladmin">School Admin</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>School (for School Admin)</label>
                    <select name="school_id" style="width: 100%;">{options}</select>
                </div>
            </div>
            <button type="submit" class="btn btn-success">Add Admin</button>
        </form>
    </div>
    <div class="card">
        <h2>Existing Admins</h2>
        <table>
            <thead><tr><th>Username</th><th>Role</th><th>School</th><th>Actions</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    '''
    return render('Admins', content)

@app.route('/admins/add', methods=['POST'])
@login_required
def add_admin():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school_id = request.form.get('school_id', type=int) if request.form.get('role') == 'schooladmin' else None
    new_admin = User(username=request.form.get('username'), password_hash=generate_password_hash(request.form.get('password')), role=request.form.get('role'), school_id=school_id)
    db.session.add(new_admin)
    db.session.commit()
    flash('Admin created', 'success')
    return redirect(url_for('admins'))

@app.route('/admins/<int:id>/delete', methods=['POST'])
@login_required
def delete_admin(id):
    if current_user.role != 'superadmin' or id == current_user.id:
        return redirect(url_for('admins'))
    admin = User.query.get_or_404(id)
    db.session.delete(admin)
    db.session.commit()
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        if check_password_hash(current_user.password_hash, request.form.get('current_password')):
            if request.form.get('new_password') == request.form.get('confirm_password'):
                current_user.password_hash = generate_password_hash(request.form.get('new_password'))
                db.session.commit()
                flash('Password changed successfully', 'success')
            else:
                flash('Passwords do not match', 'error')
        else:
            flash('Current password is incorrect', 'error')
    content = f'''
    <div class="page-header">
        <h2>Settings</h2>
    </div>
    <div class="card" style="max-width: 500px;">
        <h2>Change Password</h2>
        <form method="POST">
            <div class="form-group">
                <label>Current Password</label>
                <input type="password" name="current_password" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>New Password</label>
                <input type="password" name="new_password" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>Confirm New Password</label>
                <input type="password" name="confirm_password" required style="width: 100%;">
            </div>
            <button type="submit" class="btn btn-primary">Change Password</button>
        </form>
    </div>
    '''
    return render('Settings', content)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    data = request.get_json()
    synced_ids = []
    for record in data.get('attendance', []):
        if not Attendance.query.filter_by(school_id=school.id, local_id=record['local_id']).first():
            db.session.add(Attendance(staff_id=record['staff_id'], school_id=school.id, action=record['action'], timestamp=datetime.fromisoformat(record['timestamp']), local_id=record['local_id']))
        synced_ids.append(record['local_id'])
    school.last_sync = datetime.utcnow()
    db.session.commit()
    staff_list = [{'staff_id': s.staff_id, 'name': s.name, 'department': s.department, 'active': s.active} for s in Staff.query.filter_by(school_id=school.id).all()]
    return jsonify({'success': True, 'synced_ids': synced_ids, 'staff': staff_list})

@app.route('/api/check')
def api_check():
    return jsonify({'status': 'ok'})

with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
