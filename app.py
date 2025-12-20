import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import secrets
import json
from xhtml2pdf import pisa

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

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), default='Wakato Technologies')
    company_logo_url = db.Column(db.String(500), nullable=True)
    
    @staticmethod
    def get_settings():
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(company_name='Wakato Technologies')
            db.session.add(settings)
            db.session.commit()
        return settings

class Organization(db.Model):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    is_school = db.Column(db.Boolean, default=True)
    branches = db.relationship('School', backref='organization', lazy=True)
    departments = db.relationship('Department', backref='organization', lazy=True)


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


user_schools = db.Table('user_schools',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('schools.id'), primary_key=True)
)

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
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
    allowed_schools = db.relationship('School', secondary=user_schools, lazy='subquery',
        backref=db.backref('allowed_users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_initials(self):
        return self.username[0].upper() if self.username else 'U'
    
    def get_accessible_schools(self):
        if self.role == 'super_admin':
            return School.query.all()
        elif self.allowed_schools:
            return self.allowed_schools
        elif self.school_id:
            return [self.school]
        return []
    
    def get_accessible_school_ids(self):
        return [s.id for s in self.get_accessible_schools()]
    
    def get_accessible_organizations(self):
        if self.role == 'super_admin':
            return Organization.query.all()
        org_ids = set()
        for school in self.get_accessible_schools():
            if school.organization_id:
                org_ids.add(school.organization_id)
        if org_ids:
            return Organization.query.filter(Organization.id.in_(org_ids)).all()
        return []
    
    def get_display_organization(self):
        if self.role == 'super_admin':
            return None
        schools = self.get_accessible_schools()
        if not schools:
            return None
        first_school = schools[0]
        if first_school.organization:
            return first_school.organization
        return None

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

@app.context_processor
def inject_settings():
    if current_user.is_authenticated:
        settings = SystemSettings.get_settings()
        user_org = current_user.get_display_organization()
        return {'system_settings': settings, 'user_organization': user_org}
    return {'system_settings': None, 'user_organization': None}

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

def get_staff_data_for_api(school):
    staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
    staff_list_data = []
    for s in staff:
        name_parts = s.name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        staff_list_data.append({
            'staff_id': s.staff_id,
            'first_name': first_name,
            'last_name': last_name,
            'name': s.name,
            'department': s.department
        })
    return staff_list_data


def get_departments_for_school(school_id):
    """Get departments for a school based on its organization"""
    school = School.query.get(school_id)
    if school and school.organization_id:
        departments = Department.query.filter_by(
            organization_id=school.organization_id, 
            is_active=True
        ).order_by(Department.name).all()
        return [d.name for d in departments]
    # Fallback to default departments
    return ['Academic', 'Admin', 'Non-Academic', 'Management']


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
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def settings():
    settings = SystemSettings.get_settings()
    organizations = Organization.query.all()
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name', 'Wakato Technologies')
        settings.company_logo_url = request.form.get('company_logo_url', '').strip() or None
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', settings=settings, organizations=organizations)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        name = request.form.get('name')
        logo_url = request.form.get('logo_url', '').strip() or None
        is_school = request.form.get('is_school') == 'on'
        
        org = Organization(name=name, logo_url=logo_url, is_school=is_school)
        db.session.add(org)
        db.session.commit()
        
        # Create default departments based on organization type
        if is_school:
            default_depts = ['Academic', 'Non-Academic', 'Administration', 'Management', 'Support Staff']
        else:
            default_depts = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration', 'Management']
        
        for dept_name in default_depts:
            dept = Department(name=dept_name, organization_id=org.id)
            db.session.add(dept)
        db.session.commit()
        
        flash('Organization added with default departments!', 'success')
        return redirect(url_for('settings'))
    return render_template('add_organization.html')

@app.route('/organizations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url', '').strip() or None
        org.is_school = request.form.get('is_school') == 'on'
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('edit_organization.html', organization=org)

@app.route('/organizations/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    if org.branches:
        flash('Cannot delete organization with branches. Remove branches first.', 'danger')
        return redirect(url_for('settings'))
    
    # Delete associated departments first
    Department.query.filter_by(organization_id=id).delete()
    
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('settings'))


# ============== DEPARTMENT MANAGEMENT ==============

@app.route('/organizations/<int:org_id>/departments')
@login_required
@role_required('super_admin')
def manage_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    departments = Department.query.filter_by(organization_id=org_id, is_active=True).order_by(Department.name).all()
    return render_template('manage_departments.html', organization=org, departments=departments)


@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
@role_required('super_admin')
def add_department(org_id):
    name = request.form.get('name', '').strip()
    if name:
        # Check if department already exists for this organization
        existing = Department.query.filter_by(organization_id=org_id, name=name, is_active=True).first()
        if not existing:
            dept = Department(name=name, organization_id=org_id)
            db.session.add(dept)
            db.session.commit()
            flash(f'Department "{name}" added successfully!', 'success')
        else:
            flash('Department already exists!', 'warning')
    else:
        flash('Department name is required!', 'danger')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/departments/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_department(id):
    dept = Department.query.get_or_404(id)
    org_id = dept.organization_id
    
    # Soft delete - just mark as inactive
    dept.is_active = False
    db.session.commit()
    
    flash('Department removed successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/organizations/<int:org_id>/departments/seed', methods=['POST'])
@login_required
@role_required('super_admin')
def seed_default_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    
    # Determine defaults based on organization type
    is_school = getattr(org, 'is_school', True)
    if is_school is None:
        is_school = True
    
    if is_school:
        defaults = ['Academic', 'Non-Academic', 'Administration', 'Management', 'Support Staff']
    else:
        defaults = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration', 'Management', 'Sales']
    
    # Get existing department names
    existing = [d.name for d in Department.query.filter_by(organization_id=org_id, is_active=True).all()]
    
    added = 0
    for name in defaults:
        if name not in existing:
            dept = Department(name=name, organization_id=org_id)
            db.session.add(dept)
            added += 1
    
    db.session.commit()
    
    if added > 0:
        flash(f'{added} default departments added!', 'success')
    else:
        flash('All default departments already exist.', 'info')
    
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    if current_user.role == 'super_admin' or accessible_school_ids:
        if current_user.role == 'super_admin':
            all_staff = Staff.query.filter_by(is_active=True).all()
        else:
            all_staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids), Staff.is_active==True).all()
        total_staff = len(all_staff)
        all_staff_ids = [s.id for s in all_staff]
        today_attendance = Attendance.query.filter(
            Attendance.staff_id.in_(all_staff_ids),
            Attendance.date == today
        ).count() if all_staff_ids else 0
        late_today = Attendance.query.filter(
            Attendance.staff_id.in_(all_staff_ids),
            Attendance.date == today,
            Attendance.is_late == True
        ).count() if all_staff_ids else 0
        non_mgmt_staff = [s for s in all_staff if s.department != 'Management']
        non_mgmt_ids = [s.id for s in non_mgmt_staff]
        present_ids = [a.staff_id for a in Attendance.query.filter(
            Attendance.staff_id.in_(non_mgmt_ids),
            Attendance.date == today
        ).all()] if non_mgmt_ids else []
        absent_today = len([s for s in non_mgmt_staff if s.id not in present_ids])
        school_stats = []
        for school in schools:
            school_staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
            school_staff_ids = [s.id for s in school_staff]
            school_present = Attendance.query.filter(
                Attendance.staff_id.in_(school_staff_ids),
                Attendance.date == today
            ).count() if school_staff_ids else 0
            school_late = Attendance.query.filter(
                Attendance.staff_id.in_(school_staff_ids),
                Attendance.date == today,
                Attendance.is_late == True
            ).count() if school_staff_ids else 0
            school_stats.append({
                'school': school,
                'total_staff': len(school_staff),
                'present': school_present,
                'late': school_late
            })
    else:
        total_staff = 0
        today_attendance = 0
        late_today = 0
        absent_today = 0
        school_stats = []
    return render_template('dashboard.html', 
                         schools=schools,
                         school_stats=school_stats,
                         total_schools=len(schools),
                         total_staff=total_staff, 
                         today_attendance=today_attendance, 
                         late_today=late_today,
                         absent_today=absent_today)

