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
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY', '')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'

# ==================== MODELS ====================

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
    hr_email = db.Column(db.String(120), nullable=True)
    hr_email_name = db.Column(db.String(100), nullable=True)
    branches = db.relationship('School', backref='organization', lazy=True)
    departments = db.relationship('Department', backref='organization', lazy=True, cascade='all, delete-orphan')


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @staticmethod
    def create_defaults(organization_id):
        defaults = ['Academic', 'Non-Academic', 'Administrative', 'Support Staff']
        for name in defaults:
            dept = Department(name=name, organization_id=organization_id)
            db.session.add(dept)
        db.session.commit()


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
    
    # Monday to Friday schedules
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
    
    # Saturday and Sunday schedules
    schedule_sat_start = db.Column(db.String(5), default='08:00')
    schedule_sat_end = db.Column(db.String(5), default='17:00')
    schedule_sun_start = db.Column(db.String(5), default='08:00')
    schedule_sun_end = db.Column(db.String(5), default='17:00')
    
    # Shift system fields
    shift_mode_enabled = db.Column(db.Boolean, default=False)
    time_format_24h = db.Column(db.Boolean, default=True)
    work_days = db.Column(db.String(50), default='mon,tue,wed,thu,fri')
    grace_period_minutes = db.Column(db.Integer, default=0)
    
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
    staff_id = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    times_late = db.Column(db.Integer, default=0)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)
    attendance = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')
    queries_received = db.relationship('StaffQuery', backref='staff', lazy=True, cascade='all, delete-orphan')


class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    grace_period_minutes = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    school = db.relationship('School', backref=db.backref('shifts', lazy=True, cascade='all, delete-orphan'))
    assignments = db.relationship('StaffShiftAssignment', backref='shift', lazy=True, cascade='all, delete-orphan')


class StaffShiftAssignment(db.Model):
    __tablename__ = 'staff_shift_assignments'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'), nullable=False)
    effective_from = db.Column(db.Date, nullable=False, default=date.today)
    effective_to = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    staff = db.relationship('Staff', backref=db.backref('shift_assignments', lazy=True))


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


class QueryTemplate(db.Model):
    __tablename__ = 'query_templates'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    from_email = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    organization = db.relationship('Organization', backref='query_templates')
    creator = db.relationship('User', backref='created_templates')


class StaffQuery(db.Model):
    __tablename__ = 'staff_queries'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=False)
    sent_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    times_late_at_query = db.Column(db.Integer, default=0)
    email_status = db.Column(db.String(20), default='pending')
    
    template = db.relationship('QueryTemplate', backref='queries_sent')
    sender = db.relationship('User', backref='queries_sent')


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
@app.template_filter('convert_to_12h')
def convert_to_12h(time_str):
    if not time_str:
        return ''
    try:
        time_obj = datetime.strptime(time_str, '%H:%M')
        return time_obj.strftime('%I:%M %p')
    except:
        return time_str

# ==================== HELPER FUNCTIONS ====================

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
    """Get schedule for a specific day (0=Monday, 6=Sunday)"""
    days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    if day_of_week < 7:
        day = days[day_of_week]
        start = getattr(school, f'schedule_{day}_start', None)
        end = getattr(school, f'schedule_{day}_end', None)
        return start, end
    return None, None


def format_time_display(time_str, use_24h=True):
    """Convert 24h time string to 12h or keep as 24h based on setting"""
    if not time_str:
        return ''
    try:
        time_obj = datetime.strptime(time_str, '%H:%M')
        if use_24h:
            return time_str
        else:
            return time_obj.strftime('%I:%M %p')
    except:
        return time_str


def is_work_day(school, target_date):
    """Check if target_date is a work day for the school"""
    work_days_str = school.work_days or 'mon,tue,wed,thu,fri'
    work_days = [d.strip().lower() for d in work_days_str.split(',')]
    day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    day_of_week = target_date.weekday()
    return day_names[day_of_week] in work_days


def get_staff_schedule_for_date(staff, target_date):
    """
    Get the schedule for a staff member on a specific date.
    Returns (start_time, end_time, grace_minutes, is_shift)
    """
    school = staff.school
    if not school:
        return None, None, 0, False
    
    # Check if this is a work day
    if not is_work_day(school, target_date):
        return None, None, 0, False
    
    # Check if shift mode is enabled and staff has active shift
    if school.shift_mode_enabled:
        active_assignment = StaffShiftAssignment.query.filter(
            StaffShiftAssignment.staff_id == staff.id,
            StaffShiftAssignment.is_active == True,
            StaffShiftAssignment.effective_from <= target_date,
            db.or_(
                StaffShiftAssignment.effective_to.is_(None),
                StaffShiftAssignment.effective_to >= target_date
            )
        ).first()
        
        if active_assignment and active_assignment.shift and active_assignment.shift.is_active:
            shift = active_assignment.shift
            return shift.start_time, shift.end_time, shift.grace_period_minutes, True
    
    # Fall back to regular branch schedule
    day_of_week = target_date.weekday()
    start_time, end_time = get_school_schedule(school, day_of_week)
    grace_minutes = school.grace_period_minutes or 0
    
    return start_time, end_time, grace_minutes, False


def get_staff_current_shift(staff):
    """Get the current active shift for a staff member, if any"""
    if not staff.school or not staff.school.shift_mode_enabled:
        return None
    
    today = date.today()
    assignment = StaffShiftAssignment.query.filter(
        StaffShiftAssignment.staff_id == staff.id,
        StaffShiftAssignment.is_active == True,
        StaffShiftAssignment.effective_from <= today,
        db.or_(
            StaffShiftAssignment.effective_to.is_(None),
            StaffShiftAssignment.effective_to >= today
        )
    ).first()
    
    if assignment and assignment.shift and assignment.shift.is_active:
        return assignment.shift
    return None


def get_staff_data_for_api(school):
    staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
    staff_list_data = []
    for s in staff:
        name_parts = s.name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Get current shift info if applicable
        shift_info = None
        if school.shift_mode_enabled:
            current_shift = get_staff_current_shift(s)
            if current_shift:
                shift_info = {
                    'name': current_shift.name,
                    'start_time': format_time_display(current_shift.start_time, school.time_format_24h),
                    'end_time': format_time_display(current_shift.end_time, school.time_format_24h)
                }
        
        staff_list_data.append({
            'staff_id': s.staff_id,
            'first_name': first_name,
            'last_name': last_name,
            'name': s.name,
            'department': s.department,
            'shift': shift_info
        })
    return staff_list_data


def check_staff_id_exists_in_org(staff_id, school_id, exclude_staff_id=None):
    if not school_id:
        return None
    try:
        school_id = int(school_id)
    except (ValueError, TypeError):
        return None
    branch = School.query.get(school_id)
    if not branch:
        return None
    if branch.organization_id:
        org_branch_ids = [s.id for s in School.query.filter_by(organization_id=branch.organization_id).all()]
        query = Staff.query.filter(Staff.staff_id == staff_id, Staff.school_id.in_(org_branch_ids))
    else:
        query = Staff.query.filter_by(staff_id=staff_id, school_id=school_id)
    if exclude_staff_id:
        query = query.filter(Staff.id != exclude_staff_id)
    return query.first()


def send_query_email(staff, template, organization, sender, late_count=None, period_str=None):
    if not staff.email:
        return False, "Staff has no email address"
    
    api_key = app.config.get('SENDGRID_API_KEY')
    if not api_key:
        return False, "SendGrid API key not configured"
    
    # Get verified sender email from environment
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'noreply@wakatotech.com')
    
    # Reply-To: Use template's from_email, or organization's hr_email, or fallback
    reply_to_email = None
    if template.from_email:
        reply_to_email = template.from_email
    elif organization and organization.hr_email:
        reply_to_email = organization.hr_email
    
    # Use passed late_count or fall back to staff.times_late
    actual_late_count = late_count if late_count is not None else staff.times_late
    
    # Use passed period or default to "All Time"
    actual_period = period_str if period_str else "All Time"
    
    # Replace placeholders in body
    body = template.body
    body = body.replace('{staff_name}', staff.name)
    body = body.replace('{staff_id}', staff.staff_id)
    body = body.replace('{department}', staff.department or '')
    body = body.replace('{branch}', staff.school.name if staff.school else '')
    body = body.replace('{late_count}', str(actual_late_count))
    body = body.replace('{times_late}', str(actual_late_count))
    body = body.replace('{period}', actual_period)
    body = body.replace('{current_date}', datetime.now().strftime('%d/%m/%Y'))
    body = body.replace('{date}', datetime.now().strftime('%d/%m/%Y'))
    body = body.replace('{organization_name}', organization.name if organization else '')
    body = body.replace('{branch_name}', staff.school.name if staff.school else '')
    
    # Replace placeholders in subject
    subject = template.subject
    subject = subject.replace('{staff_name}', staff.name)
    subject = subject.replace('{date}', datetime.now().strftime('%d/%m/%Y'))
    subject = subject.replace('{period}', actual_period)
    
    # Build email payload
    email_data = {
        'personalizations': [{'to': [{'email': staff.email}]}],
        'from': {'email': from_email, 'name': 'HR Department'},
        'subject': subject,
        'content': [{'type': 'text/html', 'value': body}]
    }
    
    # Add Reply-To if available
    if reply_to_email:
        email_data['reply_to'] = {'email': reply_to_email}
    
    try:
        response = requests.post(
            'https://api.sendgrid.com/v3/mail/send',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json=email_data
        )
        if response.status_code in [200, 201, 202]:
            return True, "Email sent successfully"
        else:
            return False, f"SendGrid error: {response.status_code} - {response.text}"
    except Exception as e:
        return False, str(e)


def format_minutes_to_hours(minutes):
    if minutes <= 0:
        return "0mins"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0:
        return f"{hours}hr{'s' if hours > 1 else ''} {mins}mins"
    elif hours > 0:
        return f"{hours}hr{'s' if hours > 1 else ''}"
    else:
        return f"{mins}mins"


