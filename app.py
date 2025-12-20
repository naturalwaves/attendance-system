from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import os
import csv
import io
from collections import defaultdict

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
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Attendance System')
    company_logo_url = db.Column(db.String(500))
    late_threshold_minutes = db.Column(db.Integer, default=15)
    work_start_time = db.Column(db.String(10), default='08:00')
    work_end_time = db.Column(db.String(10), default='17:00')
    api_key = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500))
    is_school = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True)
    departments = db.relationship('Department', backref='organization', lazy=True)

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='hr_viewer')
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    organization = db.relationship('Organization', backref='users')
    school = db.relationship('School', backref='users')

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    short_name = db.Column(db.String(50))
    address = db.Column(db.String(500))
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(100))
    position = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance = db.relationship('Attendance', backref='staff', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time)
    check_out = db.Column(db.Time)
    status = db.Column(db.String(20), default='present')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def run_migrations():
    """Run all database migrations"""
    from sqlalchemy import text
    
    table_columns = {
        '"user"': [
            ("organization_id", "INTEGER"),
            ("school_id", "INTEGER"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ],
        'organization': [
            ("logo_url", "VARCHAR(500)"),
            ("is_school", "BOOLEAN DEFAULT TRUE"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ],
        'school': [
            ("short_name", "VARCHAR(50)"),
            ("address", "VARCHAR(500)"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ],
        'staff': [
            ("department", "VARCHAR(100)"),
            ("position", "VARCHAR(100)"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ],
        'attendance': [
            ("school_id", "INTEGER"),
            ("check_in", "TIME"),
            ("check_out", "TIME"),
            ("status", "VARCHAR(20) DEFAULT 'present'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ],
        'system_settings': [
            ("company_name", "VARCHAR(200) DEFAULT 'Attendance System'"),
            ("company_logo_url", "VARCHAR(500)"),
            ("late_threshold_minutes", "INTEGER DEFAULT 15"),
            ("work_start_time", "VARCHAR(10) DEFAULT '08:00'"),
            ("work_end_time", "VARCHAR(10) DEFAULT '17:00'"),
            ("api_key", "VARCHAR(100)"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
    }
    
    for table, columns in table_columns.items():
        for col_name, col_type in columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM {table} LIMIT 1'))
                db.session.rollback()
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                except:
                    db.session.rollback()
    
    # Create department table
    try:
        db.session.execute(text('SELECT id FROM department LIMIT 1'))
        db.session.rollback()
    except:
        db.session.rollback()
        try:
            db.session.execute(text('''CREATE TABLE IF NOT EXISTS department (
                id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL,
                organization_id INTEGER, is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
            db.session.commit()
        except:
            db.session.rollback()
    
    # Set defaults
    try:
        db.session.execute(text('UPDATE "user" SET is_active = TRUE WHERE is_active IS NULL'))
        db.session.execute(text('UPDATE organization SET is_active = TRUE WHERE is_active IS NULL'))
        db.session.execute(text('UPDATE school SET is_active = TRUE WHERE is_active IS NULL'))
        db.session.execute(text('UPDATE staff SET is_active = TRUE WHERE is_active IS NULL'))
        db.session.commit()
    except:
        db.session.rollback()
    
    # Update attendance school_id
    try:
        db.session.execute(text('''UPDATE attendance SET school_id = staff.school_id 
            FROM staff WHERE attendance.staff_id = staff.id AND attendance.school_id IS NULL'''))
        db.session.commit()
    except:
        db.session.rollback()

def get_system_settings():
    try:
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(company_name='Attendance System', late_threshold_minutes=15,
                work_start_time='08:00', work_end_time='17:00')
            db.session.add(settings)
            db.session.commit()
        return settings
    except:
        return None

@app.context_processor
def inject_settings():
    settings = get_system_settings()
    user_organization = None
    if current_user.is_authenticated:
        try:
            if current_user.organization_id:
                user_organization = Organization.query.get(current_user.organization_id)
        except:
            pass
    return dict(system_settings=settings, user_organization=user_organization)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('Account is disabled.', 'danger')
                return render_template('login.html')
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().date()
    
    if current_user.role == 'super_admin':
        total_staff = Staff.query.filter_by(is_active=True).count()
        total_schools = School.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today).count()
        late_today = Attendance.query.filter_by(date=today, status='late').count()
        absent_today = Attendance.query.filter_by(date=today, status='absent').count()
        organizations = Organization.query.filter_by(is_active=True).all()
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count() if school_ids else 0
        total_schools = len(org_schools)
        today_attendance = Attendance.query.filter(Attendance.date==today, Attendance.school_id.in_(school_ids)).count() if school_ids else 0
        late_today = Attendance.query.filter(Attendance.date==today, Attendance.status=='late', Attendance.school_id.in_(school_ids)).count() if school_ids else 0
        absent_today = Attendance.query.filter(Attendance.date==today, Attendance.status=='absent', Attendance.school_id.in_(school_ids)).count() if school_ids else 0
        organizations = [Organization.query.get(current_user.organization_id)]
        schools = org_schools
    else:
        total_staff = total_schools = today_attendance = late_today = absent_today = 0
        organizations = []
        schools = []
    
    school_stats = []
    for school in schools:
        staff_count = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        present = Attendance.query.filter_by(school_id=school.id, date=today, status='present').count()
        late = Attendance.query.filter_by(school_id=school.id, date=today, status='late').count()
        school_stats.append({'school': school, 'total_staff': staff_count, 'present': present + late, 'late': late})
    
    return render_template('dashboard.html', total_staff=total_staff, total_schools=total_schools,
        today_attendance=today_attendance, late_today=late_today, absent_today=absent_today,
        organizations=organizations, school_stats=school_stats)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def settings():
    settings = get_system_settings()
    organizations = Organization.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else ([Organization.query.get(current_user.organization_id)] if current_user.organization_id else [])
    
    if request.method == 'POST' and current_user.role == 'super_admin' and settings:
        settings.company_name = request.form.get('company_name', settings.company_name)
        settings.company_logo_url = request.form.get('company_logo_url', settings.company_logo_url)
        settings.late_threshold_minutes = int(request.form.get('late_threshold', 15))
        settings.work_start_time = request.form.get('work_start_time', '08:00')
        settings.work_end_time = request.form.get('work_end_time', '17:00')
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=settings, organizations=organizations)

@app.route('/organizations')
@login_required
@role_required('super_admin')
def organizations():
    return render_template('organizations.html', organizations=Organization.query.filter_by(is_active=True).all())

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        org = Organization(name=request.form.get('name'), logo_url=request.form.get('logo_url'),
            is_school=request.form.get('is_school') == 'on')
        db.session.add(org)
        db.session.commit()
        
        defaults = ['Academic', 'Non-Academic', 'Administration', 'Support Staff'] if org.is_school else ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration']
        for name in defaults:
            db.session.add(Department(name=name, organization_id=org.id))
        db.session.commit()
        flash('Organization added successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('add_organization.html')

@app.route('/organizations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url')
        org.is_school = request.form.get('is_school') == 'on'
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('edit_organization.html', organization=org)

@app.route('/organizations/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    org.is_active = False
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('organizations'))

@app.route('/organizations/<int:org_id>/departments')
@login_required
@role_required('super_admin', 'school_admin')
def manage_departments(org_id):
    if current_user.role == 'school_admin' and current_user.organization_id != org_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('departments.html', organization=Organization.query.get_or_404(org_id),
        departments=Department.query.filter_by(organization_id=org_id, is_active=True).all())

@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_department(org_id):
    if current_user.role == 'school_admin' and current_user.organization_id != org_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    name = request.form.get('name')
    if name:
        db.session.add(Department(name=name, organization_id=org_id))
        db.session.commit()
        flash('Department added successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/departments/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def delete_department(id):
    dept = Department.query.get_or_404(id)
    if current_user.role == 'school_admin' and current_user.organization_id != dept.organization_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    dept.is_active = False
    db.session.commit()
    flash('Department deleted successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=dept.organization_id))

@app.route('/api/organizations/<int:org_id>/departments')
@login_required
def get_organization_departments(org_id):
    return jsonify([{'id': d.id, 'name': d.name} for d in Department.query.filter_by(organization_id=org_id, is_active=True).all()])

@app.route('/schools')
@login_required
@role_required('super_admin', 'school_admin')
def schools():
    if current_user.role == 'super_admin':
        school_list = School.query.filter_by(is_active=True).all()
    else:
        school_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    return render_template('schools.html', schools=school_list)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_school():
    organizations = Organization.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else [Organization.query.get(current_user.organization_id)]
    if request.method == 'POST':
        org_id = current_user.organization_id if current_user.role == 'school_admin' else request.form.get('organization_id')
        db.session.add(School(name=request.form.get('name'), short_name=request.form.get('short_name'),
            address=request.form.get('address'), organization_id=org_id))
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    if current_user.role == 'school_admin' and school.organization_id != current_user.organization_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('schools'))
    organizations = Organization.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else [Organization.query.get(current_user.organization_id)]
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        school.address = request.form.get('address')
        if current_user.role == 'super_admin':
            school.organization_id = request.form.get('organization_id')
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    return render_template('edit_school.html', school=school, organizations=organizations)

@app.route('/schools/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    if current_user.role == 'school_admin' and school.organization_id != current_user.organization_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('schools'))
    school.is_active = False
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
@role_required('super_admin', 'school_admin', 'hr_viewer')
def staff():
    if current_user.role == 'super_admin':
        staff_list = Staff.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).all() if school_ids else []
    else:
        staff_list = []
    return render_template('staff.html', staff=staff_list)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_staff():
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
        departments = []
    else:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        organizations = [Organization.query.get(current_user.organization_id)]
        departments = Department.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
    if request.method == 'POST':
        db.session.add(Staff(staff_id=request.form.get('staff_id'), name=request.form.get('name'),
            department=request.form.get('department'), position=request.form.get('position'),
            school_id=request.form.get('school_id')))
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff'))
    return render_template('add_staff.html', schools=schools, organizations=organizations, departments=departments)

@app.route('/staff/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_staff(id):
    staff_member = Staff.query.get_or_404(id)
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        if staff_member.school_id not in [s.id for s in schools]:
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
    
    if request.method == 'POST':
        staff_member.staff_id = request.form.get('staff_id')
        staff_member.name = request.form.get('name')
        staff_member.department = request.form.get('department')
        staff_member.position = request.form.get('position')
        staff_member.school_id = request.form.get('school_id')
        db.session.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('staff'))
    return render_template('edit_staff.html', staff=staff_member, schools=schools)

@app.route('/staff/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def delete_staff(id):
    staff_member = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin':
        schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        if staff_member.school_id not in [s.id for s in schools]:
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
    staff_member.is_active = False
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def bulk_upload_staff():
    schools = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        file = request.files.get('file')
        if not file:
            flash('No file uploaded.', 'danger')
            return redirect(url_for('bulk_upload_staff'))
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            count = 0
            for row in reader:
                if not Staff.query.filter_by(staff_id=row.get('staff_id', '').strip()).first() and row.get('staff_id'):
                    db.session.add(Staff(staff_id=row.get('staff_id', '').strip(), name=row.get('name', '').strip(),
                        department=row.get('department', '').strip(), position=row.get('position', '').strip(), school_id=school_id))
                    count += 1
            db.session.commit()
            flash(f'{count} staff members uploaded successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('staff'))
    return render_template('bulk_upload.html', schools=schools)

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    return render_template('users.html', users=User.query.filter_by(is_active=True).all())

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        username = request.form.get('username')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html', organizations=organizations, schools=schools)
        db.session.add(User(username=username, password_hash=generate_password_hash(request.form.get('password')),
            role=request.form.get('role'), organization_id=request.form.get('organization_id') or None,
            school_id=request.form.get('school_id') or None))
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('add_user.html', organizations=organizations, schools=schools)

@app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.role = request.form.get('role')
        user.organization_id = request.form.get('organization_id') or None
        user.school_id = request.form.get('school_id') or None
        if request.form.get('password'):
            user.password_hash = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('edit_user.html', user=user, organizations=organizations, schools=schools)

@app.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('users'))
    user.is_active = False
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/reports/attendance')
@login_required
def attendance_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all() if current_user.organization_id else []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In', 'Check Out', 'Status'])
        for r in records:
            writer.writerow([r.date.isoformat(), r.staff.staff_id if r.staff else '', r.staff.name if r.staff else '',
                r.staff.school.name if r.staff and r.staff.school else '', str(r.check_in) if r.check_in else '',
                str(r.check_out) if r.check_out else '', r.status])
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=attendance.csv'})
    
    return render_template('attendance_report.html', records=records, schools=schools, start_date=start_date, end_date=end_date, selected_school=school_id)

@app.route('/reports/late')
@login_required
def late_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.status == 'late')
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all() if current_user.organization_id else []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In', 'Late By'])
        for r in records:
            late_by = ''
            if r.check_in:
                try:
                    diff = datetime.combine(r.date, r.check_in) - datetime.combine(r.date, datetime.strptime('08:00', '%H:%M').time())
                    late_by = f"{int(diff.total_seconds() // 60)} minutes"
                except: pass
            writer.writerow([r.date.isoformat(), r.staff.staff_id if r.staff else '', r.staff.name if r.staff else '',
                r.staff.school.name if r.staff and r.staff.school else '', str(r.check_in) if r.check_in else '', late_by])
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=late.csv'})
    
    return render_template('late_report.html', records=records, schools=schools, start_date=start_date, end_date=end_date, selected_school=school_id)

@app.route('/reports/absent')
@login_required
def absent_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.status == 'absent')
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all() if current_user.organization_id else []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department'])
        for r in records:
            writer.writerow([r.date.isoformat(), r.staff.staff_id if r.staff else '', r.staff.name if r.staff else '',
                r.staff.school.name if r.staff and r.staff.school else '', r.staff.department if r.staff else ''])
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=absent.csv'})
    
    return render_template('absent_report.html', records=records, schools=schools, start_date=start_date, end_date=end_date, selected_school=school_id)

@app.route('/reports/overtime')
@login_required
def overtime_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    work_end = datetime.strptime('17:00', '%H:%M').time()
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.check_out.isnot(None))
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = [r for r in query.order_by(Attendance.date.desc()).all() if r.check_out and r.check_out > work_end]
    schools = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all() if current_user.organization_id else []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check Out', 'Overtime'])
        for r in records:
            diff = datetime.combine(r.date, r.check_out) - datetime.combine(r.date, work_end)
            overtime = f"{int(diff.total_seconds()//3600)}h {int((diff.total_seconds()%3600)//60)}m"
            writer.writerow([r.date.isoformat(), r.staff.staff_id if r.staff else '', r.staff.name if r.staff else '',
                r.staff.school.name if r.staff and r.staff.school else '', str(r.check_out), overtime])
        output.seek(0)
        return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=overtime.csv'})
    
    return render_template('overtime_report.html', records=records, schools=schools, start_date=start_date, end_date=end_date, selected_school=school_id, work_end_time='17:00')

@app.route('/reports/analytics')
@login_required
def analytics():
    if current_user.role not in ['super_admin', 'school_admin', 'ceo_viewer']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    period = request.args.get('period', '30')
    org_id = request.args.get('organization')
    school_id = request.args.get('school')
    department = request.args.get('department')
    
    days = int(period) if period.isdigit() else 30
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    attendance_query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    staff_query = Staff.query.filter_by(is_active=True)
    
    if current_user.role == 'school_admin' and current_user.organization_id:
        org_id = current_user.organization_id
    
    if org_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=int(org_id), is_active=True).all()]
        if school_ids:
            attendance_query = attendance_query.filter(Attendance.school_id.in_(school_ids))
            staff_query = staff_query.filter(Staff.school_id.in_(school_ids))
    
    if school_id:
        attendance_query = attendance_query.filter(Attendance.school_id == int(school_id))
        staff_query = staff_query.filter(Staff.school_id == int(school_id))
    
    if department:
        attendance_query = attendance_query.join(Staff).filter(Staff.department == department)
        staff_query = staff_query.filter(Staff.department == department)
    
    attendance_records = attendance_query.all()
    total_staff = staff_query.count()
    total_records = len(attendance_records)
    on_time_count = sum(1 for a in attendance_records if a.status == 'present')
    late_count = sum(1 for a in attendance_records if a.status == 'late')
    absent_count = sum(1 for a in attendance_records if a.status == 'absent')
    
    expected = total_staff * days
    attendance_rate = round((total_records / expected * 100), 1) if expected > 0 else 0
    punctuality_rate = round((on_time_count / total_records * 100), 1) if total_records > 0 else 0
    
    late_records = [a for a in attendance_records if a.status == 'late' and a.check_in]
    total_late_min = sum((datetime.combine(a.date, a.check_in) - datetime.combine(a.date, datetime.strptime('08:00', '%H:%M').time())).total_seconds() / 60 for a in late_records if a.check_in)
    avg_late_time = round(total_late_min / len(late_records)) if late_records else 0
    
    total_overtime = sum(max(0, (datetime.combine(a.date, a.check_out) - datetime.combine(a.date, datetime.strptime('17:00', '%H:%M').time())).total_seconds() / 60) for a in attendance_records if a.check_out)
    overtime_hours = round(total_overtime / 60, 1)
    
    trend_data = defaultdict(lambda: {'present': 0, 'late': 0, 'absent': 0, 'total': 0})
    for a in attendance_records:
        d = a.date.strftime('%Y-%m-%d')
        trend_data[d]['total'] += 1
        trend_data[d][a.status] += 1
    
    sorted_dates = sorted(trend_data.keys())
    trend_labels = sorted_dates
    attendance_trend = [trend_data[d]['present'] + trend_data[d]['late'] for d in sorted_dates]
    punctuality_trend = [round((trend_data[d]['present'] / (trend_data[d]['total'] or 1)) * 100, 1) for d in sorted_dates]
    
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    late_by_day = [0] * 7
    for a in attendance_records:
        if a.status == 'late':
            late_by_day[a.date.weekday()] += 1
    
    dept_stats = defaultdict(lambda: {'total': 0, 'present': 0})
    for a in attendance_records:
        s = Staff.query.get(a.staff_id)
        if s and s.department:
            dept_stats[s.department]['total'] += 1
            if a.status in ['present', 'late']:
                dept_stats[s.department]['present'] += 1
    
    department_labels = list(dept_stats.keys()) or ['No Data']
    department_data = [round((v['present'] / v['total'] * 100), 1) if v['total'] > 0 else 0 for v in dept_stats.values()] or [0]
    
    branch_stats = defaultdict(lambda: {'total': 0, 'present': 0})
    for a in attendance_records:
        sch = School.query.get(a.school_id)
        if sch:
            branch_stats[sch.name]['total'] += 1
            if a.status in ['present', 'late']:
                branch_stats[sch.name]['present'] += 1
    
    branch_labels = list(branch_stats.keys()) or ['No Data']
    branch_data = [round((v['present'] / v['total'] * 100), 1) if v['total'] > 0 else 0 for v in branch_stats.values()] or [0]
    
    arrival_labels = [f'{h}:00' for h in range(6, 12)]
    arrival_data = [0] * 6
    for a in attendance_records:
        if a.check_in and 6 <= a.check_in.hour < 12:
            arrival_data[a.check_in.hour - 6] += 1
    
    this_week_start = end_date - timedelta(days=end_date.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    weekly_labels = ['This Week', 'Last Week']
    weekly_data = [len([a for a in attendance_records if a.date >= this_week_start]), len([a for a in attendance_records if last_week_start <= a.date < this_week_start])]
    
    staff_att = defaultdict(lambda: {'present': 0, 'total': 0, 'name': '', 'school': ''})
    for a in attendance_records:
        s = Staff.query.get(a.staff_id)
        if s:
            staff_att[a.staff_id]['total'] += 1
            if a.status == 'present':
                staff_att[a.staff_id]['present'] += 1
            staff_att[a.staff_id]['name'] = s.name
            sch = School.query.get(s.school_id)
            staff_att[a.staff_id]['school'] = sch.name if sch else 'N/A'
    
    top_performers = sorted([{'name': d['name'], 'school': d['school'], 'rate': round((d['present']/d['total']*100),1) if d['total']>0 else 0, 'days': d['total']} for d in staff_att.values() if d['total']>0 and (d['present']/d['total']*100)>=95], key=lambda x: x['rate'], reverse=True)[:10]
    needs_attention = sorted([{'name': d['name'], 'school': d['school'], 'rate': round((d['present']/d['total']*100),1) if d['total']>0 else 0, 'days': d['total']} for d in staff_att.values() if d['total']>0 and (d['present']/d['total']*100)<70], key=lambda x: x['rate'])[:10]
    early_arrivals = sorted([{'name': staff_att[sid]['name'], 'school': staff_att[sid]['school'], 'early_days': sum(1 for a in attendance_records if a.staff_id==sid and a.check_in and a.check_in.hour<8), 'avg_time': '07:45'} for sid in staff_att if sum(1 for a in attendance_records if a.staff_id==sid and a.check_in and a.check_in.hour<8)>0], key=lambda x: x['early_days'], reverse=True)[:10]
    perfect_attendance = [p for p in top_performers if p['rate']==100][:10]
    
    organizations = Organization.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else []
    schools_list = School.query.filter_by(is_active=True).all() if current_user.role == 'super_admin' else School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all() if current_user.organization_id else []
    departments_list = [d[0] for d in db.session.query(Staff.department).distinct().filter(Staff.department.isnot(None)).all()]
    
    return render_template('analytics.html', attendance_rate=attendance_rate, punctuality_rate=punctuality_rate, total_staff=total_staff, total_records=total_records, on_time_count=on_time_count, late_count=late_count, avg_late_time=avg_late_time, overtime_hours=overtime_hours, trend_labels=trend_labels, attendance_trend=attendance_trend, punctuality_trend=punctuality_trend, day_names=day_names, late_by_day=late_by_day, department_labels=department_labels, department_data=department_data, branch_labels=branch_labels, branch_data=branch_data, arrival_labels=arrival_labels, arrival_data=arrival_data, weekly_labels=weekly_labels, weekly_data=weekly_data, present_count=on_time_count+late_count, absent_count=absent_count, top_performers=top_performers, needs_attention=needs_attention, early_arrivals=early_arrivals, perfect_attendance=perfect_attendance, most_improved=[], on_time_streaks=[], organizations=organizations, schools=schools_list, departments=departments_list, selected_period=period, selected_org=org_id, selected_school=school_id, selected_department=department)

@app.route('/reports/analytics/pdf')
@login_required
def download_analytics_pdf():
    if current_user.role not in ['super_admin', 'school_admin', 'ceo_viewer']:
        return redirect(url_for('dashboard'))
    try:
        from xhtml2pdf import pisa
        today = datetime.now()
        days = 30
        end_date = today.date()
        start_date = end_date - timedelta(days=days)
        
        if current_user.role == 'school_admin' and current_user.organization_id:
            school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
            records = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.school_id.in_(school_ids)).all() if school_ids else []
            total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count() if school_ids else 0
        else:
            records = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date).all()
            total_staff = Staff.query.filter_by(is_active=True).count()
        
        total = len(records)
        on_time = sum(1 for a in records if a.status == 'present')
        late = sum(1 for a in records if a.status == 'late')
        absent = sum(1 for a in records if a.status == 'absent')
        att_rate = round((total / (total_staff * days) * 100), 1) if total_staff * days > 0 else 0
        punct_rate = round((on_time / total * 100), 1) if total > 0 else 0
        
        html = f'''<!DOCTYPE html><html><head><style>body{{font-family:Arial;margin:40px}}h1{{color:#333;border-bottom:2px solid #667eea}}.metric{{display:inline-block;width:23%;text-align:center;padding:15px;background:#f5f5f5}}table{{width:100%;border-collapse:collapse;margin-top:20px}}th,td{{border:1px solid #ddd;padding:10px}}th{{background:#667eea;color:white}}</style></head><body><h1>Analytics Report</h1><p>{start_date} - {end_date}</p><div class="metric"><h3>{att_rate}%</h3><p>Attendance</p></div><div class="metric"><h3>{punct_rate}%</h3><p>Punctuality</p></div><div class="metric"><h3>{total_staff}</h3><p>Staff</p></div><div class="metric"><h3>{total}</h3><p>Records</p></div><table><tr><th>Status</th><th>Count</th><th>%</th></tr><tr><td>On Time</td><td>{on_time}</td><td>{round((on_time/total*100),1) if total else 0}%</td></tr><tr><td>Late</td><td>{late}</td><td>{round((late/total*100),1) if total else 0}%</td></tr><tr><td>Absent</td><td>{absent}</td><td>{round((absent/total*100),1) if total else 0}%</td></tr></table></body></html>'''
        
        output = io.BytesIO()
        pisa.CreatePDF(io.BytesIO(html.encode('utf-8')), dest=output)
        output.seek(0)
        return Response(output.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename=analytics_{today.strftime("%Y%m%d")}.pdf'})
    except:
        flash('PDF generation failed.', 'danger')
        return redirect(url_for('analytics'))

@app.route('/api/sync', methods=['POST'])
def api_sync():
    settings = get_system_settings()
    api_key = request.headers.get('X-API-Key')
    if not settings or not api_key or api_key != settings.api_key:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    
    try:
        synced, errors = 0, []
        for rec in data.get('records', []):
            staff = Staff.query.filter_by(staff_id=rec.get('staff_id')).first()
            if not staff:
                errors.append(f"Staff {rec.get('staff_id')} not found")
                continue
            
            date = datetime.strptime(rec.get('date'), '%Y-%m-%d').date()
            check_in = datetime.strptime(rec.get('check_in'), '%H:%M:%S').time() if rec.get('check_in') else None
            check_out = datetime.strptime(rec.get('check_out'), '%H:%M:%S').time() if rec.get('check_out') else None
            status = 'late' if check_in and datetime.combine(date, check_in) > datetime.combine(date, datetime.strptime('08:00', '%H:%M').time()) + timedelta(minutes=15) else ('absent' if not check_in else 'present')
            
            existing = Attendance.query.filter_by(staff_id=staff.id, date=date).first()
            if existing:
                existing.check_in = check_in or existing.check_in
                existing.check_out = check_out or existing.check_out
                existing.status = status
            else:
                db.session.add(Attendance(staff_id=staff.id, school_id=staff.school_id, date=date, check_in=check_in, check_out=check_out, status=status))
            synced += 1
        
        db.session.commit()
        return jsonify({'success': True, 'synced': synced, 'errors': errors})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password_hash=generate_password_hash('admin123'), role='super_admin', is_active=True))
        if not SystemSettings.query.first():
            db.session.add(SystemSettings(company_name='Attendance Management System', late_threshold_minutes=15, work_start_time='08:00', work_end_time='17:00'))
        db.session.commit()
        return '<h2>Database Initialized!</h2><p>Login: admin / admin123</p><a href="/login">Go to Login</a>'
    except Exception as e:
        db.session.rollback()
        return f'Error: {str(e)}'

@app.route('/migrate-departments')
def migrate_departments():
    try:
        run_migrations()
        
        # Ensure admin and settings exist
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password_hash=generate_password_hash('admin123'), role='super_admin', is_active=True))
        if not SystemSettings.query.first():
            db.session.add(SystemSettings(company_name='Attendance Management System', late_threshold_minutes=15, work_start_time='08:00', work_end_time='17:00'))
        
        # Add default departments
        dept_count = 0
        for org in Organization.query.all():
            if Department.query.filter_by(organization_id=org.id).count() == 0:
                for name in (['Academic', 'Non-Academic', 'Administration', 'Support Staff'] if org.is_school else ['Operations', 'Finance', 'HR', 'IT', 'Marketing', 'Administration']):
                    db.session.add(Department(name=name, organization_id=org.id))
                    dept_count += 1
        
        db.session.commit()
        return f'<h2>Migration Complete!</h2><p>Added {dept_count} departments</p><a href="/login">Go to Login</a>'
    except Exception as e:
        db.session.rollback()
        return f'Migration error: {str(e)}'

# Run migrations on startup
with app.app_context():
    try:
        db.create_all()
        run_migrations()
        
        # Ensure admin exists
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password_hash=generate_password_hash('admin123'), role='super_admin', is_active=True))
        
        # Ensure settings exist
        if not SystemSettings.query.first():
            db.session.add(SystemSettings(company_name='Attendance Management System', late_threshold_minutes=15, work_start_time='08:00', work_end_time='17:00'))
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Startup migration error: {e}")

if __name__ == '__main__':
    app.run(debug=True)