@app.route('/schools')
@login_required
@role_required('super_admin')
def schools():
    all_schools = School.query.all()
    return render_template('schools.html', schools=all_schools)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        logo_url = request.form.get('logo_url', '').strip() or None
        organization_id = request.form.get('organization_id') or None
        api_key = secrets.token_hex(32)
        school = School(name=name, short_name=short_name, logo_url=logo_url, api_key=api_key, organization_id=organization_id)
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        school.logo_url = request.form.get('logo_url', '').strip() or None
        school.organization_id = request.form.get('organization_id') or None
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('edit_school.html', school=school, organizations=organizations)

@app.route('/schools/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/regenerate-key/<int:id>')
@login_required
@role_required('super_admin')
def regenerate_api_key(id):
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff_list():
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    if current_user.role == 'super_admin':
        staff = Staff.query.all()
    elif accessible_school_ids:
        staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()
    else:
        staff = []
    staff_with_status = []
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
        staff_with_status.append({
            'staff': s,
            'status': status,
            'status_color': status_color
        })
    schools = School.query.all()
    return render_template('staff.html', staff_with_status=staff_with_status, schools=schools)

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
            flash('Staff ID already exists!', 'danger')
            return redirect(url_for('add_staff'))
        staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    
    # Get schools and departments based on role
    if current_user.role == 'super_admin':
        schools = School.query.all()
        # Get all unique departments from all organizations
        all_depts = Department.query.filter_by(is_active=True).all()
        departments = list(set([d.name for d in all_depts]))
        if not departments:
            departments = ['Academic', 'Admin', 'Non-Academic', 'Management']
    else:
        schools = [current_user.school]
        if current_user.school_id:
            departments = get_departments_for_school(current_user.school_id)
        else:
            departments = ['Academic', 'Admin', 'Non-Academic', 'Management']
    
    departments.sort()
    return render_template('add_staff.html', schools=schools, departments=departments)