def calculate_late_status(staff, sign_in_datetime, record_date):
    """
    Calculate if staff is late based on their schedule (shift or regular).
    Returns (is_late, late_minutes, scheduled_start_time)
    """
    start_time, end_time, grace_minutes, is_shift = get_staff_schedule_for_date(staff, record_date)
    
    if not start_time:
        return False, 0, None
    
    # Management staff are not marked late
    if staff.department == 'Management':
        return False, 0, start_time
    
    try:
        scheduled_start = datetime.strptime(start_time, '%H:%M').time()
        
        # Add grace period
        scheduled_with_grace = datetime.combine(record_date, scheduled_start) + timedelta(minutes=grace_minutes)
        scheduled_start_with_grace = scheduled_with_grace.time()
        
        if sign_in_datetime.time() > scheduled_start_with_grace:
            # Calculate late minutes from original scheduled time (not grace time)
            delta = datetime.combine(record_date, sign_in_datetime.time()) - datetime.combine(record_date, scheduled_start)
            late_minutes = int(delta.total_seconds() / 60)
            return True, late_minutes, start_time
        
        return False, 0, start_time
    except:
        return False, 0, start_time


def calculate_overtime(staff, sign_out_datetime, record_date):
    """
    Calculate overtime based on staff schedule (shift or regular).
    Returns overtime_minutes
    """
    start_time, end_time, grace_minutes, is_shift = get_staff_schedule_for_date(staff, record_date)
    
    if not end_time:
        return 0
    
    try:
        scheduled_end = datetime.strptime(end_time, '%H:%M').time()
        
        if sign_out_datetime.time() > scheduled_end:
            delta = datetime.combine(record_date, sign_out_datetime.time()) - datetime.combine(record_date, scheduled_end)
            return int(delta.total_seconds() / 60)
        
        return 0
    except:
        return 0
# ==================== AUTH ROUTES ====================

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


# ==================== SETTINGS & ORGANIZATIONS ====================

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
        hr_email = request.form.get('hr_email', '').strip() or None
        hr_email_name = request.form.get('hr_email_name', '').strip() or None
        org = Organization(name=name, logo_url=logo_url, hr_email=hr_email, hr_email_name=hr_email_name)
        db.session.add(org)
        db.session.commit()
        Department.create_defaults(org.id)
        flash('Organization added successfully with default departments!', 'success')
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
        org.hr_email = request.form.get('hr_email', '').strip() or None
        org.hr_email_name = request.form.get('hr_email_name', '').strip() or None
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
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/organizations/<int:org_id>/departments')
@login_required
@role_required('super_admin')
def manage_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    departments = Department.query.filter_by(organization_id=org_id).order_by(Department.name).all()
    dept_staff_counts = {}
    for dept in departments:
        count = Staff.query.join(School).filter(School.organization_id == org_id, Staff.department == dept.name).count()
        dept_staff_counts[dept.id] = count
    return render_template('manage_departments.html', organization=org, departments=departments, dept_staff_counts=dept_staff_counts)


@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
@role_required('super_admin')
def add_department(org_id):
    org = Organization.query.get_or_404(org_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Department name is required.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    existing = Department.query.filter_by(organization_id=org_id, name=name).first()
    if existing:
        flash('A department with this name already exists.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    dept = Department(name=name, organization_id=org_id)
    db.session.add(dept)
    db.session.commit()
    flash(f'Department "{name}" added successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/organizations/<int:org_id>/departments/edit/<int:dept_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def edit_department(org_id, dept_id):
    dept = Department.query.get_or_404(dept_id)
    if dept.organization_id != org_id:
        flash('Invalid department.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    old_name = dept.name
    new_name = request.form.get('name', '').strip()
    if not new_name:
        flash('Department name is required.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    existing = Department.query.filter_by(organization_id=org_id, name=new_name).first()
    if existing and existing.id != dept_id:
        flash('A department with this name already exists.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    Staff.query.join(School).filter(School.organization_id == org_id, Staff.department == old_name).update({Staff.department: new_name}, synchronize_session=False)
    dept.name = new_name
    db.session.commit()
    flash(f'Department renamed from "{old_name}" to "{new_name}".', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/organizations/<int:org_id>/departments/delete/<int:dept_id>')
@login_required
@role_required('super_admin')
def delete_department(org_id, dept_id):
    dept = Department.query.get_or_404(dept_id)
    if dept.organization_id != org_id:
        flash('Invalid department.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    staff_count = Staff.query.join(School).filter(School.organization_id == org_id, Staff.department == dept.name).count()
    if staff_count > 0:
        flash(f'Cannot delete "{dept.name}" - {staff_count} staff member(s) are assigned to this department.', 'danger')
        return redirect(url_for('manage_departments', org_id=org_id))
    dept_name = dept.name
    db.session.delete(dept)
    db.session.commit()
    flash(f'Department "{dept_name}" deleted successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/api/branch-departments/<int:branch_id>')
@login_required
def get_branch_departments(branch_id):
    school = School.query.get_or_404(branch_id)
    if school.organization_id:
        departments = Department.query.filter_by(organization_id=school.organization_id).order_by(Department.name).all()
        if departments:
            return jsonify([{'id': d.id, 'name': d.name} for d in departments])
    # Return defaults if no organization or no departments found
    return jsonify([
        {'id': 0, 'name': 'Academic'}, 
        {'id': 0, 'name': 'Administrative'}, 
        {'id': 0, 'name': 'Management'}, 
        {'id': 0, 'name': 'Non-Academic'}, 
        {'id': 0, 'name': 'Support Staff'}
    ])



@app.route('/api/organization-branches/<int:org_id>')
@login_required
def get_organization_branches(org_id):
    if current_user.role == 'super_admin':
        branches = School.query.filter_by(organization_id=org_id).all()
    else:
        accessible_ids = current_user.get_accessible_school_ids()
        branches = School.query.filter(School.organization_id == org_id, School.id.in_(accessible_ids)).all()
    return jsonify({'branches': [{'id': b.id, 'name': b.name} for b in branches]})


# ==================== DASHBOARD ====================

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
        management_staff = [s for s in all_staff if s.department == 'Management']
        non_mgmt_staff = [s for s in all_staff if s.department != 'Management']
        total_staff = len(non_mgmt_staff)
        management_count = len(management_staff)
        non_mgmt_ids = [s.id for s in non_mgmt_staff]
        today_attendance = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today).count() if non_mgmt_ids else 0
        late_today = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today, Attendance.is_late == True).count() if non_mgmt_ids else 0
        present_ids = [a.staff_id for a in Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today).all()] if non_mgmt_ids else []
        absent_today = len([s for s in non_mgmt_staff if s.id not in present_ids])
        school_stats = []
        for school in schools:
            school_staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
            school_non_mgmt = [s for s in school_staff if s.department != 'Management']
            school_staff_ids = [s.id for s in school_non_mgmt]
            school_present = Attendance.query.filter(Attendance.staff_id.in_(school_staff_ids), Attendance.date == today).count() if school_staff_ids else 0
            school_late = Attendance.query.filter(Attendance.staff_id.in_(school_staff_ids), Attendance.date == today, Attendance.is_late == True).count() if school_staff_ids else 0
            school_stats.append({'id': school.id, 'school': school, 'total_staff': len(school_non_mgmt), 'present': school_present, 'late': school_late})
    else:
        total_staff = 0
        management_count = 0
        today_attendance = 0
        late_today = 0
        absent_today = 0
        school_stats = []
    return render_template('dashboard.html', schools=schools, school_stats=school_stats, total_schools=len(schools), total_staff=total_staff, management_count=management_count, today_attendance=today_attendance, late_today=late_today, absent_today=absent_today)


@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    today = date.today()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
        school_ids = [s.id for s in schools]
    else:
        school_ids = current_user.get_accessible_school_ids()
        schools = School.query.filter(School.id.in_(school_ids)).all()
    
    total_staff = Staff.query.filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True
    ).count()
    
    management_count = Staff.query.filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True,
        Staff.department == 'Management'
    ).count()
    
    today_attendance = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today,
        Attendance.sign_in_time.isnot(None)
    ).count()
    
    late_today = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today,
        Attendance.is_late == True
    ).count()
    
    absent_today = total_staff - today_attendance - management_count
    if absent_today < 0:
        absent_today = 0
    
    # First check-in today
    first_checkin = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today,
        Attendance.sign_in_time.isnot(None)
    ).order_by(Attendance.sign_in_time.asc()).first()
    
    first_checkin_data = None
    if first_checkin:
        staff = first_checkin.staff
        school = School.query.get(staff.school_id)
        use_24h = school.time_format_24h if school and school.time_format_24h is not None else True
        
        if use_24h:
            time_str = first_checkin.sign_in_time.strftime('%H:%M')
        else:
            time_str = first_checkin.sign_in_time.strftime('%I:%M %p')
        
        first_checkin_data = {
            'name': staff.name,
            'branch': school.short_name or school.name if school else '-',
            'department': staff.department or '-',
            'time': time_str
        }
    
    # Recent activity (last 10 check-ins/outs) - order by sign_in_time desc
    recent = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today
    ).order_by(Attendance.sign_in_time.desc()).limit(10).all()
    
    recent_activity = []
    for r in recent:
        staff = r.staff
        school = School.query.get(staff.school_id)
        use_24h = school.time_format_24h if school and school.time_format_24h is not None else True
        
        if r.sign_out_time:
            action = 'signed out'
            if use_24h:
                time_str = r.sign_out_time.strftime('%H:%M')
            else:
                time_str = r.sign_out_time.strftime('%I:%M %p')
        elif r.sign_in_time:
            action = 'signed in'
            if use_24h:
                time_str = r.sign_in_time.strftime('%H:%M')
            else:
                time_str = r.sign_in_time.strftime('%I:%M %p')
        else:
            continue
        
        recent_activity.append({
            'name': staff.name,
            'action': action,
            'time': time_str,
            'branch': school.short_name or school.name if school else '-'
        })
    
    return jsonify({
        'total_schools': len(schools),
        'total_staff': total_staff,
        'management_count': management_count,
        'today_attendance': today_attendance,
        'late_today': late_today,
        'absent_today': absent_today,
        'first_checkin': first_checkin_data,
        'recent_activity': recent_activity
    })




