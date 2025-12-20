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

def get_system_settings():
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings(company_name='Attendance System')
        db.session.add(settings)
        db.session.commit()
    return settings

@app.context_processor
def inject_settings():
    settings = get_system_settings()
    user_organization = None
    if current_user.is_authenticated and current_user.organization_id:
        user_organization = Organization.query.get(current_user.organization_id)
    return dict(system_settings=settings, user_organization=user_organization)

# Authentication Routes
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

# Dashboard
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
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count()
        total_schools = len(org_schools)
        today_attendance = Attendance.query.filter(Attendance.date==today, Attendance.school_id.in_(school_ids)).count()
        late_today = Attendance.query.filter(Attendance.date==today, Attendance.status=='late', Attendance.school_id.in_(school_ids)).count()
        absent_today = Attendance.query.filter(Attendance.date==today, Attendance.status=='absent', Attendance.school_id.in_(school_ids)).count()
        organizations = [Organization.query.get(current_user.organization_id)]
        schools = org_schools
    else:
        total_staff = 0
        total_schools = 0
        today_attendance = 0
        late_today = 0
        absent_today = 0
        organizations = []
        schools = []
    
    school_stats = []
    for school in schools:
        staff_count = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        present = Attendance.query.filter_by(school_id=school.id, date=today, status='present').count()
        late = Attendance.query.filter_by(school_id=school.id, date=today, status='late').count()
        school_stats.append({
            'school': school,
            'total_staff': staff_count,
            'present': present + late,
            'late': late
        })
    
    return render_template('dashboard.html',
        total_staff=total_staff,
        total_schools=total_schools,
        today_attendance=today_attendance,
        late_today=late_today,
        absent_today=absent_today,
        organizations=organizations,
        school_stats=school_stats
    )

# Settings
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def settings():
    settings = get_system_settings()
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.organization_id:
        organizations = [Organization.query.get(current_user.organization_id)]
    else:
        organizations = []
    
    if request.method == 'POST':
        if current_user.role == 'super_admin':
            settings.company_name = request.form.get('company_name', settings.company_name)
            settings.company_logo_url = request.form.get('company_logo_url', settings.company_logo_url)
            settings.late_threshold_minutes = int(request.form.get('late_threshold', 15))
            settings.work_start_time = request.form.get('work_start_time', '08:00')
            settings.work_end_time = request.form.get('work_end_time', '17:00')
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=settings, organizations=organizations)

# Organization Management
@app.route('/organizations')
@login_required
@role_required('super_admin')
def organizations():
    orgs = Organization.query.filter_by(is_active=True).all()
    return render_template('organizations.html', organizations=orgs)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        org = Organization(
            name=request.form.get('name'),
            logo_url=request.form.get('logo_url'),
            is_school=request.form.get('is_school') == 'on'
        )
        db.session.add(org)
        db.session.commit()
        
        if org.is_school:
            default_depts = ['Academic', 'Non-Academic', 'Administration', 'Support Staff']
        else:
            default_depts = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration']
        
        for dept_name in default_depts:
            dept = Department(name=dept_name, organization_id=org.id)
            db.session.add(dept)
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

# Department Management
@app.route('/organizations/<int:org_id>/departments')
@login_required
@role_required('super_admin', 'school_admin')
def manage_departments(org_id):
    if current_user.role == 'school_admin' and current_user.organization_id != org_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    org = Organization.query.get_or_404(org_id)
    departments = Department.query.filter_by(organization_id=org_id, is_active=True).all()
    return render_template('departments.html', organization=org, departments=departments)

@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_department(org_id):
    if current_user.role == 'school_admin' and current_user.organization_id != org_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    name = request.form.get('name')
    if name:
        dept = Department(name=name, organization_id=org_id)
        db.session.add(dept)
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
    departments = Department.query.filter_by(organization_id=org_id, is_active=True).all()
    return jsonify([{'id': d.id, 'name': d.name} for d in departments])