@app.route('/staff/toggle/<int:id>')
@login_required
@role_required('super_admin', 'school_admin')
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin' and staff.school_id != current_user.school_id:
        flash('You do not have permission to modify this staff.', 'danger')
        return redirect(url_for('staff_list'))
    staff.is_active = not staff.is_active
    db.session.commit()
    status = 'activated' if staff.is_active else 'deactivated'
    flash(f'Staff {status} successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def bulk_upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected!', 'danger')
            return redirect(url_for('bulk_upload'))
        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'danger')
            return redirect(url_for('bulk_upload'))
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file!', 'danger')
            return redirect(url_for('bulk_upload'))
        school_id = request.form.get('school_id')
        if current_user.role == 'school_admin':
            school_id = current_user.school_id
        
        # Get valid departments for this school
        valid_departments = get_departments_for_school(school_id)
        
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
                existing = Staff.query.filter_by(staff_id=staff_id).first()
                if existing:
                    skipped += 1
                    continue
                # Validate department - must exist in organization's departments
                if department not in valid_departments:
                    # Use first valid department as fallback
                    department = valid_departments[0] if valid_departments else 'Academic'
                staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
                db.session.add(staff)
                added += 1
            db.session.commit()
            flash(f'Bulk upload complete! Added: {added}, Skipped: {skipped}', 'success')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
        return redirect(url_for('staff_list'))
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = [current_user.school]
    return render_template('bulk_upload.html', schools=schools)

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    all_users = User.query.all()
    return render_template('users.html', users=all_users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        school_ids = request.form.getlist('school_ids')
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists!', 'danger')
            return redirect(url_for('add_user'))
        user = User(username=username, role=role)
        user.set_password(password)
        if school_ids:
            for school_id in school_ids:
                school = School.query.get(int(school_id))
                if school:
                    user.allowed_schools.append(school)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('add_user.html', schools=schools, roles=roles)

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.role = request.form.get('role')
        school_ids = request.form.getlist('school_ids')
        password = request.form.get('password')
        if password:
            user.set_password(password)
        user.allowed_schools = []
        if school_ids:
            for school_id in school_ids:
                school = School.query.get(int(school_id))
                if school:
                    user.allowed_schools.append(school)
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('edit_user.html', user=user, schools=schools, roles=roles)

@app.route('/users/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete yourself!', 'danger')
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/reports/attendance')
@login_required
def attendance_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('attendance_report.html', 
                         attendance=attendance, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         today=today.isoformat())

@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late Minutes', 'Overtime Minutes'])
    for a in attendance:
        writer.writerow([
            a.date.strftime('%d/%m/%Y'),
            a.staff.staff_id,
            a.staff.name,
            a.staff.school.short_name or a.staff.school.name,
            a.staff.department,
            a.sign_in_time.strftime('%H:%M') if a.sign_in_time else '',
            a.sign_out_time.strftime('%H:%M') if a.sign_out_time else '',
            'Late' if a.is_late else 'On Time',
            a.late_minutes,
            a.overtime_minutes
        ])
    output.seek(0)
    filename = f'attendance_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/late')