@app.route('/api/search-staff')
@login_required
def search_staff():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter(Staff.is_active == True)
    if current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_query = staff_query.filter(db.or_(Staff.name.ilike(f'%{query}%'), Staff.staff_id.ilike(f'%{query}%'))).limit(10)
    results = []
    for staff in staff_query.all():
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
        if staff.department == 'Management':
            if attendance:
                status = 'signed_in'
                time_str = attendance.sign_in_time.strftime('%H:%M') if attendance.sign_in_time else None
            else:
                status = 'not_signed_in'
                time_str = None
        else:
            status = 'absent'
            time_str = None
            if attendance:
                if attendance.is_late:
                    status = 'late'
                else:
                    status = 'signed_in'
                if attendance.sign_in_time:
                    time_str = attendance.sign_in_time.strftime('%H:%M')
        results.append({'id': staff.id, 'staff_id': staff.staff_id, 'name': staff.name, 'branch': staff.school.short_name or staff.school.name if staff.school else 'N/A', 'department': staff.department, 'status': status, 'time': time_str})
    return jsonify({'results': results})


@app.route('/api/branch-staff/<int:branch_id>')
@login_required
def api_branch_staff(branch_id):
    school = School.query.get_or_404(branch_id)
    
    # Access check
    if current_user.role != 'super_admin':
        if school.id not in current_user.get_accessible_school_ids():
            return jsonify([])
    
    today = date.today()
    staff_list = Staff.query.filter_by(school_id=branch_id, is_active=True).all()
    
    use_24h = school.time_format_24h if school.time_format_24h is not None else True
    
    result = []
    for staff in staff_list:
        attendance = Attendance.query.filter_by(
            staff_id=staff.id,
            date=today
        ).first()
        
        time_in = ''
        time_out = ''
        status = 'Absent'
        
        if attendance:
            if attendance.sign_in_time:
                if use_24h:
                    time_in = attendance.sign_in_time.strftime('%H:%M')
                else:
                    time_in = attendance.sign_in_time.strftime('%I:%M %p')
                status = 'Late' if attendance.is_late else 'Present'
            if attendance.sign_out_time:
                if use_24h:
                    time_out = attendance.sign_out_time.strftime('%H:%M')
                else:
                    time_out = attendance.sign_out_time.strftime('%I:%M %p')
        
        shift_name = None
        if school.shift_mode_enabled:
            current_shift = get_staff_current_shift(staff)
            if current_shift:
                shift_name = current_shift.name
        
        result.append({
            'id': staff.id,
            'name': staff.name,
            'department': staff.department or '-',
            'status': status,
            'time_in': time_in,
            'time_out': time_out,
            'shift': shift_name
        })
    
    return jsonify(result)

# ==================== SCHOOLS/BRANCHES ====================

@app.route('/schools')
@login_required
def schools():
    organization_id = request.args.get('organization_id', type=int)
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        if organization_id:
            all_schools = School.query.filter_by(organization_id=organization_id).all()
        else:
            all_schools = School.query.all()
        show_admin_features = True
    else:
        organizations = current_user.get_accessible_organizations()
        accessible_ids = current_user.get_accessible_school_ids()
        if organization_id:
            all_schools = School.query.filter(School.organization_id == organization_id, School.id.in_(accessible_ids)).all()
        else:
            all_schools = School.query.filter(School.id.in_(accessible_ids)).all()
        show_admin_features = False
    
    total_staff = sum(len(s.staff) for s in all_schools)
    total_active_staff = sum(len([st for st in s.staff if st.is_active]) for s in all_schools)
    
    return render_template('schools.html', 
        schools=all_schools, 
        organizations=organizations,
        selected_organization=organization_id,
        total_staff=total_staff,
        total_active_staff=total_active_staff,
        show_admin_features=show_admin_features
    )



@app.route('/branches')
@login_required
def branches():
    organization_id = request.args.get('organization_id', type=int)
    
    organizations = Organization.query.all()
    
    if current_user.role == 'super_admin':
        if organization_id:
            all_schools = School.query.filter_by(organization_id=organization_id).all()
        else:
            all_schools = School.query.all()
        show_admin_features = True
    else:
        accessible_ids = current_user.get_accessible_school_ids()
        if organization_id:
            all_schools = School.query.filter(School.organization_id == organization_id, School.id.in_(accessible_ids)).all()
        else:
            all_schools = School.query.filter(School.id.in_(accessible_ids)).all()
        show_admin_features = False
    
    total_staff = sum(len(s.staff) for s in all_schools)
    total_active_staff = sum(len([st for st in s.staff if st.is_active]) for s in all_schools)
    
    return render_template('schools.html', 
        schools=all_schools, 
        organizations=organizations,
        selected_organization=organization_id,
        total_staff=total_staff,
        total_active_staff=total_active_staff,
        show_admin_features=show_admin_features
    )


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
        for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
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
        for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
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


# ==================== BRANCH SETTINGS (SHIFT SYSTEM) ====================

@app.route('/branch/<int:id>/settings', methods=['GET', 'POST'])
@login_required
def branch_settings(id):
    school = School.query.get_or_404(id)
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
        show_api_section = False
    elif current_user.role == 'super_admin':
        show_api_section = True
    else:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action', 'save_settings')
        
        if action == 'save_settings':
            # Time format
            school.time_format_24h = request.form.get('time_format') == '24h'
            
            # Shift mode
            school.shift_mode_enabled = 'shift_mode_enabled' in request.form
            
            # Work days
            work_days = request.form.getlist('work_days')
            school.work_days = ','.join(work_days) if work_days else 'mon,tue,wed,thu,fri'
            
            # Grace period
            try:
                school.grace_period_minutes = int(request.form.get('grace_period_minutes', 0))
            except:
                school.grace_period_minutes = 0
            
            # Regular schedule for all 7 days
            for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
                start = request.form.get(f'schedule_{day}_start')
                end = request.form.get(f'schedule_{day}_end')
                if start:
                    setattr(school, f'schedule_{day}_start', start)
                if end:
                    setattr(school, f'schedule_{day}_end', end)
            
            db.session.commit()
            flash('Branch settings updated successfully!', 'success')
        
        return redirect(url_for('branch_settings', id=id))
    
    # Get shifts for this branch
    shifts = Shift.query.filter_by(school_id=id, is_active=True).order_by(Shift.name).all()
    
    # Get staff for assignment
    staff_list = Staff.query.filter_by(school_id=id, is_active=True).order_by(Staff.name).all()
    
    # Get current assignments with staff info
    assignments = db.session.query(StaffShiftAssignment, Staff, Shift).join(
        Staff, StaffShiftAssignment.staff_id == Staff.id
    ).join(
        Shift, StaffShiftAssignment.shift_id == Shift.id
    ).filter(
        Staff.school_id == id,
        StaffShiftAssignment.is_active == True,
        Shift.is_active == True
    ).order_by(Staff.name).all()
    
    # Parse work days for template
    work_days_list = (school.work_days or 'mon,tue,wed,thu,fri').split(',')
    
    return render_template('branch_settings.html', 
        school=school, 
        shifts=shifts, 
        staff_list=staff_list,
        assignments=assignments,
        show_api_section=show_api_section,
        work_days_list=work_days_list
    )