# School/Branch Management
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
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    else:
        organizations = [Organization.query.get(current_user.organization_id)]
    
    if request.method == 'POST':
        org_id = request.form.get('organization_id')
        if current_user.role == 'school_admin':
            org_id = current_user.organization_id
        
        school = School(
            name=request.form.get('name'),
            short_name=request.form.get('short_name'),
            address=request.form.get('address'),
            organization_id=org_id
        )
        db.session.add(school)
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
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    else:
        organizations = [Organization.query.get(current_user.organization_id)]
    
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

# Staff Management
@app.route('/staff')
@login_required
@role_required('super_admin', 'school_admin', 'hr_viewer')
def staff():
    if current_user.role == 'super_admin':
        staff_list = Staff.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).all()
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
    else:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        organizations = [Organization.query.get(current_user.organization_id)]
    
    departments = []
    if current_user.role == 'school_admin' and current_user.organization_id:
        departments = Department.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
    if request.method == 'POST':
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            name=request.form.get('name'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            school_id=request.form.get('school_id')
        )
        db.session.add(staff)
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
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
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
                existing = Staff.query.filter_by(staff_id=row.get('staff_id', '').strip()).first()
                if not existing and row.get('staff_id'):
                    staff = Staff(
                        staff_id=row.get('staff_id', '').strip(),
                        name=row.get('name', '').strip(),
                        department=row.get('department', '').strip(),
                        position=row.get('position', '').strip(),
                        school_id=school_id
                    )
                    db.session.add(staff)
                    count += 1
            
            db.session.commit()
            flash(f'{count} staff members uploaded successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing file: {str(e)}', 'danger')
        
        return redirect(url_for('staff'))
    
    return render_template('bulk_upload.html', schools=schools)

# User Management
@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    user_list = User.query.filter_by(is_active=True).all()
    return render_template('users.html', users=user_list)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        org_id = request.form.get('organization_id') or None
        school_id = request.form.get('school_id') or None
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html', organizations=organizations, schools=schools)
        
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            organization_id=org_id,
            school_id=school_id
        )
        db.session.add(user)
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
        
        new_password = request.form.get('password')
        if new_password:
            user.password_hash = generate_password_hash(new_password)
        
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

# Attendance Reports
@app.route('/reports/attendance')
@login_required
def attendance_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids))
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    else:
        schools = []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In', 'Check Out', 'Status'])
        
        for record in records:
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id if record.staff else '',
                record.staff.name if record.staff else '',
                record.staff.school.name if record.staff and record.staff.school else '',
                str(record.check_in) if record.check_in else '',
                str(record.check_out) if record.check_out else '',
                record.status
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=attendance_report.csv'}
        )
    
    return render_template('attendance_report.html', 
        records=records, 
        schools=schools,
        start_date=start_date,
        end_date=end_date,
        selected_school=school_id
    )

@app.route('/reports/late')
@login_required
def late_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.status == 'late'
    )
    
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids))
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    else:
        schools = []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In', 'Late By'])
        
        settings = get_system_settings()
        work_start = datetime.strptime(settings.work_start_time, '%H:%M').time()
        
        for record in records:
            late_by = ''
            if record.check_in:
                check_in_dt = datetime.combine(record.date, record.check_in)
                work_start_dt = datetime.combine(record.date, work_start)
                diff = check_in_dt - work_start_dt
                late_by = f"{int(diff.total_seconds() // 60)} minutes"
            
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id if record.staff else '',
                record.staff.name if record.staff else '',
                record.staff.school.name if record.staff and record.staff.school else '',
                str(record.check_in) if record.check_in else '',
                late_by
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=late_report.csv'}
        )
    
    return render_template('late_report.html',
        records=records,
        schools=schools,
        start_date=start_date,
        end_date=end_date,
        selected_school=school_id
    )