@login_required
def late_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    calc_mode = request.args.get('calc_mode', 'alltime')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    show_toggle = bool(date_from and date_to)
    start_date = None
    end_date = None
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        except:
            pass
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    late_staff = []
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
            period_total = period_att_query.count()
            period_late = period_att_query.filter_by(is_late=True).count()
        else:
            period_total = 0
            period_late = 0
        all_att_query = Attendance.query.filter_by(staff_id=s.id)
        all_total = all_att_query.count()
        all_late = all_att_query.filter_by(is_late=True).count()
        if start_date and end_date:
            times_late = period_late
        else:
            times_late = s.times_late
        if start_date and end_date and period_total == 0:
            continue
        if times_late > 0 or s.times_late > 0:
            if calc_mode == 'period' and start_date and end_date:
                if period_total > 0:
                    punctuality = round(((period_total - period_late) / period_total) * 100, 1)
                    lateness = round((period_late / period_total) * 100, 1)
                else:
                    punctuality = 0.0
                    lateness = 0.0
            else:
                if all_total > 0:
                    punctuality = round(((all_total - all_late) / all_total) * 100, 1)
                    lateness = round((all_late / all_total) * 100, 1)
                else:
                    punctuality = 0.0
                    lateness = 0.0
            late_staff.append({
                'staff': s,
                'times_late': times_late,
                'punctuality': punctuality,
                'lateness': lateness
            })
    late_staff.sort(key=lambda x: x['times_late'], reverse=True)
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('late_report.html', 
                         late_staff=late_staff, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         calc_mode=calc_mode,
                         show_toggle=show_toggle,
                         today=today.isoformat())

@app.route('/reports/late/download')
@login_required
def download_late_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    calc_mode = request.args.get('calc_mode', 'alltime')
    start_date = None
    end_date = None
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        except:
            pass
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
            period_total = period_att_query.count()
            period_late = period_att_query.filter_by(is_late=True).count()
        else:
            period_total = 0
            period_late = 0
        all_att_query = Attendance.query.filter_by(staff_id=s.id)
        all_total = all_att_query.count()
        all_late = all_att_query.filter_by(is_late=True).count()
        if start_date and end_date:
            times_late = period_late
        else:
            times_late = s.times_late
        if start_date and end_date and period_total == 0:
            continue
        if times_late > 0 or s.times_late > 0:
            if calc_mode == 'period' and start_date and end_date:
                if period_total > 0:
                    punctuality = round(((period_total - period_late) / period_total) * 100, 1)
                    lateness = round((period_late / period_total) * 100, 1)
                else:
                    punctuality = 0.0
                    lateness = 0.0
            else:
                if all_total > 0:
                    punctuality = round(((all_total - all_late) / all_total) * 100, 1)
                    lateness = round((all_late / all_total) * 100, 1)
                else:
                    punctuality = 0.0
                    lateness = 0.0
            writer.writerow([
                s.staff_id,
                s.name,
                s.school.short_name or s.school.name,
                s.department,
                times_late,
                punctuality,
                lateness
            ])
    output.seek(0)
    filename = f'late_report_{date_from}_to_{date_to}.csv' if date_from and date_to else f'late_report_{date.today()}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/late/reset', methods=['POST'])
@login_required
@role_required('super_admin')
def reset_late_counter():
    school_id = request.form.get('school_id', '')
    if school_id:
        staff = Staff.query.filter_by(school_id=school_id).all()
        school = School.query.get(school_id)
        school_name = school.name if school else 'Unknown'
    else:
        staff = Staff.query.all()
        school_name = 'all branches'
    for s in staff:
        s.times_late = 0
    db.session.commit()
    flash(f'Late counters reset for {school_name}!', 'success')
    return redirect(url_for('late_report'))

@app.route('/reports/absent')
@login_required
def absent_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    absent_records = []
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            for s in all_staff:
                if s.department == 'Management':
                    continue
                attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
                if not attendance:
                    absent_records.append({
                        'date': current_date,
                        'staff': s
                    })
        current_date += timedelta(days=1)
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('absent_report.html', 
                         absent_records=absent_records, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         today=today.isoformat())

@app.route('/reports/absent/download')
@login_required
def download_absent_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department'])
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            for s in all_staff:
                if s.department == 'Management':
                    continue
                attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
                if not attendance:
                    writer.writerow([
                        current_date.strftime('%d/%m/%Y'),
                        s.staff_id,
                        s.name,
                        s.school.short_name or s.school.name,
                        s.department
                    ])
        current_date += timedelta(days=1)
    output.seek(0)
    filename = f'absent_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/overtime')
@login_required
def overtime_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.overtime_minutes > 0
    )
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' an