@app.route('/branch/<int:id>/shifts/add', methods=['POST'])
@login_required
def add_shift(id):
    school = School.query.get_or_404(id)
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    name = request.form.get('shift_name', '').strip()
    start_time = request.form.get('shift_start_time')
    end_time = request.form.get('shift_end_time')
    grace_period = request.form.get('shift_grace_period', 0)
    
    if not name or not start_time or not end_time:
        flash('Shift name, start time and end time are required', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    # Check for duplicate shift name
    existing = Shift.query.filter_by(school_id=id, name=name, is_active=True).first()
    if existing:
        flash(f'A shift named "{name}" already exists', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    try:
        grace_period = int(grace_period)
    except:
        grace_period = 0
    
    shift = Shift(
        school_id=id,
        name=name,
        start_time=start_time,
        end_time=end_time,
        grace_period_minutes=grace_period
    )
    db.session.add(shift)
    db.session.commit()
    
    flash(f'Shift "{name}" created successfully!', 'success')
    return redirect(url_for('branch_settings', id=id))


@app.route('/branch/<int:id>/shifts/<int:shift_id>/edit', methods=['POST'])
@login_required
def edit_shift(id, shift_id):
    school = School.query.get_or_404(id)
    shift = Shift.query.get_or_404(shift_id)
    
    if shift.school_id != id:
        flash('Invalid shift', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    new_name = request.form.get('shift_name', shift.name).strip()
    
    # Check for duplicate name (excluding current shift)
    existing = Shift.query.filter(
        Shift.school_id == id, 
        Shift.name == new_name, 
        Shift.is_active == True,
        Shift.id != shift_id
    ).first()
    if existing:
        flash(f'A shift named "{new_name}" already exists', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    shift.name = new_name
    shift.start_time = request.form.get('shift_start_time', shift.start_time)
    shift.end_time = request.form.get('shift_end_time', shift.end_time)
    
    try:
        shift.grace_period_minutes = int(request.form.get('shift_grace_period', 0))
    except:
        pass
    
    db.session.commit()
    flash(f'Shift "{shift.name}" updated successfully!', 'success')
    return redirect(url_for('branch_settings', id=id))


@app.route('/branch/<int:id>/shifts/<int:shift_id>/delete')
@login_required
def delete_shift(id, shift_id):
    school = School.query.get_or_404(id)
    shift = Shift.query.get_or_404(shift_id)
    
    if shift.school_id != id:
        flash('Invalid shift', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    shift_name = shift.name
    shift.is_active = False
    
    # Deactivate all assignments for this shift
    StaffShiftAssignment.query.filter_by(shift_id=shift_id).update({'is_active': False})
    
    db.session.commit()
    flash(f'Shift "{shift_name}" deleted!', 'success')
    return redirect(url_for('branch_settings', id=id))


@app.route('/branch/<int:id>/shifts/assign', methods=['POST'])
@login_required
def assign_shift(id):
    school = School.query.get_or_404(id)
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    staff_ids = request.form.getlist('staff_ids')
    shift_id = request.form.get('shift_id')
    effective_from = request.form.get('effective_from')
    effective_to = request.form.get('effective_to') or None
    
    if not staff_ids or not shift_id:
        flash('Please select staff and shift', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    shift = Shift.query.get(shift_id)
    if not shift or shift.school_id != id or not shift.is_active:
        flash('Invalid shift', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    try:
        effective_from_date = datetime.strptime(effective_from, '%Y-%m-%d').date() if effective_from else date.today()
        effective_to_date = datetime.strptime(effective_to, '%Y-%m-%d').date() if effective_to else None
    except:
        effective_from_date = date.today()
        effective_to_date = None
    
    assigned_count = 0
    for staff_id in staff_ids:
        staff = Staff.query.get(staff_id)
        if not staff or staff.school_id != id:
            continue
        
        # Deactivate existing assignments for this staff
        StaffShiftAssignment.query.filter_by(staff_id=staff.id, is_active=True).update({'is_active': False})
        
        # Create new assignment
        assignment = StaffShiftAssignment(
            staff_id=staff.id,
            shift_id=shift.id,
            effective_from=effective_from_date,
            effective_to=effective_to_date
        )
        db.session.add(assignment)
        assigned_count += 1
    
    db.session.commit()
    flash(f'{assigned_count} staff assigned to shift "{shift.name}"', 'success')
    return redirect(url_for('branch_settings', id=id))


@app.route('/branch/<int:id>/shifts/unassign/<int:assignment_id>')
@login_required
def unassign_shift(id, assignment_id):
    school = School.query.get_or_404(id)
    assignment = StaffShiftAssignment.query.get_or_404(assignment_id)
    
    # Verify staff belongs to this school
    if assignment.staff.school_id != id:
        flash('Invalid assignment', 'danger')
        return redirect(url_for('branch_settings', id=id))
    
    # Check access
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    staff_name = assignment.staff.name
    assignment.is_active = False
    db.session.commit()
    flash(f'{staff_name} removed from shift', 'success')
    return redirect(url_for('branch_settings', id=id))


@app.route('/api/branch/<int:id>/staff-without-shift')
@login_required
def get_staff_without_shift(id):
    """API to get staff not currently assigned to any shift"""
    school = School.query.get_or_404(id)
    
    # Check access
    if current_user.role not in ['super_admin', 'school_admin']:
        return jsonify({'error': 'Access denied'}), 403
    if current_user.role == 'school_admin' and school.id not in current_user.get_accessible_school_ids():
        return jsonify({'error': 'Access denied'}), 403
    
    # Get all active staff in this branch
    all_staff = Staff.query.filter_by(school_id=id, is_active=True).all()
    
    # Get staff with active shift assignments
    assigned_staff_ids = db.session.query(StaffShiftAssignment.staff_id).filter(
        StaffShiftAssignment.is_active == True
    ).distinct().all()
    assigned_ids = [s[0] for s in assigned_staff_ids]
    
    # Filter to staff without shifts
    unassigned = [s for s in all_staff if s.id not in assigned_ids]
    
    return jsonify({
        'staff': [{'id': s.id, 'name': s.name, 'staff_id': s.staff_id, 'department': s.department} for s in unassigned]
    })


# ==================== STAFF ====================

@app.route('/staff')
@login_required
def staff_list():
    organization_id = request.args.get('organization_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    
    # Get all organizations for filter dropdown (all roles can see this)
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = current_user.get_accessible_organizations()
    
    # Get branches based on organization filter or user access
    if organization_id:
        if current_user.role == 'super_admin':
            branches = School.query.filter_by(organization_id=organization_id).all()
        else:
            accessible_ids = current_user.get_accessible_school_ids()
            branches = School.query.filter(
                School.organization_id == organization_id,
                School.id.in_(accessible_ids)
            ).all()
    else:
        if current_user.role == 'super_admin':
            branches = School.query.all()
        else:
            branches = current_user.get_accessible_schools()
    
    # Get staff based on filters
    if current_user.role == 'super_admin':
        if organization_id:
            org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            if branch_id and branch_id in org_school_ids:
                staff = Staff.query.filter(Staff.school_id == branch_id).all()
            else:
                staff = Staff.query.filter(Staff.school_id.in_(org_school_ids)).all() if org_school_ids else []
        elif branch_id:
            staff = Staff.query.filter(Staff.school_id == branch_id).all()
        else:
            staff = Staff.query.all()
    else:
        accessible_school_ids = current_user.get_accessible_school_ids()
        if not accessible_school_ids:
            staff = []
        elif branch_id and branch_id in accessible_school_ids:
            staff = Staff.query.filter(Staff.school_id == branch_id).all()
        elif organization_id:
            org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            filtered_ids = [sid for sid in org_school_ids if sid in accessible_school_ids]
            staff = Staff.query.filter(Staff.school_id.in_(filtered_ids)).all() if filtered_ids else []
        else:
            staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()
    
    # Get all schools for modals (add/edit staff)
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    return render_template('staff.html', 
        staff=staff,
        schools=schools,
        organizations=organizations,
        branches=branches,
        selected_organization=organization_id,
        selected_branch=branch_id
    )


@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        department = request.form.get('department')
        school_id = request.form.get('school_id')
        email = request.form.get('email', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        photo_url = request.form.get('photo_url', '').strip() or None
        if current_user.role == 'school_admin':
            if current_user.allowed_schools:
                school_id = current_user.allowed_schools[0].id
            elif current_user.school_id:
                school_id = current_user.school_id
            else:
                flash('No branch assigned to your account!', 'danger')
                return redirect(url_for('staff_list'))
        if not school_id:
            flash('Please select a branch!', 'danger')
            return redirect(url_for('add_staff'))
        try:
            school_id = int(school_id)
        except (ValueError, TypeError):
            flash('Invalid branch selected!', 'danger')
            return redirect(url_for('add_staff'))
        existing = check_staff_id_exists_in_org(staff_id, school_id)
        if existing:
            flash('Staff ID already exists in this organization!', 'danger')
            return redirect(url_for('add_staff'))
        staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id, email=email, phone=phone, photo_url=photo_url)
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = []
    departments = ['Academic', 'Non-Academic', 'Administrative', 'Support Staff']
    return render_template('add_staff.html', schools=schools, organizations=organizations, departments=departments)


@app.route('/staff/edit/<int:id>', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin' and staff.school_id not in current_user.get_accessible_school_ids():
        flash('You do not have permission to edit this staff.', 'danger')
        return redirect(url_for('staff_list'))
    new_staff_id = request.form.get('staff_id')
    new_school_id = request.form.get('school_id')
    try:
        new_school_id = int(new_school_id)
    except (ValueError, TypeError):
        flash('Invalid branch selected!', 'danger')
        return redirect(url_for('staff_list'))
    if new_staff_id != staff.staff_id:
        existing = check_staff_id_exists_in_org(new_staff_id, new_school_id, exclude_staff_id=id)
        if existing:
            flash('Staff ID already exists in this organization!', 'danger')
            return redirect(url_for('staff_list'))
    staff.staff_id = new_staff_id
    staff.name = request.form.get('name')
    staff.department = request.form.get('department')
    staff.school_id = new_school_id
    staff.is_active = request.form.get('is_active') == 'true'
    staff.email = request.form.get('email', '').strip() or None
    staff.phone = request.form.get('phone', '').strip() or None
    staff.photo_url = request.form.get('photo_url', '').strip() or None
    db.session.commit()
    flash(f'Staff "{staff.name}" updated successfully!', 'success')
    return redirect(url_for('staff_list'))


@app.route('/staff/toggle/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin' and staff.school_id not in current_user.get_accessible_school_ids():
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


@app.route('/staff/download-csv')
@login_required
def download_staff_csv():
    if current_user.role not in ['super_admin', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    if current_user.role == 'super_admin':
        staff = Staff.query.join(School).join(Organization).order_by(Organization.name, School.name, Staff.name).all()
    else:
        allowed_school_ids = [s.id for s in current_user.allowed_schools]
        staff = Staff.query.filter(Staff.school_id.in_(allowed_school_ids)).order_by(Staff.name).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Email', 'Phone', 'Status', 'Current Shift'])
    for s in staff:
        current_shift = get_staff_current_shift(s)
        shift_name = current_shift.name if current_shift else 'Regular Schedule'
        writer.writerow([s.staff_id, s.name, s.school.organization.name if s.school and s.school.organization else '', s.school.name if s.school else '', s.department or '', s.email or '', s.phone or '', 'Active' if s.is_active else 'Inactive', shift_name])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=staff_list.csv'})


@app.route('/staff/download-template')
@login_required
@role_required('super_admin', 'school_admin')
def download_staff_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['staff_id', 'name', 'department', 'email', 'phone', 'photo_url'])
    writer.writerow(['001', 'John Doe', 'Academic', 'john@example.com', '08012345678', 'https://example.com/photo.jpg'])
    writer.writerow(['002', 'Jane Smith', 'Administrative', 'jane@example.com', '08098765432', ''])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=staff_upload_template.csv'})


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
            if current_user.allowed_schools:
                school_id = current_user.allowed_schools[0].id
            elif current_user.school_id:
                school_id = current_user.school_id
            else:
                flash('No branch assigned to your account!', 'danger')
                return redirect(url_for('staff_list'))
        try:
            school_id = int(school_id)
        except (ValueError, TypeError):
            flash('Invalid branch selected!', 'danger')
            return redirect(url_for('bulk_upload'))
        school = School.query.get(school_id)
        if not school:
            flash('Branch not found!', 'danger')
            return redirect(url_for('bulk_upload'))
        valid_departments = []
        if school.organization_id:
            valid_departments = [d.name for d in Department.query.filter_by(organization_id=school.organization_id).all()]
        if not valid_departments:
            valid_departments = ['Academic', 'Non-Academic', 'Administrative', 'Support Staff']
        if school.organization_id:
            org_branch_ids = [s.id for s in School.query.filter_by(organization_id=school.organization_id).all()]
        else:
            org_branch_ids = [school_id]
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            added = 0
            skipped = 0
            errors = []
            for row_num, row in enumerate(reader, start=2):
                row_staff_id = row.get('staff_id', '').strip()
                name = row.get('name', '').strip()
                department = row.get('department', '').strip()
                email = row.get('email', '').strip() or None
                phone = row.get('phone', '').strip() or None
                photo_url = row.get('photo_url', '').strip() or None
                if not row_staff_id or not name:
                    errors.append(f"Row {row_num}: Missing staff_id or name")
                    skipped += 1
                    continue
                existing = Staff.query.filter(Staff.staff_id == row_staff_id, Staff.school_id.in_(org_branch_ids)).first()
                if existing:
                    errors.append(f"Row {row_num}: Staff ID '{row_staff_id}' already exists")
                    skipped += 1
                    continue
                if department not in valid_departments:
                    department = valid_departments[0] if valid_departments else 'Academic'
                staff = Staff(staff_id=row_staff_id, name=name, department=department, school_id=school_id, email=email, phone=phone, photo_url=photo_url)
                db.session.add(staff)
                added += 1
            db.session.commit()
            if errors:
                flash(f'Bulk upload complete! Added: {added}, Skipped: {skipped}. Errors: {"; ".join(errors[:5])}{"..." if len(errors) > 5 else ""}', 'warning')
            else:
                flash(f'Bulk upload complete! Added: {added}, Skipped: {skipped}', 'success')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
        return redirect(url_for('staff_list'))
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = []
    return render_template('bulk_upload.html', schools=schools, organizations=organizations)
# ==================== USERS ====================

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    all_users = User.query.all()
    schools = School.query.all()
    return render_template('users.html', users=all_users, schools=schools)


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


@app.route('/users/edit/<int:id>', methods=['POST'])
@login_required
@role_required('super_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    if user.username == 'admin':
        flash('Cannot edit the default admin account', 'danger')
        return redirect(url_for('users'))
    user.username = request.form.get('username')
    user.role = request.form.get('role')
    user.is_active = 'is_active' in request.form
    new_password = request.form.get('password')
    if new_password and new_password.strip():
        user.set_password(new_password)
    user.allowed_schools = []
    if user.role == 'school_admin':
        school_ids = request.form.getlist('allowed_schools')
        if school_ids:
            for school_id in school_ids:
                school = School.query.get(int(school_id))
                if school:
                    user.allowed_schools.append(school)
    db.session.commit()
    flash('User updated successfully', 'success')
    return redirect(url_for('users'))


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


# ==================== HR QUERY SYSTEM ====================

@app.route('/query-templates')
@login_required
@role_required('super_admin', 'hr_viewer', 'school_admin')
def query_templates():
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        templates = QueryTemplate.query.filter_by(is_active=True).all()
    else:
        organizations = current_user.get_accessible_organizations()
        org_ids = [o.id for o in organizations]
        templates = QueryTemplate.query.filter(QueryTemplate.organization_id.in_(org_ids), QueryTemplate.is_active == True).all() if org_ids else []
    return render_template('query_templates.html', templates=templates, organizations=organizations)


@app.route('/query-templates/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'hr_viewer', 'school_admin')
def add_query_template():
    if request.method == 'POST':
        organization_id = request.form.get('organization_id')
        title = request.form.get('title')
        subject = request.form.get('subject')
        body = request.form.get('body')
        from_email = request.form.get('from_email', '').strip() or None
        
        if not all([organization_id, title, subject, body]):
            flash('All fields are required!', 'danger')
            return redirect(url_for('add_query_template'))
        
        template = QueryTemplate(
            organization_id=organization_id, 
            title=title, 
            subject=subject, 
            body=body, 
            from_email=from_email,
            created_by=current_user.id
        )
        db.session.add(template)
        db.session.commit()
        flash('Query template added successfully!', 'success')
        return redirect(url_for('query_templates'))
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = current_user.get_accessible_organizations()
    return render_template('add_query_template.html', organizations=organizations)


@app.route('/query-templates/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'hr_viewer', 'school_admin')
def edit_query_template(id):
    template = QueryTemplate.query.get_or_404(id)
    
    if request.method == 'POST':
        template.organization_id = request.form.get('organization_id')
        template.title = request.form.get('title')
        template.subject = request.form.get('subject')
        template.body = request.form.get('body')
        template.from_email = request.form.get('from_email', '').strip() or None
        db.session.commit()
        flash('Query template updated successfully!', 'success')
        return redirect(url_for('query_templates'))
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = current_user.get_accessible_organizations()
    
    return render_template('edit_query_template.html', template=template, organizations=organizations)


@app.route('/query-templates/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_query_template(id):
    template = QueryTemplate.query.get_or_404(id)
    template.is_active = False
    db.session.commit()
    flash('Query template deleted successfully!', 'success')
    return redirect(url_for('query_templates'))


@app.route('/queries/send', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin', 'hr_viewer')
def send_query():
    if request.method == 'POST':
        staff_ids = request.form.getlist('staff_ids')
        template_id = request.form.get('template_id')
        
        # Get period info from form
        period_start = request.form.get('period_start', '')
        period_end = request.form.get('period_end', '')
        
        # Build period string
        if period_start and period_end:
            try:
                start_dt = datetime.strptime(period_start, '%Y-%m-%d')
                end_dt = datetime.strptime(period_end, '%Y-%m-%d')
                period_str = f"{start_dt.strftime('%d/%m/%Y')} to {end_dt.strftime('%d/%m/%Y')}"
            except:
                period_str = f"{period_start} to {period_end}"
        else:
            period_str = "All Time"
        
        if not staff_ids:
            flash('Please select at least one staff member!', 'danger')
            return redirect(url_for('send_query'))
        if not template_id:
            flash('Please select a query template!', 'danger')
            return redirect(url_for('send_query'))
        
        template = QueryTemplate.query.get(template_id)
        if not template:
            flash('Invalid template!', 'danger')
            return redirect(url_for('send_query'))
        
        success_count = 0
        fail_count = 0
        no_email_count = 0
        
        for staff_id in staff_ids:
            staff = Staff.query.get(staff_id)
            if not staff:
                continue
            
            # Get the late count from the form (passed as hidden field)
            staff_late_count = request.form.get(f'late_count_{staff_id}', type=int)
            if staff_late_count is None:
                staff_late_count = staff.times_late
            
            if not staff.email:
                no_email_count += 1
                query_record = StaffQuery(
                    staff_id=staff.id, 
                    template_id=template.id, 
                    sent_by=current_user.id, 
                    times_late_at_query=staff_late_count, 
                    email_status='no_email'
                )
                db.session.add(query_record)
                continue
            
            organization = template.organization
            success, message = send_query_email(staff, template, organization, current_user, staff_late_count, period_str)
            
            query_record = StaffQuery(
                staff_id=staff.id, 
                template_id=template.id, 
                sent_by=current_user.id, 
                times_late_at_query=staff_late_count, 
                email_status='sent' if success else 'failed'
            )
            db.session.add(query_record)
            
            if success:
                success_count += 1
            else:
                fail_count += 1
        
        db.session.commit()
        
        if success_count > 0:
            flash(f'Successfully sent {success_count} query email(s)!', 'success')
        if fail_count > 0:
            flash(f'{fail_count} email(s) failed to send.', 'warning')
        if no_email_count > 0:
            flash(f'{no_email_count} staff member(s) have no email address (query recorded).', 'info')
        
        return redirect(url_for('query_tracking'))
    
    # GET request - show the send query page
    accessible_school_ids = current_user.get_accessible_school_ids()
    organization_id = request.args.get('organization_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    period = request.args.get('period', 'all')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    
    # Calculate date range based on period
    today = date.today()
    
    if period == 'today':
        start_date = today
        end_date = today
    elif period == '7days':
        start_date = today - timedelta(days=7)
        end_date = today
    elif period == '14days':
        start_date = today - timedelta(days=14)
        end_date = today
    elif period == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = today - timedelta(days=today.weekday() + 1)
    elif period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'last_month':
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif period == 'custom' and start_date_param and end_date_param:
        try:
            start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
        except:
            start_date = None
            end_date = today
    else:
        start_date = None
        end_date = today
    
    # Build staff query
    staff_query = Staff.query.filter(Staff.is_active == True, Staff.department != 'Management')
    
    # Filter by organization
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if branch_id and branch_id in org_school_ids:
            staff_query = staff_query.filter(Staff.school_id == branch_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids))
    elif current_user.role != 'super_admin' and accessible_school_ids:
        if branch_id and branch_id in accessible_school_ids:
            staff_query = staff_query.filter(Staff.school_id == branch_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    elif branch_id:
        staff_query = staff_query.filter(Staff.school_id == branch_id)
    
    all_staff = staff_query.all()
    
    # Calculate late counts based on period
    late_staff = []
    for s in all_staff:
        if start_date:
            period_late_count = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date,
                Attendance.is_late == True
            ).count()
        else:
            period_late_count = s.times_late
        
        if period_late_count > 0:
            late_staff.append({
                'staff': s,
                'late_count': period_late_count,
                'total_late': s.times_late
            })
    
    # Sort by late count descending
    late_staff.sort(key=lambda x: x['late_count'], reverse=True)
    
    # Get organizations and branches for filters
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        if organization_id:
            branches = School.query.filter_by(organization_id=organization_id).all()
            templates = QueryTemplate.query.filter_by(organization_id=organization_id, is_active=True).all()
        else:
            branches = School.query.all()
            templates = QueryTemplate.query.filter_by(is_active=True).all()
    else:
        organizations = current_user.get_accessible_organizations()
        org_ids = [o.id for o in organizations]
        if organization_id and organization_id in org_ids:
            branches = School.query.filter(School.organization_id == organization_id, School.id.in_(accessible_school_ids)).all()
            templates = QueryTemplate.query.filter_by(organization_id=organization_id, is_active=True).all()
        else:
            branches = current_user.get_accessible_schools()
            templates = QueryTemplate.query.filter(QueryTemplate.organization_id.in_(org_ids), QueryTemplate.is_active == True).all() if org_ids else []
    
    return render_template('send_query.html', 
        late_staff=late_staff, 
        templates=templates, 
        organizations=organizations,
        branches=branches,
        selected_organization=organization_id,
        selected_branch=branch_id,
        selected_period=period,
        start_date=start_date_param or (start_date.strftime('%Y-%m-%d') if start_date else ''),
        end_date=end_date_param or end_date.strftime('%Y-%m-%d')
    )


@app.route('/queries/tracking')
@login_required
@role_required('super_admin', 'hr_viewer', 'school_admin')
def query_tracking():
    accessible_school_ids = current_user.get_accessible_school_ids()
    organization_id = request.args.get('organization_id', type=int)
    if current_user.role == 'super_admin':
        if organization_id:
            org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            staff_with_queries = db.session.query(Staff, db.func.count(StaffQuery.id).label('query_count')).outerjoin(StaffQuery).filter(Staff.school_id.in_(org_school_ids)).group_by(Staff.id).having(db.func.count(StaffQuery.id) > 0).order_by(db.desc('query_count')).all()
        else:
            staff_with_queries = db.session.query(Staff, db.func.count(StaffQuery.id).label('query_count')).outerjoin(StaffQuery).group_by(Staff.id).having(db.func.count(StaffQuery.id) > 0).order_by(db.desc('query_count')).all()
        organizations = Organization.query.all()
    else:
        staff_with_queries = db.session.query(Staff, db.func.count(StaffQuery.id).label('query_count')).outerjoin(StaffQuery).filter(Staff.school_id.in_(accessible_school_ids)).group_by(Staff.id).having(db.func.count(StaffQuery.id) > 0).order_by(db.desc('query_count')).all() if accessible_school_ids else []
        organizations = current_user.get_accessible_organizations()
    recent_queries = StaffQuery.query.order_by(StaffQuery.sent_at.desc()).limit(50).all()
    return render_template('query_tracking.html', staff_with_queries=staff_with_queries, recent_queries=recent_queries, organizations=organizations, selected_organization=organization_id)


@app.route('/queries/staff/<int:staff_id>')
@login_required
@role_required('super_admin', 'hr_viewer', 'school_admin')
def staff_query_history(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    queries = StaffQuery.query.filter_by(staff_id=staff_id).order_by(StaffQuery.sent_at.desc()).all()
    return render_template('staff_query_history.html', staff=staff, queries=queries)


# ==================== REPORTS ====================

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')


@app.route('/reports/attendance')
@login_required
def attendance_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        else:
            staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(org_school_ids)).all()] if org_school_ids else []
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = current_user.get_accessible_organizations()
    return render_template('attendance_report.html', attendance=attendance, schools=schools, organizations=organizations, date_from=date_from, date_to=date_to, school_id=school_id, organization_id=organization_id, today=today.isoformat())


@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        else:
            staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(org_school_ids)).all()] if org_school_ids else []
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Shift', 'Sign In', 'Sign Out', 'Status', 'Late Duration', 'Overtime Duration'])
    for a in attendance:
        # Get shift info
        current_shift = get_staff_current_shift(a.staff)
        shift_name = current_shift.name if current_shift else 'Regular'
        
        if a.staff.department == 'Management':
            status = 'Signed In'
            late_formatted = '-'
        else:
            late_formatted = format_minutes_to_hours(a.late_minutes) if a.is_late else 'On Time'
            status = f'Late ({late_formatted})' if a.is_late else 'On Time'
        overtime_formatted = format_minutes_to_hours(a.overtime_minutes)
        writer.writerow([a.date.strftime('%d/%m/%Y'), a.staff.staff_id, a.staff.name, a.staff.school.organization.name if a.staff.school and a.staff.school.organization else '', a.staff.school.short_name or a.staff.school.name if a.staff.school else '', a.staff.department, shift_name, a.sign_in_time.strftime('%H:%M') if a.sign_in_time else '', a.sign_out_time.strftime('%H:%M') if a.sign_out_time else '', status, late_formatted, overtime_formatted])
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
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_query = staff_query.filter_by(school_id=school_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids)) if org_school_ids else staff_query.filter(False)
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    late_staff = []
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(Attendance.staff_id == s.id, Attendance.date >= start_date, Attendance.date <= end_date)
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
            
            # Get shift info
            current_shift = get_staff_current_shift(s)
            shift_name = current_shift.name if current_shift else None
            
            late_staff.append({
                'staff': s, 
                'times_late': times_late, 
                'punctuality': punctuality, 
                'lateness': lateness,
                'shift': shift_name
            })
    late_staff.sort(key=lambda x: x['times_late'], reverse=True)
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = current_user.get_accessible_organizations()
    return render_template('late_report.html', late_staff=late_staff, schools=schools, organizations=organizations, date_from=date_from, date_to=date_to, school_id=school_id, organization_id=organization_id, calc_mode=calc_mode, show_toggle=show_toggle, today=today.isoformat())


@app.route('/reports/late/download')
@login_required
def download_late_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_query = staff_query.filter_by(school_id=school_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids)) if org_school_ids else staff_query.filter(False)
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Shift', 'Times Late', '% Punctuality', '% Lateness'])
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(Attendance.staff_id == s.id, Attendance.date >= start_date, Attendance.date <= end_date)
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
            
            # Get shift info
            current_shift = get_staff_current_shift(s)
            shift_name = current_shift.name if current_shift else 'Regular'
            
            writer.writerow([s.staff_id, s.name, s.school.organization.name if s.school and s.school.organization else '', s.school.short_name or s.school.name if s.school else '', s.department, shift_name, times_late, punctuality, lateness])
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
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_query = staff_query.filter_by(school_id=school_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids)) if org_school_ids else staff_query.filter(False)
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    absent_records = []
    current_date = start_date
    while current_date <= end_date:
        for s in all_staff:
            if s.department == 'Management':
                continue
            # Check if this is a work day for the staff's branch
            if not is_work_day(s.school, current_date):
                continue
            attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
            if not attendance:
                # Get shift info
                current_shift = get_staff_current_shift(s)
                shift_name = current_shift.name if current_shift else None
                absent_records.append({
                    'date': current_date, 
                    'staff': s,
                    'shift': shift_name
                })
        current_date += timedelta(days=1)
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = current_user.get_accessible_organizations()
    return render_template('absent_report.html', absent_records=absent_records, schools=schools, organizations=organizations, date_from=date_from, date_to=date_to, school_id=school_id, organization_id=organization_id, today=today.isoformat())


@app.route('/reports/absent/download')
@login_required
def download_absent_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
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
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_query = staff_query.filter_by(school_id=school_id)
        else:
            staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids)) if org_school_ids else staff_query.filter(False)
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Shift'])
    current_date = start_date
    while current_date <= end_date:
        for s in all_staff:
            if s.department == 'Management':
                continue
            # Check if this is a work day for the staff's branch
            if not is_work_day(s.school, current_date):
                continue
            attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
            if not attendance:
                # Get shift info
                current_shift = get_staff_current_shift(s)
                shift_name = current_shift.name if current_shift else 'Regular'
                writer.writerow([current_date.strftime('%d/%m/%Y'), s.staff_id, s.name, s.school.organization.name if s.school and s.school.organization else '', s.school.short_name or s.school.name if s.school else '', s.department, shift_name])
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
    organization_id = request.args.get('organization_id', '')
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
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.overtime_minutes > 0)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        else:
            staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(org_school_ids)).all()] if org_school_ids else []
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    overtime = query.order_by(Attendance.date.desc()).all()
    if current_user.role == 'super_admin':
        schools = School.query.all()
        organizations = Organization.query.all()
    else:
        schools = current_user.get_accessible_schools()
        organizations = current_user.get_accessible_organizations()
    return render_template('overtime_report.html', overtime=overtime, schools=schools, organizations=organizations, date_from=date_from, date_to=date_to, school_id=school_id, organization_id=organization_id, today=today.isoformat(), format_minutes=format_minutes_to_hours)


@app.route('/reports/overtime/download')
@login_required
def download_overtime_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
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
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.overtime_minutes > 0)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        if school_id:
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        else:
            staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(org_school_ids)).all()] if org_school_ids else []
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    overtime = query.order_by(Attendance.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Shift', 'Sign Out', 'Overtime'])
    for o in overtime:
        # Get shift info
        current_shift = get_staff_current_shift(o.staff)
        shift_name = current_shift.name if current_shift else 'Regular'
        writer.writerow([o.date.strftime('%d/%m/%Y'), o.staff.staff_id, o.staff.name, o.staff.school.organization.name if o.staff.school and o.staff.school.organization else '', o.staff.school.short_name or o.staff.school.name if o.staff.school else '', o.staff.department, shift_name, o.sign_out_time.strftime('%H:%M') if o.sign_out_time else '', format_minutes_to_hours(o.overtime_minutes)])
    output.seek(0)
    filename = f'overtime_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})
# ==================== ANALYTICS ====================

@app.route('/reports/analytics')
@login_required
def analytics():
    period = request.args.get('period', '30')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
    department_filter = request.args.get('department', '')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    
    today = date.today()
    
    if period == 'today':
        start_date = today
        end_date = today
        period_days = 1
    elif period == 'custom' and start_date_param and end_date_param:
        try:
            start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
            period_days = (end_date - start_date).days + 1
        except:
            start_date = today - timedelta(days=30)
            end_date = today
            period_days = 30
    elif period == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
        period_days = (end_date - start_date).days + 1
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = today - timedelta(days=today.weekday() + 1)
        period_days = 7
    elif period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
        period_days = (end_date - start_date).days + 1
    elif period == 'last_month':
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
        period_days = (end_date - start_date).days + 1
    else:
        try:
            period_days = int(period)
        except:
            period_days = 30
        start_date = today - timedelta(days=period_days)
        end_date = today
    
    previous_start = start_date - timedelta(days=period_days)
    accessible_school_ids = current_user.get_accessible_school_ids()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    organizations = current_user.get_accessible_organizations()
    
    if organization_id:
        departments = [d.name for d in Department.query.filter_by(organization_id=organization_id).all()]
    else:
        all_depts = set()
        for org in organizations:
            for dept in Department.query.filter_by(organization_id=org.id).all():
                all_depts.add(dept.name)
        departments = sorted(list(all_depts)) if all_depts else ['Academic', 'Non-Academic', 'Administrative', 'Support Staff']
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids))
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    
    if department_filter:
        staff_query = staff_query.filter_by(department=department_filter)
    
    all_staff = staff_query.all()
    staff_ids = [s.id for s in all_staff]
    
    current_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all() if staff_ids else []
    
    previous_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= previous_start,
        Attendance.date < start_date
    ).all() if staff_ids else []
    
    total_staff = len(all_staff)
    branch_count = len(set(s.school_id for s in all_staff)) if all_staff else 0
    total_records = len(current_attendance)
    
    # Calculate working days based on each staff's work schedule
    working_days = 0
    for i in range(period_days):
        check_date = start_date + timedelta(days=i)
        for s in all_staff[:1]:
            if s.school and is_work_day(s.school, check_date):
                working_days += 1
                break
    
    if working_days == 0:
        working_days = sum(1 for i in range(period_days) if (start_date + timedelta(days=i)).weekday() < 5)
    
    expected_attendance = total_staff * working_days if total_staff > 0 else 1
    
    attendance_rate = round((total_records / expected_attendance) * 100, 1) if expected_attendance > 0 and total_records > 0 else 0
    attendance_rate = min(attendance_rate, 100)
    
    prev_working_days = sum(1 for i in range(period_days) if (previous_start + timedelta(days=i)).weekday() < 5)
    prev_expected = total_staff * prev_working_days if total_staff > 0 else 1
    prev_attendance_rate = round((len(previous_attendance) / prev_expected) * 100, 1) if prev_expected > 0 and len(previous_attendance) > 0 else 0
    prev_attendance_rate = min(prev_attendance_rate, 100)
    
    attendance_trend = round(attendance_rate - prev_attendance_rate, 1)
    
    on_time_count = sum(1 for a in current_attendance if not a.is_late)
    late_count = sum(1 for a in current_attendance if a.is_late)
    punctuality_rate = round((on_time_count / total_records) * 100, 1) if total_records > 0 else 0
    
    prev_on_time = sum(1 for a in previous_attendance if not a.is_late)
    prev_punctuality = round((prev_on_time / len(previous_attendance)) * 100, 1) if len(previous_attendance) > 0 else 0
    punctuality_trend = round(punctuality_rate - prev_punctuality, 1)
    
    total_late_minutes = sum(a.late_minutes for a in current_attendance if a.is_late)
    avg_late_minutes = round(total_late_minutes / late_count, 1) if late_count > 0 else 0
    
    total_overtime_minutes = sum(a.overtime_minutes for a in current_attendance)
    overtime_hours = total_overtime_minutes // 60
    overtime_mins = total_overtime_minutes % 60
    
    trend_labels = []
    trend_data = []
    punctuality_data = []
    
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            day_attendance = [a for a in current_attendance if a.date == current_date]
            day_count = len(day_attendance)
            day_rate = round((day_count / total_staff) * 100, 1) if total_staff > 0 else 0
            day_on_time = sum(1 for a in day_attendance if not a.is_late)
            day_punctuality = round((day_on_time / day_count) * 100, 1) if day_count > 0 else 0
            trend_labels.append(current_date.strftime('%d %b'))
            trend_data.append(min(day_rate, 100))
            punctuality_data.append(day_punctuality)
        current_date += timedelta(days=1)
    
    late_by_day = [0, 0, 0, 0, 0, 0, 0]
    for a in current_attendance:
        if a.is_late:
            late_by_day[a.date.weekday()] += 1
    
    absent_by_day = [0, 0, 0, 0, 0, 0, 0]
    non_mgmt_staff = [s for s in all_staff if s.department != 'Management']
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            for s in non_mgmt_staff:
                has_attendance = any(a.date == current_date and a.staff_id == s.id for a in current_attendance)
                if not has_attendance:
                    absent_by_day[current_date.weekday()] += 1
        current_date += timedelta(days=1)
    
    peak_late_hours = {'08:00-08:15': 0, '08:15-08:30': 0, '08:30-08:45': 0, '08:45-09:00': 0, '09:00-09:30': 0, '09:30+': 0}
    for a in current_attendance:
        if a.is_late and a.sign_in_time:
            total_minutes = a.sign_in_time.hour * 60 + a.sign_in_time.minute
            if total_minutes < 8 * 60 + 15:
                peak_late_hours['08:00-08:15'] += 1
            elif total_minutes < 8 * 60 + 30:
                peak_late_hours['08:15-08:30'] += 1
            elif total_minutes < 8 * 60 + 45:
                peak_late_hours['08:30-08:45'] += 1
            elif total_minutes < 9 * 60:
                peak_late_hours['08:45-09:00'] += 1
            elif total_minutes < 9 * 60 + 30:
                peak_late_hours['09:00-09:30'] += 1
            else:
                peak_late_hours['09:30+'] += 1
    
    peak_late_labels = list(peak_late_hours.keys())
    peak_late_data = list(peak_late_hours.values())
    
    department_labels = []
    department_data = []
    for dept in departments:
        dept_staff = [s for s in all_staff if s.department == dept]
        if dept_staff:
            dept_staff_ids = [s.id for s in dept_staff]
            dept_attendance = [a for a in current_attendance if a.staff_id in dept_staff_ids]
            dept_on_time = sum(1 for a in dept_attendance if not a.is_late)
            dept_punctuality = round((dept_on_time / len(dept_attendance)) * 100) if dept_attendance else 0
            department_labels.append(dept)
            department_data.append(dept_punctuality)
    
    branch_labels = []
    branch_attendance = []
    branch_punctuality = []
    for school in schools[:10]:
        school_staff = [s for s in all_staff if s.school_id == school.id]
        if school_staff:
            school_staff_ids = [s.id for s in school_staff]
            school_att = [a for a in current_attendance if a.staff_id in school_staff_ids]
            school_expected = len(school_staff) * working_days if school_staff else 1
            school_rate = round((len(school_att) / school_expected) * 100, 1) if school_expected > 0 and len(school_att) > 0 else 0
            school_on_time = sum(1 for a in school_att if not a.is_late)
            school_punct = round((school_on_time / len(school_att)) * 100, 1) if school_att else 0
            branch_labels.append(school.short_name or school.name[:15])
            branch_attendance.append(min(school_rate, 100))
            branch_punctuality.append(school_punct)
    
    top_performers = []
    needs_attention = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = [a for a in current_attendance if a.staff_id == s.id]
        if len(staff_attendance) >= 3:
            on_time = sum(1 for a in staff_attendance if not a.is_late)
            punctuality = round((on_time / len(staff_attendance)) * 100, 1)
            top_performers.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'punctuality': punctuality})
        late_cnt = sum(1 for a in staff_attendance if a.is_late)
        if late_cnt > 0:
            needs_attention.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'late_count': late_cnt})
    
    top_performers.sort(key=lambda x: x['punctuality'], reverse=True)
    top_performers = top_performers[:5]
    needs_attention.sort(key=lambda x: x['late_count'], reverse=True)
    needs_attention = needs_attention[:5]
    
    distribution_labels = ['On Time', 'Late']
    distribution_data = [on_time_count, late_count]
    
    total_expected = total_staff * working_days
    total_absent = total_expected - total_records if total_expected > total_records else 0
    presence_labels = ['Present', 'Absent']
    presence_data = [total_records, total_absent]
    
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)
    
    this_week_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= this_week_start,
        Attendance.date <= today
    ).all() if staff_ids else []
    
    last_week_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= last_week_start,
        Attendance.date <= last_week_end
    ).all() if staff_ids else []
    
    weekly_comparison_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    weekly_this_week = []
    weekly_last_week = []
    
    for day_idx in range(5):
        this_day = this_week_start + timedelta(days=day_idx)
        this_day_att = len([a for a in this_week_attendance if a.date == this_day])
        this_day_rate = round((this_day_att / total_staff) * 100, 1) if total_staff > 0 else 0
        weekly_this_week.append(min(this_day_rate, 100))
        
        last_day = last_week_start + timedelta(days=day_idx)
        last_day_att = len([a for a in last_week_attendance if a.date == last_day])
        last_day_rate = round((last_day_att / total_staff) * 100, 1) if total_staff > 0 else 0
        weekly_last_week.append(min(last_day_rate, 100))
    
    early_arrivals = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_att = [a for a in current_attendance if a.staff_id == s.id and a.sign_in_time and not a.is_late]
        if len(staff_att) >= 3:
            early_mins_list = []
            for a in staff_att:
                if a.sign_in_time and s.school:
                    start_time, end_time, grace_mins, is_shift = get_staff_schedule_for_date(s, a.date)
                    if start_time:
                        scheduled = datetime.strptime(start_time, '%H:%M').time()
                        actual = a.sign_in_time.time()
                        if actual < scheduled:
                            delta = datetime.combine(a.date, scheduled) - datetime.combine(a.date, actual)
                            early_mins_list.append(int(delta.total_seconds() / 60))
            if early_mins_list:
                avg_early = round(sum(early_mins_list) / len(early_mins_list), 0)
                early_arrivals.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'avg_early_mins': int(avg_early)})
    
    early_arrivals.sort(key=lambda x: x['avg_early_mins'], reverse=True)
    early_arrivals = early_arrivals[:5]
    
    perfect_attendance = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_att = [a for a in current_attendance if a.staff_id == s.id]
        staff_on_time = [a for a in staff_att if not a.is_late]
        if len(staff_att) >= working_days and len(staff_on_time) == len(staff_att) and len(staff_att) > 0:
            perfect_attendance.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'days': len(staff_att)})
    
    perfect_attendance.sort(key=lambda x: x['days'], reverse=True)
    perfect_attendance = perfect_attendance[:5]
    
    most_improved = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        current_late = sum(1 for a in current_attendance if a.staff_id == s.id and a.is_late)
        prev_late = sum(1 for a in previous_attendance if a.staff_id == s.id and a.is_late)
        if prev_late > current_late and prev_late > 0:
            reduction = prev_late - current_late
            most_improved.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'reduction': reduction})
    
    most_improved.sort(key=lambda x: x['reduction'], reverse=True)
    most_improved = most_improved[:5]
    
    attendance_streaks = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_att = sorted([a for a in current_attendance if a.staff_id == s.id], key=lambda x: x.date, reverse=True)
        streak = 0
        for a in staff_att:
            if not a.is_late:
                streak += 1
            else:
                break
        if streak >= 3:
            attendance_streaks.append({'name': s.name, 'branch': s.school.short_name or s.school.name if s.school else 'N/A', 'streak': streak})
    
    attendance_streaks.sort(key=lambda x: x['streak'], reverse=True)
    attendance_streaks = attendance_streaks[:5]
    
    return render_template('analytics.html',
        schools=schools, organizations=organizations, departments=departments,
        selected_school_id=school_id, selected_organization_id=organization_id, selected_department=department_filter,
        period=period, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'),
        attendance_rate=attendance_rate, attendance_trend=attendance_trend,
        punctuality_rate=punctuality_rate, punctuality_trend=punctuality_trend,
        total_staff=total_staff, branch_count=branch_count, total_records=total_records,
        on_time_count=on_time_count, late_count=late_count, avg_late_minutes=avg_late_minutes,
        overtime_hours=overtime_hours, overtime_mins=overtime_mins,
        trend_labels=trend_labels, trend_data=trend_data, punctuality_data=punctuality_data,
        late_by_day=late_by_day, absent_by_day=absent_by_day,
        peak_late_labels=peak_late_labels, peak_late_data=peak_late_data,
        department_labels=department_labels, department_data=department_data,
        branch_labels=branch_labels, branch_attendance=branch_attendance, branch_punctuality=branch_punctuality,
        top_performers=top_performers, needs_attention=needs_attention,
        distribution_labels=distribution_labels, distribution_data=distribution_data,
        presence_labels=presence_labels, presence_data=presence_data,
        weekly_comparison_labels=weekly_comparison_labels, weekly_this_week=weekly_this_week, weekly_last_week=weekly_last_week,
        early_arrivals=early_arrivals, perfect_attendance=perfect_attendance,
        most_improved=most_improved, attendance_streaks=attendance_streaks
    )