@app.route('/reports/absent')
@login_required
def absent_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.status == 'absent'
    )
    
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids))
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    else:
        schools = []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department'])
        
        for record in records:
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id if record.staff else '',
                record.staff.name if record.staff else '',
                record.staff.school.name if record.staff and record.staff.school else '',
                record.staff.department if record.staff else ''
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=absent_report.csv'}
        )
    
    return render_template('absent_report.html',
        records=records,
        schools=schools,
        start_date=start_date,
        end_date=end_date,
        selected_school=school_id
    )

@app.route('/reports/overtime')
@login_required
def overtime_report():
    start_date = request.args.get('start_date', datetime.now().date().isoformat())
    end_date = request.args.get('end_date', datetime.now().date().isoformat())
    school_id = request.args.get('school_id')
    
    settings = get_system_settings()
    work_end = datetime.strptime(settings.work_end_time, '%H:%M').time()
    
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.check_out.isnot(None)
    )
    
    if current_user.role == 'school_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        query = query.filter(Attendance.school_id.in_(school_ids))
    elif school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    all_records = query.order_by(Attendance.date.desc()).all()
    
    records = []
    for record in all_records:
        if record.check_out and record.check_out > work_end:
            records.append(record)
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    else:
        schools = []
    
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check Out', 'Overtime'])
        
        for record in records:
            overtime = ''
            if record.check_out:
                check_out_dt = datetime.combine(record.date, record.check_out)
                work_end_dt = datetime.combine(record.date, work_end)
                diff = check_out_dt - work_end_dt
                hours = int(diff.total_seconds() // 3600)
                minutes = int((diff.total_seconds() % 3600) // 60)
                overtime = f"{hours}h {minutes}m"
            
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id if record.staff else '',
                record.staff.name if record.staff else '',
                record.staff.school.name if record.staff and record.staff.school else '',
                str(record.check_out) if record.check_out else '',
                overtime
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=overtime_report.csv'}
        )
    
    return render_template('overtime_report.html',
        records=records,
        schools=schools,
        start_date=start_date,
        end_date=end_date,
        selected_school=school_id,
        work_end_time=settings.work_end_time
    )

# Analytics
@app.route('/reports/analytics')
@login_required
def analytics():
    if current_user.role not in ['super_admin', 'school_admin', 'ceo_viewer']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get filter parameters
    period = request.args.get('period', '30')
    org_id = request.args.get('organization')
    school_id = request.args.get('school')
    department = request.args.get('department')
    
    # Calculate date range
    try:
        days = int(period)
    except:
        days = 30
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    # Base query for attendance
    attendance_query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    
    # Base query for staff
    staff_query = Staff.query.filter_by(is_active=True)
    
    # Apply organization filter
    if current_user.role == 'school_admin' and current_user.organization_id:
        org_id = current_user.organization_id
        schools = School.query.filter_by(organization_id=org_id, is_active=True).all()
        school_ids = [s.id for s in schools]
        attendance_query = attendance_query.filter(Attendance.school_id.in_(school_ids))
        staff_query = staff_query.filter(Staff.school_id.in_(school_ids))
    elif org_id:
        org_id = int(org_id)
        schools = School.query.filter_by(organization_id=org_id, is_active=True).all()
        school_ids = [s.id for s in schools]
        attendance_query = attendance_query.filter(Attendance.school_id.in_(school_ids))
        staff_query = staff_query.filter(Staff.school_id.in_(school_ids))
    
    # Apply school filter
    if school_id:
        school_id = int(school_id)
        attendance_query = attendance_query.filter(Attendance.school_id == school_id)
        staff_query = staff_query.filter(Staff.school_id == school_id)
    
    # Apply department filter
    if department:
        attendance_query = attendance_query.join(Staff).filter(Staff.department == department)
        staff_query = staff_query.filter(Staff.department == department)
    
    # Get all attendance records
    attendance_records = attendance_query.all()
    total_staff = staff_query.count()
    
    # Calculate metrics
    total_records = len(attendance_records)
    on_time_count = sum(1 for a in attendance_records if a.status == 'present')
    late_count = sum(1 for a in attendance_records if a.status == 'late')
    absent_count = sum(1 for a in attendance_records if a.status == 'absent')
    
    # Attendance rate
    expected_records = total_staff * days
    attendance_rate = round((total_records / expected_records * 100), 1) if expected_records > 0 else 0
    
    # Punctuality rate
    punctuality_rate = round((on_time_count / total_records * 100), 1) if total_records > 0 else 0
    
    # Calculate late times
    late_records = [a for a in attendance_records if a.status == 'late' and a.check_in]
    total_late_minutes = 0
    for a in late_records:
        if a.check_in:
            try:
                check_in_time = datetime.strptime(str(a.check_in), '%H:%M:%S').time() if isinstance(a.check_in, str) else a.check_in
                expected_time = datetime.strptime('08:00:00', '%H:%M:%S').time()
                late_minutes = (datetime.combine(a.date, check_in_time) - datetime.combine(a.date, expected_time)).total_seconds() / 60
                if late_minutes > 0:
                    total_late_minutes += late_minutes
            except:
                pass
    
    avg_late_time = round(total_late_minutes / len(late_records)) if late_records else 0
    
    # Calculate overtime
    total_overtime = 0
    for a in attendance_records:
        if a.check_out:
            try:
                check_out_time = datetime.strptime(str(a.check_out), '%H:%M:%S').time() if isinstance(a.check_out, str) else a.check_out
                expected_end = datetime.strptime('17:00:00', '%H:%M:%S').time()
                overtime_minutes = (datetime.combine(a.date, check_out_time) - datetime.combine(a.date, expected_end)).total_seconds() / 60
                if overtime_minutes > 0:
                    total_overtime += overtime_minutes
            except:
                pass
    
    overtime_hours = round(total_overtime / 60, 1)
    
    # Trend data (daily)
    trend_data = defaultdict(lambda: {'present': 0, 'late': 0, 'absent': 0, 'total': 0})
    for a in attendance_records:
        date_str = a.date.strftime('%Y-%m-%d')
        trend_data[date_str]['total'] += 1
        if a.status == 'present':
            trend_data[date_str]['present'] += 1
        elif a.status == 'late':
            trend_data[date_str]['late'] += 1
        elif a.status == 'absent':
            trend_data[date_str]['absent'] += 1
    
    # Sort by date
    sorted_dates = sorted(trend_data.keys())
    trend_labels = sorted_dates
    attendance_trend = [trend_data[d]['present'] + trend_data[d]['late'] for d in sorted_dates]
    punctuality_trend = [round((trend_data[d]['present'] / (trend_data[d]['total'] or 1)) * 100, 1) for d in sorted_dates]
    
    # Late by day of week
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    late_by_day = [0] * 7
    for a in attendance_records:
        if a.status == 'late':
            late_by_day[a.date.weekday()] += 1
    
    # Department performance
    dept_stats = defaultdict(lambda: {'total': 0, 'present': 0})
    for a in attendance_records:
        staff_member = Staff.query.get(a.staff_id)
        if staff_member and staff_member.department:
            dept_stats[staff_member.department]['total'] += 1
            if a.status in ['present', 'late']:
                dept_stats[staff_member.department]['present'] += 1
    
    department_labels = list(dept_stats.keys()) or ['No Data']
    department_data = [round((v['present'] / v['total'] * 100), 1) if v['total'] > 0 else 0 for v in dept_stats.values()] or [0]
    
    # Branch comparison
    branch_stats = defaultdict(lambda: {'total': 0, 'present': 0})
    for a in attendance_records:
        school = School.query.get(a.school_id)
        if school:
            branch_stats[school.name]['total'] += 1
            if a.status in ['present', 'late']:
                branch_stats[school.name]['present'] += 1
    
    branch_labels = list(branch_stats.keys()) or ['No Data']
    branch_data = [round((v['present'] / v['total'] * 100), 1) if v['total'] > 0 else 0 for v in branch_stats.values()] or [0]
    
    # Arrival distribution (hourly)
    arrival_labels = [f'{h}:00' for h in range(6, 12)]
    arrival_data = [0] * 6
    for a in attendance_records:
        if a.check_in:
            try:
                hour = int(str(a.check_in).split(':')[0])
                if 6 <= hour < 12:
                    arrival_data[hour - 6] += 1
            except:
                pass
    
    # Weekly comparison
    weekly_labels = ['This Week', 'Last Week']
    this_week_start = end_date - timedelta(days=end_date.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    
    this_week_records = [a for a in attendance_records if a.date >= this_week_start]
    last_week_records = [a for a in attendance_records if last_week_start <= a.date < this_week_start]
    
    weekly_data = [len(this_week_records), len(last_week_records)]
    
    # Top performers
    staff_attendance = defaultdict(lambda: {'present': 0, 'total': 0, 'name': '', 'school': ''})
    for a in attendance_records:
        staff_member = Staff.query.get(a.staff_id)
        if staff_member:
            key = a.staff_id
            staff_attendance[key]['total'] += 1
            if a.status == 'present':
                staff_attendance[key]['present'] += 1
            staff_attendance[key]['name'] = staff_member.name
            school = School.query.get(staff_member.school_id)
            staff_attendance[key]['school'] = school.name if school else 'N/A'
    
    top_performers = []
    needs_attention = []
    for staff_id, data in staff_attendance.items():
        rate = round((data['present'] / data['total'] * 100), 1) if data['total'] > 0 else 0
        entry = {
            'name': data['name'],
            'school': data['school'],
            'rate': rate,
            'days': data['total']
        }
        if rate >= 95:
            top_performers.append(entry)
        if rate < 70:
            needs_attention.append(entry)
    
    top_performers = sorted(top_performers, key=lambda x: x['rate'], reverse=True)[:10]
    needs_attention = sorted(needs_attention, key=lambda x: x['rate'])[:10]
    
    # Early arrivals
    early_arrivals = []
    for staff_id, data in staff_attendance.items():
        early_count = 0
        for a in attendance_records:
            if a.staff_id == staff_id and a.check_in:
                try:
                    hour = int(str(a.check_in).split(':')[0])
                    if hour < 8:
                        early_count += 1
                except:
                    pass
        if early_count > 0:
            early_arrivals.append({
                'name': data['name'],
                'school': data['school'],
                'early_days': early_count,
                'avg_time': '07:45'
            })
    early_arrivals = sorted(early_arrivals, key=lambda x: x['early_days'], reverse=True)[:10]
    
    # Perfect attendance
    perfect_attendance = [p for p in top_performers if p['rate'] == 100][:10]
    
    # Most improved (placeholder)
    most_improved = []
    
    # On-time streaks (placeholder)
    on_time_streaks = []
    
    # Get organizations for filter
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    else:
        organizations = []
    
    # Get schools for filter
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    else:
        schools = []
    
    # Get departments for filter
    departments = db.session.query(Staff.department).distinct().filter(Staff.department.isnot(None)).all()
    departments = [d[0] for d in departments]
    
    return render_template('analytics.html',
        # Metrics
        attendance_rate=attendance_rate,
        punctuality_rate=punctuality_rate,
        total_staff=total_staff,
        total_records=total_records,
        on_time_count=on_time_count,
        late_count=late_count,
        avg_late_time=avg_late_time,
        overtime_hours=overtime_hours,
        
        # Trend charts
        trend_labels=trend_labels,
        attendance_trend=attendance_trend,
        punctuality_trend=punctuality_trend,
        
        # Late by day
        day_names=day_names,
        late_by_day=late_by_day,
        
        # Department
        department_labels=department_labels,
        department_data=department_data,
        
        # Branch
        branch_labels=branch_labels,
        branch_data=branch_data,
        
        # Arrival
        arrival_labels=arrival_labels,
        arrival_data=arrival_data,
        
        # Weekly
        weekly_labels=weekly_labels,
        weekly_data=weekly_data,
        
        # Present/Absent pie
        present_count=on_time_count + late_count,
        absent_count=absent_count,
        
        # Rankings
        top_performers=top_performers,
        needs_attention=needs_attention,
        early_arrivals=early_arrivals,
        perfect_attendance=perfect_attendance,
        most_improved=most_improved,
        on_time_streaks=on_time_streaks,
        
        # Filters
        organizations=organizations,
        schools=schools,
        departments=departments,
        selected_period=period,
        selected_org=org_id,
        selected_school=school_id,
        selected_department=department
    )

@app.route('/reports/analytics/pdf')
@login_required
def download_analytics_pdf():
    if current_user.role not in ['super_admin', 'school_admin', 'ceo_viewer']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        from xhtml2pdf import pisa
        
        # Get current date info
        today = datetime.now()
        period = request.args.get('period', '30')
        
        try:
            days = int(period)
        except:
            days = 30
        
        end_date = today.date()
        start_date = end_date - timedelta(days=days)
        
        # Get attendance data
        if current_user.role == 'school_admin' and current_user.organization_id:
            school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
            attendance_records = Attendance.query.filter(
                Attendance.date >= start_date,
                Attendance.date <= end_date,
                Attendance.school_id.in_(school_ids)
            ).all()
            total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count()
        else:
            attendance_records = Attendance.query.filter(
                Attendance.date >= start_date,
                Attendance.date <= end_date
            ).all()
            total_staff = Staff.query.filter_by(is_active=True).count()
        
        total_records = len(attendance_records)
        on_time = sum(1 for a in attendance_records if a.status == 'present')
        late = sum(1 for a in attendance_records if a.status == 'late')
        absent = sum(1 for a in attendance_records if a.status == 'absent')
        
        expected = total_staff * days
        attendance_rate = round((total_records / expected * 100), 1) if expected > 0 else 0
        punctuality_rate = round((on_time / total_records * 100), 1) if total_records > 0 else 0
        
        settings = get_system_settings()
        
        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                h1 {{ color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
                h2 {{ color: #667eea; margin-top: 30px; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .metric {{ display: inline-block; width: 23%; text-align: center; margin: 10px 0; padding: 15px; background: #f5f5f5; border-radius: 8px; }}
                .metric h3 {{ margin: 0; color: #667eea; font-size: 24px; }}
                .metric p {{ margin: 5px 0 0 0; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
                th {{ background: #667eea; color: white; }}
                tr:nth-child(even) {{ background: #f9f9f9; }}
                .footer {{ margin-top: 40px; text-align: center; color: #999; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{settings.company_name}</h1>
                <p>Analytics Report</p>
                <p>{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}</p>
            </div>
            
            <h2>Summary Metrics</h2>
            <div>
                <div class="metric">
                    <h3>{attendance_rate}%</h3>
                    <p>Attendance Rate</p>
                </div>
                <div class="metric">
                    <h3>{punctuality_rate}%</h3>
                    <p>Punctuality Rate</p>
                </div>
                <div class="metric">
                    <h3>{total_staff}</h3>
                    <p>Active Staff</p>
                </div>
                <div class="metric">
                    <h3>{total_records}</h3>
                    <p>Total Records</p>
                </div>
            </div>
            
            <h2>Attendance Breakdown</h2>
            <table>
                <tr>
                    <th>Status</th>
                    <th>Count</th>
                    <th>Percentage</th>
                </tr>
                <tr>
                    <td>On Time</td>
                    <td>{on_time}</td>
                    <td>{round((on_time/total_records*100), 1) if total_records > 0 else 0}%</td>
                </tr>
                <tr>
                    <td>Late</td>
                    <td>{late}</td>
                    <td>{round((late/total_records*100), 1) if total_records > 0 else 0}%</td>
                </tr>
                <tr>
                    <td>Absent</td>
                    <td>{absent}</td>
                    <td>{round((absent/total_records*100), 1) if total_records > 0 else 0}%</td>
                </tr>
            </table>
            
            <div class="footer">
                <p>Generated on {today.strftime('%B %d, %Y at %H:%M')}</p>
                <p>© {today.year} {settings.company_name}</p>
            </div>
        </body>
        </html>
        '''
        
        output = io.BytesIO()
        pisa.CreatePDF(io.BytesIO(html.encode('utf-8')), dest=output)
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename=analytics_report_{today.strftime("%Y%m%d")}.pdf'}
        )
    
    except ImportError:
        flash('PDF generation requires xhtml2pdf. Please install it.', 'warning')
        return redirect(url_for('analytics'))
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'danger')
        return redirect(url_for('analytics'))

# API Sync Endpoint
@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    settings = get_system_settings()
    
    if not api_key or api_key != settings.api_key:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        records = data.get('records', [])
        synced = 0
        errors = []
        
        for record in records:
            staff = Staff.query.filter_by(staff_id=record.get('staff_id')).first()
            if not staff:
                errors.append(f"Staff {record.get('staff_id')} not found")
                continue
            
            date = datetime.strptime(record.get('date'), '%Y-%m-%d').date()
            
            existing = Attendance.query.filter_by(staff_id=staff.id, date=date).first()
            
            check_in = None
            check_out = None
            
            if record.get('check_in'):
                check_in = datetime.strptime(record.get('check_in'), '%H:%M:%S').time()
            if record.get('check_out'):
                check_out = datetime.strptime(record.get('check_out'), '%H:%M:%S').time()
            
            # Determine status
            status = 'present'
            if check_in:
                work_start = datetime.strptime(settings.work_start_time, '%H:%M').time()
                threshold = timedelta(minutes=settings.late_threshold_minutes)
                check_in_dt = datetime.combine(date, check_in)
                work_start_dt = datetime.combine(date, work_start)
                if check_in_dt > work_start_dt + threshold:
                    status = 'late'
            else:
                status = 'absent'
            
            if existing:
                existing.check_in = check_in or existing.check_in
                existing.check_out = check_out or existing.check_out
                existing.status = status
            else:
                attendance = Attendance(
                    staff_id=staff.id,
                    school_id=staff.school_id,
                    date=date,
                    check_in=check_in,
                    check_out=check_out,
                    status=status
                )
                db.session.add(attendance)
            
            synced += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'synced': synced,
            'errors': errors
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Database Initialization
@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        
        # Create default admin if not exists
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                role='super_admin',
                is_active=True
            )
            db.session.add(admin)
        
        # Create default settings if not exists
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(
                company_name='Attendance Management System',
                late_threshold_minutes=15,
                work_start_time='08:00',
                work_end_time='17:00'
            )
            db.session.add(settings)
        
        db.session.commit()
        
        return '''
        <h2>Database Initialized Successfully!</h2>
        <p>Default admin credentials:</p>
        <ul>
            <li>Username: admin</li>
            <li>Password: admin123</li>
        </ul>
        <a href="/login">Go to Login</a>
        '''
    except Exception as e:
        db.session.rollback()
        return f'Error: {str(e)}'

# Migration Route
@app.route('/migrate-departments')
def migrate_departments():
    try:
        from sqlalchemy import text
        
        migrations = []
        
        # User table migrations
        user_columns = [
            ("organization_id", "INTEGER"),
            ("school_id", "INTEGER"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in user_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM "user" LIMIT 1'))
                migrations.append(f"user.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added user.{col_name}")
                except:
                    db.session.rollback()
        
        # Organization table migrations
        org_columns = [
            ("logo_url", "VARCHAR(500)"),
            ("is_school", "BOOLEAN DEFAULT TRUE"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in org_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM organization LIMIT 1'))
                migrations.append(f"organization.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE organization ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added organization.{col_name}")
                except:
                    db.session.rollback()
        
        # School table migrations
        school_columns = [
            ("address", "VARCHAR(500)"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in school_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM school LIMIT 1'))
                migrations.append(f"school.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE school ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added school.{col_name}")
                except:
                    db.session.rollback()
        
        # Staff table migrations
        staff_columns = [
            ("department", "VARCHAR(100)"),
            ("position", "VARCHAR(100)"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in staff_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM staff LIMIT 1'))
                migrations.append(f"staff.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE staff ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added staff.{col_name}")
                except:
                    db.session.rollback()
        
        # Attendance table migrations
        attendance_columns = [
            ("school_id", "INTEGER"),
            ("check_in", "TIME"),
            ("check_out", "TIME"),
            ("status", "VARCHAR(20) DEFAULT 'present'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in attendance_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM attendance LIMIT 1'))
                migrations.append(f"attendance.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE attendance ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added attendance.{col_name}")
                except:
                    db.session.rollback()
        
        # SystemSettings table migrations
        settings_columns = [
            ("company_logo_url", "VARCHAR(500)"),
            ("api_key", "VARCHAR(100)"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        
        for col_name, col_type in settings_columns:
            try:
                db.session.execute(text(f'SELECT "{col_name}" FROM system_settings LIMIT 1'))
                migrations.append(f"system_settings.{col_name} already exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f'ALTER TABLE system_settings ADD COLUMN "{col_name}" {col_type}'))
                    db.session.commit()
                    migrations.append(f"Added system_settings.{col_name}")
                except:
                    db.session.rollback()
        
        # Create department table
        try:
            db.session.execute(text('SELECT id FROM department LIMIT 1'))
            migrations.append("department table already exists")
        except:
            db.session.rollback()
            try:
                db.session.execute(text('''
                    CREATE TABLE department (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        organization_id INTEGER,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
                db.session.commit()
                migrations.append("Created department table")
            except:
                db.session.rollback()
        
        # Set default values
        try:
            db.session.execute(text('UPDATE "user" SET is_active = TRUE WHERE is_active IS NULL'))
            db.session.execute(text('UPDATE organization SET is_active = TRUE WHERE is_active IS NULL'))
            db.session.execute(text('UPDATE school SET is_active = TRUE WHERE is_active IS NULL'))
            db.session.execute(text('UPDATE staff SET is_active = TRUE WHERE is_active IS NULL'))
            db.session.commit()
            migrations.append("Set default values for is_active")
        except:
            db.session.rollback()
        
        # Update attendance school_id from staff
        try:
            db.session.execute(text('''
                UPDATE attendance 
                SET school_id = staff.school_id 
                FROM staff 
                WHERE attendance.staff_id = staff.id 
                AND attendance.school_id IS NULL
            '''))
            db.session.commit()
            migrations.append("Updated attendance.school_id from staff")
        except:
            db.session.rollback()
        
        # Add default departments
        orgs = Organization.query.all()
        dept_count = 0
        for org in orgs:
            existing = Department.query.filter_by(organization_id=org.id).count()
            if existing == 0:
                if org.is_school or org.is_school is None:
                    defaults = ['Academic', 'Non-Academic', 'Administration', 'Support Staff']
                else:
                    defaults = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration']
                
                for dept_name in defaults:
                    dept = Department(name=dept_name, organization_id=org.id)
                    db.session.add(dept)
                    dept_count += 1
        
        db.session.commit()
        migrations.append(f"Added {dept_count} default departments")
        
        return f'''
        <h2>Migration Complete!</h2>
        <ul>
            {"".join(f"<li>{m}</li>" for m in migrations)}
        </ul>
        <br>
        <a href="/login">Go to Login</a>
        '''
    
    except Exception as e:
        db.session.rollback()
        return f'Migration error: {str(e)}'

if __name__ == '__main__':
    app.run(debug=True)
