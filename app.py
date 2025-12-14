from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
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
    <title>{{ title }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; }
        .navbar { background: #16213e; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
        .navbar h1 { color: #e94560; }
        .navbar a { color: #aaa; text-decoration: none; margin-left: 1rem; }
        .navbar a:hover { color: #e94560; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .card { background: #16213e; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { color: #e94560; margin-bottom: 1rem; }
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; margin: 0.2rem; }
        .btn-primary { background: #e94560; color: white; }
        .btn-success { background: #2ecc71; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-secondary { background: #0f3460; color: white; }
        input, select { padding: 0.5rem; border: 1px solid #0f3460; border-radius: 5px; background: #1a1a2e; color: white; margin: 0.2rem 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #0f3460; }
        th { color: #e94560; }
        .flash { padding: 1rem; border-radius: 5px; margin-bottom: 1rem; }
        .flash.error { background: #e74c3c33; border: 1px solid #e74c3c; }
        .flash.success { background: #2ecc7133; border: 1px solid #2ecc71; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
        .stat-card { background: #0f3460; border-radius: 10px; padding: 1.5rem; text-align: center; }
        .stat-card h3 { color: #aaa; font-size: 0.9rem; }
        .stat-card .number { font-size: 2.5rem; color: #e94560; font-weight: bold; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; color: #aaa; }
        .badge { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.8rem; color: white; }
        .badge-success { background: #2ecc71; }
        .badge-danger { background: #e74c3c; }
    </style>
</head>
<body>
    {% if current_user.is_authenticated %}
    <div class="navbar">
        <h1>Attendance System</h1>
        <nav>
            <a href="{{ url_for('dashboard') }}">Dashboard</a>
            <a href="{{ url_for('today') }}">Today</a>
            <a href="{{ url_for('attendance') }}">Reports</a>
            <a href="{{ url_for('staff') }}">Staff</a>
            {% if current_user.role == 'superadmin' %}
            <a href="{{ url_for('schools') }}">Schools</a>
            <a href="{{ url_for('admins') }}">Admins</a>
            {% endif %}
            <a href="{{ url_for('settings') }}">Settings</a>
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
    if not School.query.first():
        for i in range(1, 8):
            school = School(name='School ' + str(i), code='SCH' + str(i).zfill(3), api_key=secrets.token_hex(32))
            db.session.add(school)
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
    content = '''
    <div style="max-width: 400px; margin: 4rem auto;">
        <div class="card">
            <h2 style="text-align: center;">Staff Attendance System</h2>
            <form method="POST" style="margin-top: 1rem;">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" name="username" required style="width: 100%;">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" name="password" required style="width: 100%;">
                </div>
                <button type="submit" class="btn btn-primary" style="width: 100%;">Login</button>
            </form>
        </div>
    </div>
    '''
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; }
            .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
            .card { background: #16213e; border-radius: 10px; padding: 1.5rem; margin-bottom: 1.5rem; }
            .card h2 { color: #e94560; margin-bottom: 1rem; }
            .btn { padding: 0.5rem 1rem; border: none; border-radius: 5px; cursor: pointer; }
            .btn-primary { background: #e94560; color: white; }
            input { padding: 0.5rem; border: 1px solid #0f3460; border-radius: 5px; background: #1a1a2e; color: white; }
            .form-group { margin-bottom: 1rem; }
            .form-group label { display: block; margin-bottom: 0.5rem; color: #aaa; }
            .flash { padding: 1rem; border-radius: 5px; margin-bottom: 1rem; }
            .flash.error { background: #e74c3c33; border: 1px solid #e74c3c; }
        </style>
    </head>
    <body>
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
            {% endwith %}
            <div style="max-width: 400px; margin: 4rem auto;">
                <div class="card">
                    <h2 style="text-align: center;">Staff Attendance System</h2>
                    <form method="POST" style="margin-top: 1rem;">
                        <div class="form-group">
                            <label>Username</label>
                            <input type="text" name="username" required style="width: 100%;">
                        </div>
                        <div class="form-group">
                            <label>Password</label>
                            <input type="password" name="password" required style="width: 100%;">
                        </div>
                        <button type="submit" class="btn btn-primary" style="width: 100%;">Login</button>
                    </form>
                </div>
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
        stats_html += f'''
        <div class="stat-card">
            <h3>{school.name}</h3>
            <div class="number">0</div>
            <div>Currently On Site</div>
            <div style="margin-top: 0.5rem; font-size: 0.9rem; color: #888;">0 signed in today / {total_staff} total staff</div>
        </div>
        '''
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Dashboard</h2>
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
            <td>{school.name}</td>
            <td>{school.code}</td>
            <td><code>{school.api_key[:20]}...</code></td>
            <td>{school.last_sync or 'Never'}</td>
            <td>
                <a href="{url_for('edit_school', school_id=school.id)}" class="btn btn-secondary">Edit</a>
            </td>
        </tr>
        '''
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Schools</h2>
    <div class="card">
        <table>
            <thead>
                <tr><th>Name</th><th>Code</th><th>API Key</th><th>Last Sync</th><th>Actions</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    '''
    return render('Schools', content)

@app.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_school(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        school.name = request.form.get('name')
        db.session.commit()
        flash('School updated', 'success')
        return redirect(url_for('schools'))
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Edit School</h2>
    <div class="card" style="max-width: 500px;">
        <form method="POST">
            <div class="form-group">
                <label>School Name</label>
                <input type="text" name="name" value="{school.name}" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>API Key</label>
                <input type="text" value="{school.api_key}" readonly style="width: 100%;">
            </div>
            <button type="submit" class="btn btn-primary">Save</button>
            <a href="{url_for('schools')}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    return render('Edit School', content)

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
            <td>{s.staff_id}</td>
            <td>{s.name}</td>
            <td>{s.department or '-'}</td>
            <td>{school.name if school else '-'}</td>
            <td>{status}</td>
            <td>
                <form method="POST" action="{url_for('toggle_staff', id=s.id)}" style="display:inline;">
                    <button type="submit" class="btn btn-secondary">Toggle</button>
                </form>
                <form method="POST" action="{url_for('delete_staff', id=s.id)}" style="display:inline;">
                    <button type="submit" class="btn btn-danger">Delete</button>
                </form>
            </td>
        </tr>
        '''
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Staff</h2>
    <a href="{url_for('add_staff')}" class="btn btn-success" style="margin-bottom: 1rem;">+ Add Staff</a>
    <div class="card">
        <table>
            <thead>
                <tr><th>Staff ID</th><th>Name</th><th>Department</th><th>School</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>{rows}</tbody>
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
    <h2 style="margin-bottom: 1.5rem;">Add Staff</h2>
    <div class="card" style="max-width: 500px;">
        <form method="POST">
            <div class="form-group">
                <label>School</label>
                <select name="school_id" required style="width: 100%;">{options}</select>
            </div>
            <div class="form-group">
                <label>Staff ID</label>
                <input type="text" name="staff_id" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>Name</label>
                <input type="text" name="name" required style="width: 100%;">
            </div>
            <div class="form-group">
                <label>Department</label>
                <input type="text" name="department" style="width: 100%;">
            </div>
            <button type="submit" class="btn btn-success">Add</button>
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
    content = '''
    <h2 style="margin-bottom: 1.5rem;">Attendance Reports</h2>
    <div class="card">
        <p>Attendance records will appear here once staff start signing in.</p>
    </div>
    '''
    return render('Attendance', content)

@app.route('/today')
@login_required
def today():
    content = '''
    <h2 style="margin-bottom: 1.5rem;">Today's Activity</h2>
    <div class="card">
        <p>Today's sign-ins will appear here.</p>
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
            <td>{admin.username}</td>
            <td>{admin.role}</td>
            <td>{school.name if school else 'All Schools'}</td>
            <td>
                {'<form method="POST" action="' + url_for('delete_admin', id=admin.id) + '" style="display:inline;"><button type="submit" class="btn btn-danger">Delete</button></form>' if admin.id != current_user.id else ''}
            </td>
        </tr>
        '''
    options = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Admin Users</h2>
    <div class="card">
        <h2>Add New Admin</h2>
        <form method="POST" action="{url_for('add_admin')}">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <div class="form-group">
                <label>Role</label>
                <select name="role">
                    <option value="superadmin">Super Admin</option>
                    <option value="schooladmin">School Admin</option>
                </select>
            </div>
            <div class="form-group">
                <label>School (for School Admin)</label>
                <select name="school_id">{options}</select>
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
                flash('Password changed', 'success')
            else:
                flash('Passwords do not match', 'error')
        else:
            flash('Current password incorrect', 'error')
    content = f'''
    <h2 style="margin-bottom: 1.5rem;">Settings</h2>
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
                <label>Confirm Password</label>
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