@app.route('/reports/analytics/pdf')
@login_required
def analytics_pdf():
    today = date.today()
    period = request.args.get('period', '30')
    try:
        period_days = int(period)
    except:
        period_days = 30
    start_date = today - timedelta(days=period_days)
    end_date = today
    html = f"""
    <html>
    <head><style>body {{ font-family: Arial; }} h1 {{ color: #333; }}</style></head>
    <body>
        <h1>Analytics Report</h1>
        <p>Period: {start_date} to {end_date}</p>
        <p>Generated: {today}</p>
    </body>
    </html>
    """
    pdf_output = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=pdf_output)
    pdf_output.seek(0)
    return Response(pdf_output.getvalue(), mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename=analytics_{today}.pdf'})


# ==================== API ====================

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
    
    if action == 'get_staff' or (action is None and 'records' in data and len(data.get('records', [])) == 0):
        staff_list_data = get_staff_data_for_api(school)
        response = jsonify({
            'success': True, 
            'staff': staff_list_data, 
            'school': {
                'name': school.name, 
                'short_name': school.short_name or '', 
                'logo_url': school.logo_url or '',
                'shift_mode_enabled': school.shift_mode_enabled,
                'time_format_24h': school.time_format_24h,
                'work_days': school.work_days or 'mon,tue,wed,thu,fri'
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    if action == 'sync_attendance' or (action is None and 'records' in data):
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
                attendance = Attendance.query.filter_by(staff_id=staff.id, date=record_date).first()
                sign_in_time = record.get('sign_in_time') or record.get('timestamp')
                sign_out_time = record.get('sign_out_time')
                record_type = record.get('type', 'sign_in')
                
                if record_type == 'sign_in' or (sign_in_time and not attendance):
                    if not attendance:
                        if 'timestamp' in record:
                            sign_in_datetime = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
                        else:
                            sign_in_datetime = datetime.strptime(f"{record['date']} {sign_in_time}", '%Y-%m-%d %H:%M:%S')
                        
                        # Use new helper function for late calculation
                        is_late, late_minutes, scheduled_start = calculate_late_status(staff, sign_in_datetime, record_date)
                        
                        if is_late and staff.department != 'Management':
                            staff.times_late += 1
                        
                        attendance = Attendance(
                            staff_id=staff.id, 
                            date=record_date, 
                            sign_in_time=sign_in_datetime, 
                            is_late=is_late, 
                            late_minutes=late_minutes
                        )
                        db.session.add(attendance)
                        synced += 1
                
                if record_type == 'sign_out' or (sign_out_time and attendance and not attendance.sign_out_time):
                    if attendance and not attendance.sign_out_time:
                        if 'timestamp' in record:
                            sign_out_datetime = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
                        else:
                            sign_out_datetime = datetime.strptime(f"{record['date']} {sign_out_time}", '%Y-%m-%d %H:%M:%S')
                        
                        attendance.sign_out_time = sign_out_datetime
                        
                        # Use new helper function for overtime calculation
                        overtime_minutes = calculate_overtime(staff, sign_out_datetime, record_date)
                        attendance.overtime_minutes = overtime_minutes
                        
                        synced += 1
            except Exception as e:
                errors.append(str(e))
        
        db.session.commit()
        staff_list_data = get_staff_data_for_api(school)
        response = jsonify({
            'success': True, 
            'synced': synced, 
            'errors': errors, 
            'staff': staff_list_data, 
            'school': {
                'name': school.name, 
                'short_name': school.short_name or '', 
                'logo_url': school.logo_url or '',
                'shift_mode_enabled': school.shift_mode_enabled,
                'time_format_24h': school.time_format_24h,
                'work_days': school.work_days or 'mon,tue,wed,thu,fri'
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    if action == 'check_status':
        staff_id = data.get('staff_id')
        staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
        if not staff:
            response = jsonify({'error': 'Staff not found'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 404
        today_date = date.today()
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today_date).first()
        if attendance:
            status = 'signed_out' if attendance.sign_out_time else 'signed_in'
        else:
            status = 'not_signed_in'
        name_parts = staff.name.split(' ', 1)
        
        # Get shift info
        current_shift = get_staff_current_shift(staff)
        shift_info = None
        if current_shift:
            shift_info = {
                'name': current_shift.name,
                'start_time': format_time_display(current_shift.start_time, school.time_format_24h),
                'end_time': format_time_display(current_shift.end_time, school.time_format_24h)
            }
        
        response = jsonify({
            'staff_id': staff.staff_id, 
            'first_name': name_parts[0], 
            'last_name': name_parts[1] if len(name_parts) > 1 else '', 
            'name': staff.name, 
            'status': status,
            'shift': shift_info
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    if action == 'get_shifts':
        shifts = Shift.query.filter_by(school_id=school.id, is_active=True).all()
        shifts_data = []
        for shift in shifts:
            shifts_data.append({
                'id': shift.id,
                'name': shift.name,
                'start_time': format_time_display(shift.start_time, school.time_format_24h),
                'end_time': format_time_display(shift.end_time, school.time_format_24h),
                'grace_period_minutes': shift.grace_period_minutes
            })
        response = jsonify({
            'success': True,
            'shifts': shifts_data,
            'shift_mode_enabled': school.shift_mode_enabled
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    response = jsonify({'error': 'Invalid action'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 400


# ==================== INIT DB ====================

@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        try:
            db.session.execute(db.text('ALTER TABLE staff DROP CONSTRAINT IF EXISTS staff_staff_id_key'))
            db.session.commit()
        except:
            db.session.rollback()
        
        migrations = [
            'ALTER TABLE staff ADD COLUMN IF NOT EXISTS email VARCHAR(120)',
            'ALTER TABLE staff ADD COLUMN IF NOT EXISTS phone VARCHAR(20)',
            'ALTER TABLE staff ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500)',
            'ALTER TABLE organizations ADD COLUMN IF NOT EXISTS hr_email VARCHAR(120)',
            'ALTER TABLE organizations ADD COLUMN IF NOT EXISTS hr_email_name VARCHAR(100)',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS schedule_sat_start VARCHAR(5) DEFAULT \'08:00\'',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS schedule_sat_end VARCHAR(5) DEFAULT \'17:00\'',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS schedule_sun_start VARCHAR(5) DEFAULT \'08:00\'',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS schedule_sun_end VARCHAR(5) DEFAULT \'17:00\'',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS shift_mode_enabled BOOLEAN DEFAULT FALSE',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS time_format_24h BOOLEAN DEFAULT TRUE',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS work_days VARCHAR(50) DEFAULT \'mon,tue,wed,thu,fri\'',
            'ALTER TABLE schools ADD COLUMN IF NOT EXISTS grace_period_minutes INTEGER DEFAULT 0',
            'ALTER TABLE schools ALTER COLUMN work_days TYPE VARCHAR(50)',
            'ALTER TABLE shifts ADD COLUMN IF NOT EXISTS grace_period_minutes INTEGER DEFAULT 0',
            'ALTER TABLE shifts ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE',
            'ALTER TABLE shifts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
            'ALTER TABLE staff_shift_assignments ADD COLUMN IF NOT EXISTS effective_from DATE DEFAULT CURRENT_DATE',
            'ALTER TABLE staff_shift_assignments ADD COLUMN IF NOT EXISTS effective_to DATE',
            'ALTER TABLE staff_shift_assignments ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE',
            'ALTER TABLE staff_shift_assignments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        ]
        for sql in migrations:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
            except:
                db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS departments (
                id SERIAL PRIMARY KEY, 
                name VARCHAR(100) NOT NULL, 
                organization_id INTEGER NOT NULL REFERENCES organizations(id), 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('ALTER TABLE schools ADD COLUMN organization_id INTEGER'))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('ALTER TABLE schools ADD COLUMN logo_url VARCHAR(500)'))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS user_schools (
                user_id INTEGER NOT NULL, 
                school_id INTEGER NOT NULL, 
                PRIMARY KEY (user_id, school_id), 
                FOREIGN KEY (user_id) REFERENCES users(id), 
                FOREIGN KEY (school_id) REFERENCES schools(id)
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS query_templates (
                id SERIAL PRIMARY KEY, 
                organization_id INTEGER NOT NULL REFERENCES organizations(id), 
                title VARCHAR(100) NOT NULL, 
                subject VARCHAR(200) NOT NULL, 
                body TEXT NOT NULL, 
                from_email VARCHAR(255),
                created_by INTEGER NOT NULL REFERENCES users(id), 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                is_active BOOLEAN DEFAULT TRUE
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('ALTER TABLE query_templates ADD COLUMN IF NOT EXISTS from_email VARCHAR(255)'))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS staff_queries (
                id SERIAL PRIMARY KEY, 
                staff_id INTEGER NOT NULL REFERENCES staff(id), 
                template_id INTEGER NOT NULL REFERENCES query_templates(id), 
                sent_by INTEGER NOT NULL REFERENCES users(id), 
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                times_late_at_query INTEGER DEFAULT 0, 
                email_status VARCHAR(20) DEFAULT 'pending'
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS shifts (
                id SERIAL PRIMARY KEY, 
                school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE, 
                name VARCHAR(50) NOT NULL, 
                start_time VARCHAR(5) NOT NULL, 
                end_time VARCHAR(5) NOT NULL, 
                grace_period_minutes INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''CREATE TABLE IF NOT EXISTS staff_shift_assignments (
                id SERIAL PRIMARY KEY, 
                staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE, 
                shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE, 
                effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
                effective_to DATE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''))
            db.session.commit()
        except:
            db.session.rollback()
        
        if not SystemSettings.query.first():
            settings = SystemSettings(company_name='Wakato Technologies')
            db.session.add(settings)
        
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='super_admin')
            admin.set_password('admin123')
            db.session.add(admin)
        
        for org in Organization.query.all():
            if not Department.query.filter_by(organization_id=org.id).first():
                Department.create_defaults(org.id)
        
        db.session.commit()
        return 'Database initialized successfully! All tables and columns ready.'
    except Exception as e:
        return f'Error: {str(e)}'


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))














