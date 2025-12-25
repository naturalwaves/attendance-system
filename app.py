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
    name = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    time_format = db.Column(db.String(3), default='12h')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    
    uses_shift_system = db.Column(db.Boolean, default=False)
    grace_period_minutes = db.Column(db.Integer, default=0)
    work_days = db.Column(db.String(20), default='0,1,2,3,4')
    
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    users = db.relationship('User', backref='school', lazy=True)
    shifts = db.relationship('Shift', backref='school', lazy=True, cascade='all, delete-orphan')
    
    def get_work_days_list(self):
        if not self.work_days:
            return [0, 1, 2, 3, 4]
        return [int(d) for d in self.work_days.split(',') if d.strip()]
    
    def set_work_days_list(self, days_list):
        self.work_days = ','.join(str(d) for d in days_list)
    
    def is_work_day(self, day_of_week):
        return day_of_week in self.get_work_days_list()
    
    def get_work_days_display(self):
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        return [day_names[d] for d in self.get_work_days_list()]


class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    
    def get_start_time_display(self):
        return self._format_time(self.start_time)
    
    def get_end_time_display(self):
        return self._format_time(self.end_time)
    
    def _format_time(self, time_str):
        if not time_str:
            return ''
        try:
            time_format = '12h'
            school = School.query.get(self.school_id)
            if school and school.organization_id:
                org = Organization.query.get(school.organization_id)
                if org and hasattr(org, 'time_format') and org.time_format:
                    time_format = org.time_format
            
            t = datetime.strptime(time_str, '%H:%M')
            if time_format == '24h':
                return t.strftime('%H:%M')
            else:
                return t.strftime('%I:%M %p').lstrip('0')
        except:
            return time_str


class StaffShiftAssignment(db.Model):
    __tablename__ = 'staff_shift_assignments'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    staff = db.relationship('Staff', backref='shift_assignments')
    creator = db.relationship('User', backref='created_shift_assignments')
    
    @staticmethod
    def get_staff_shift_for_date(staff_id, check_date):
        assignment = StaffShiftAssignment.query.filter(
            StaffShiftAssignment.staff_id == staff_id,
            StaffShiftAssignment.start_date <= check_date,
            StaffShiftAssignment.end_date >= check_date
        ).order_by(StaffShiftAssignment.created_at.desc()).first()
        return assignment.shift if assignment else None
    
    def get_date_range_display(self):
        return f"{self.start_date.strftime('%d %b %Y')} - {self.end_date.strftime('%d %b %Y')}"
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
        if first_school.organization_id:
            org = Organization.query.get(first_school.organization_id)
            return org
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
    
    def get_current_shift(self):
        today = date.today()
        return StaffShiftAssignment.get_staff_shift_for_date(self.id, today)
    
    def get_shift_for_date(self, check_date):
        return StaffShiftAssignment.get_staff_shift_for_date(self.id, check_date)


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


def format_time_for_org(time_value, org_id):
    """Format time based on organization's time format preference (12h or 24h)"""
    if time_value is None:
        return '-'
    
    org = Organization.query.get(org_id) if org_id else None
    time_format = org.time_format if org and org.time_format else '12h'
    
    if isinstance(time_value, str):
        try:
            time_obj = datetime.strptime(time_value, '%H:%M')
        except ValueError:
            try:
                time_obj = datetime.strptime(time_value, '%H:%M:%S')
            except ValueError:
                return time_value
    elif isinstance(time_value, datetime):
        time_obj = time_value
    elif hasattr(time_value, 'strftime'):
        time_obj = time_value
    else:
        return str(time_value)
    
    if time_format == '12h':
        return time_obj.strftime('%I:%M %p').lstrip('0')
    else:
        return time_obj.strftime('%H:%M')


def get_school_schedule(school, day_of_week):
    """Get schedule for non-shift branches"""
    days = ['mon', 'tue', 'wed', 'thu', 'fri']
    if day_of_week < 5:
        day = days[day_of_week]
        start = getattr(school, f'schedule_{day}_start')
        end = getattr(school, f'schedule_{day}_end')
        return start, end
    return None, None


def get_staff_schedule_for_date(staff, check_date):
    """
    Get the schedule (start_time, end_time) for a staff member on a specific date.
    Handles both shift-based and regular schedules.
    Returns (start_time, end_time, grace_period_minutes) or (None, None, 0)
    """
    school = staff.school
    if not school:
        return None, None, 0
    
    day_of_week = check_date.weekday()
    
    if not school.is_work_day(day_of_week):
        return None, None, 0
    
    grace_period = school.grace_period_minutes or 0
    
    if school.uses_shift_system:
        shift = staff.get_shift_for_date(check_date)
        if shift:
            return shift.start_time, shift.end_time, grace_period
        else:
            return None, None, grace_period
    else:
        start_time, end_time = get_school_schedule(school, day_of_week)
        return start_time, end_time, grace_period


def calculate_late_status(staff, sign_in_datetime, check_date):
    """
    Calculate if staff is late and by how many minutes.
    Returns (is_late, late_minutes)
    """
    if staff.department == 'Management':
        return False, 0
    
    start_time, end_time, grace_period = get_staff_schedule_for_date(staff, check_date)
    
    if not start_time:
        return False, 0
    
    try:
        scheduled_start = datetime.strptime(start_time, '%H:%M').time()
        scheduled_start_dt = datetime.combine(check_date, scheduled_start)
        late_threshold_dt = scheduled_start_dt + timedelta(minutes=grace_period)
        late_threshold = late_threshold_dt.time()
        
        actual_time = sign_in_datetime.time()
        
        if actual_time > late_threshold:
            delta = datetime.combine(check_date, actual_time) - datetime.combine(check_date, scheduled_start)
            late_minutes = int(delta.total_seconds() / 60)
            return True, late_minutes
        else:
            return False, 0
    except Exception as e:
        print(f"Error calculating late status: {e}")
        return False, 0


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
    
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'noreply@wakatotech.com')
    
    reply_to_email = None
    if template.from_email:
        reply_to_email = template.from_email
    elif organization and hasattr(organization, 'hr_email') and organization.hr_email:
        reply_to_email = organization.hr_email
    
    actual_late_count = late_count if late_count is not None else staff.times_late
    actual_period = period_str if period_str else "All Time"
    
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
    
    subject = template.subject
    subject = subject.replace('{staff_name}', staff.name)
    subject = subject.replace('{date}', datetime.now().strftime('%d/%m/%Y'))
    subject = subject.replace('{period}', actual_period)
    
    email_data = {
        'personalizations': [{'to': [{'email': staff.email}]}],
        'from': {'email': from_email, 'name': 'HR Department'},
        'subject': subject,
        'content': [{'type': 'text/html', 'value': body}]
    }
    
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
        org = Organization(name=name)
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
        org.time_format = request.form.get('time_format', '12h')
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('edit_organization.html', organization=org)


@app.route('/organizations/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    branches = School.query.filter_by(organization_id=id).all()
    if branches:
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
        return jsonify([{'id': d.id, 'name': d.name} for d in departments])
    else:
        return jsonify([{'id': 0, 'name': 'Academic'}, {'id': 0, 'name': 'Non-Academic'}, {'id': 0, 'name': 'Administrative'}, {'id': 0, 'name': 'Support Staff'}])


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
def dashboard_stats():
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    if current_user.role == 'super_admin':
        schools = School.query.all()
        all_staff = Staff.query.filter_by(is_active=True).all()
    elif accessible_school_ids:
        schools = current_user.get_accessible_schools()
        all_staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids), Staff.is_active==True).all()
    else:
        schools = []
        all_staff = []
    total_schools = len(schools)
    management_staff = [s for s in all_staff if s.department == 'Management']
    non_mgmt_staff = [s for s in all_staff if s.department != 'Management']
    total_staff = len(non_mgmt_staff)
    management_count = len(management_staff)
    non_mgmt_ids = [s.id for s in non_mgmt_staff]
    today_attendance = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today).count() if non_mgmt_ids else 0
    late_today = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today, Attendance.is_late == True).count() if non_mgmt_ids else 0
    present_ids = [a.staff_id for a in Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today).all()] if non_mgmt_ids else []
    absent_today = len([s for s in non_mgmt_staff if s.id not in present_ids])
    
    first_checkin = None
    if non_mgmt_ids:
        first_attendance = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today, Attendance.sign_in_time.isnot(None)).order_by(Attendance.sign_in_time.asc()).first()
        if first_attendance:
            staff = Staff.query.get(first_attendance.staff_id)
            if staff and staff.school:
                org_id = staff.school.organization_id
                first_checkin = {
                    'name': staff.name, 
                    'branch': staff.school.short_name or staff.school.name, 
                    'department': staff.department, 
                    'time': format_time_for_org(first_attendance.sign_in_time, org_id)
                }
    
    recent_activity = []
    if non_mgmt_ids:
        recent_checkins = Attendance.query.filter(Attendance.staff_id.in_(non_mgmt_ids), Attendance.date == today).order_by(Attendance.sign_in_time.desc()).limit(20).all()
        for checkin in recent_checkins:
            staff = Staff.query.get(checkin.staff_id)
            if staff and staff.school:
                org_id = staff.school.organization_id
                recent_activity.append({
                    'name': staff.name, 
                    'time': format_time_for_org(checkin.sign_in_time, org_id) if checkin.sign_in_time else '', 
                    'branch': staff.school.short_name or staff.school.name
                })
    
    return jsonify({
        'total_schools': total_schools, 
        'total_staff': total_staff, 
        'management_count': management_count, 
        'today_attendance': today_attendance, 
        'late_today': late_today, 
        'absent_today': absent_today, 
        'first_checkin': first_checkin, 
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
        org_id = staff.school.organization_id if staff.school else None
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
        if staff.department == 'Management':
            if attendance:
                status = 'signed_in'
                time_str = format_time_for_org(attendance.sign_in_time, org_id) if attendance.sign_in_time else None
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
                    time_str = format_time_for_org(attendance.sign_in_time, org_id)
        results.append({
            'id': staff.id, 
            'staff_id': staff.staff_id, 
            'name': staff.name, 
            'branch': staff.school.short_name or staff.school.name if staff.school else 'N/A', 
            'department': staff.department, 
            'status': status, 
            'time': time_str
        })
    return jsonify({'results': results})


@app.route('/api/branch-staff/<int:branch_id>')
@login_required
def get_branch_staff(branch_id):
    today = date.today()
    school = School.query.get(branch_id)
    if not school:
        return jsonify([])
    org_id = school.organization_id
    staff_list = Staff.query.filter_by(school_id=branch_id, is_active=True).all()
    result = []
    for staff in staff_list:
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
        if staff.department == 'Management':
            if attendance:
                status = 'Signed In'
                time_in = format_time_for_org(attendance.sign_in_time, org_id) if attendance.sign_in_time else '-'
                time_out = format_time_for_org(attendance.sign_out_time, org_id) if attendance.sign_out_time else '-'
            else:
                status = 'Not Signed In'
                time_in = '-'
                time_out = '-'
        else:
            if attendance:
                if attendance.is_late:
                    status = 'Late'
                else:
                    status = 'Present'
                time_in = format_time_for_org(attendance.sign_in_time, org_id) if attendance.sign_in_time else '-'
                time_out = format_time_for_org(attendance.sign_out_time, org_id) if attendance.sign_out_time else '-'
            else:
                status = 'Absent'
                time_in = '-'
                time_out = '-'
        result.append({
            'name': staff.name, 
            'department': staff.department, 
            'status': status, 
            'time_in': time_in, 
            'time_out': time_out
        })
    return jsonify(result)


# ==================== SCHOOLS/BRANCHES ====================

@app.route('/schools')
@login_required
@role_required('super_admin')
def schools():
    organization_id = request.args.get('organization_id', type=int)
    organizations = Organization.query.all()
    if organization_id:
        all_schools = School.query.filter_by(organization_id=organization_id).all()
    else:
        all_schools = School.query.all()
    total_staff = sum(len(s.staff) for s in all_schools)
    total_active_staff = sum(len([st for st in s.staff if st.is_active]) for s in all_schools)
    return render_template('schools.html', 
        schools=all_schools, 
        organizations=organizations,
        selected_organization=organization_id,
        total_staff=total_staff,
        total_active_staff=total_active_staff
    )


@app.route('/branches')
@login_required
@role_required('super_admin')
def branches():
    organization_id = request.args.get('organization_id', type=int)
    organizations = Organization.query.all()
    if organization_id:
        all_schools = School.query.filter_by(organization_id=organization_id).all()
    else:
        all_schools = School.query.all()
    total_staff = sum(len(s.staff) for s in all_schools)
    total_active_staff = sum(len([st for st in s.staff if st.is_active]) for s in all_schools)
    return render_template('schools.html', 
        schools=all_schools, 
        organizations=organizations,
        selected_organization=organization_id,
        total_staff=total_staff,
        total_active_staff=total_active_staff
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


# ==================== BRANCH SETTINGS (SHIFT SYSTEM) ====================

@app.route('/schools/<int:id>/settings', methods=['GET', 'POST'])
@login_required
def branch_settings(id):
    school = School.query.get_or_404(id)
    
    if current_user.role == 'school_admin':
        allowed_ids = [s.id for s in current_user.allowed_schools]
        if school.id not in allowed_ids:
            flash('Access denied', 'danger')
            return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school.uses_shift_system = 'uses_shift_system' in request.form
        school.grace_period_minutes = int(request.form.get('grace_period_minutes', 0))
        work_days = request.form.getlist('work_days')
        school.set_work_days_list([int(d) for d in work_days])
        db.session.commit()
        flash('Branch settings updated successfully', 'success')
        return redirect(url_for('branch_settings', id=id))
    
    shifts = Shift.query.filter_by(school_id=id).all()
    staff_list = Staff.query.filter_by(school_id=id, is_active=True).all()
    
    staff_assignments = {}
    for staff in staff_list:
        assignments = StaffShiftAssignment.query.filter_by(staff_id=staff.id).all()
        staff_assignments[staff.id] = assignments
    
    time_format = '12h'
    if school.organization_id:
        org = Organization.query.get(school.organization_id)
        if org and hasattr(org, 'time_format') and org.time_format:
            time_format = org.time_format
    
    return render_template('branch_settings.html', 
                           school=school, 
                           shifts=shifts, 
                           staff_list=staff_list,
                           staff_assignments=staff_assignments,
                           today=date.today(),
                           time_format=time_format)


@app.route('/schools/<int:school_id>/shifts/add', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_shift(school_id):
    school = School.query.get_or_404(school_id)
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    
    name = request.form.get('name', '').strip()
    start_time = request.form.get('start_time', '').strip()
    end_time = request.form.get('end_time', '').strip()
    
    if not all([name, start_time, end_time]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    existing = Shift.query.filter_by(school_id=school_id, name=name).first()
    if existing:
        flash(f'A shift named "{name}" already exists.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    shift = Shift(
        school_id=school_id,
        name=name,
        start_time=start_time,
        end_time=end_time
    )
    db.session.add(shift)
    db.session.commit()
    
    flash(f'Shift "{name}" added successfully!', 'success')
    return redirect(url_for('branch_settings', id=school_id))


@app.route('/schools/<int:school_id>/shifts/<int:shift_id>/edit', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_shift(school_id, shift_id):
    school = School.query.get_or_404(school_id)
    shift = Shift.query.get_or_404(shift_id)
    
    if shift.school_id != school_id:
        flash('Invalid shift.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    
    shift.name = request.form.get('name', '').strip()
    shift.start_time = request.form.get('start_time', '').strip()
    shift.end_time = request.form.get('end_time', '').strip()
    
    db.session.commit()
    flash(f'Shift "{shift.name}" updated successfully!', 'success')
    return redirect(url_for('branch_settings', id=school_id))


@app.route('/schools/<int:school_id>/shifts/<int:shift_id>/delete')
@login_required
@role_required('super_admin', 'school_admin')
def delete_shift(school_id, shift_id):
    school = School.query.get_or_404(school_id)
    shift = Shift.query.get_or_404(shift_id)
    
    if shift.school_id != school_id:
        flash('Invalid shift.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    
    shift_name = shift.name
    
    StaffShiftAssignment.query.filter_by(shift_id=shift_id).delete()
    db.session.delete(shift)
    db.session.commit()
    
    flash(f'Shift "{shift_name}" deleted successfully!', 'success')
    return redirect(url_for('branch_settings', id=school_id))


@app.route('/schools/<int:school_id>/roster/assign', methods=['POST'])
@login_required
@role_required('super_admin', 'school_admin')
def assign_shift_roster(school_id):
    school = School.query.get_or_404(school_id)
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    
    staff_id = request.form.get('staff_id', type=int)
    shift_id = request.form.get('shift_id', type=int)
    start_date_str = request.form.get('start_date', '')
    end_date_str = request.form.get('end_date', '')
    
    if not all([staff_id, shift_id, start_date_str, end_date_str]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    staff = Staff.query.get(staff_id)
    if not staff or staff.school_id != school_id:
        flash('Invalid staff member.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    shift = Shift.query.get(shift_id)
    if not shift or shift.school_id != school_id:
        flash('Invalid shift.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    if end_date < start_date:
        flash('End date must be after start date.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    overlapping = StaffShiftAssignment.query.filter(
        StaffShiftAssignment.staff_id == staff_id,
        StaffShiftAssignment.start_date <= end_date,
        StaffShiftAssignment.end_date >= start_date
    ).first()
    
    if overlapping:
        flash(f'This staff already has a shift assigned during this period ({overlapping.get_date_range_display()}).', 'warning')
        return redirect(url_for('branch_settings', id=school_id))
    
    assignment = StaffShiftAssignment(
        staff_id=staff_id,
        shift_id=shift_id,
        start_date=start_date,
        end_date=end_date,
        created_by=current_user.id
    )
    db.session.add(assignment)
    db.session.commit()
    
    flash(f'Shift assigned to {staff.name} successfully!', 'success')
    return redirect(url_for('branch_settings', id=school_id))


@app.route('/schools/<int:school_id>/roster/<int:assignment_id>/delete')
@login_required
@role_required('super_admin', 'school_admin')
def delete_shift_assignment(school_id, assignment_id):
    school = School.query.get_or_404(school_id)
    assignment = StaffShiftAssignment.query.get_or_404(assignment_id)
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    
    if assignment.staff.school_id != school_id:
        flash('Invalid assignment.', 'danger')
        return redirect(url_for('branch_settings', id=school_id))
    
    staff_name = assignment.staff.name
    db.session.delete(assignment)
    db.session.commit()
    
    flash(f'Shift assignment for {staff_name} removed.', 'success')
    return redirect(url_for('branch_settings', id=school_id))


@app.route('/api/staff-shift/<int:staff_id>')
@login_required
def get_staff_shift(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    today = date.today()
    shift = staff.get_shift_for_date(today)
    org_id = staff.school.organization_id if staff.school else None
    
    if shift:
        return jsonify({
            'has_shift': True,
            'shift_name': shift.name,
            'start_time': shift.start_time,
            'end_time': shift.end_time,
            'start_time_display': format_time_for_org(shift.start_time, org_id),
            'end_time_display': format_time_for_org(shift.end_time, org_id)
        })
    else:
        return jsonify({
            'has_shift': False,
            'message': 'No shift assigned for today'
        })
# ==================== STAFF ====================

@app.route('/staff')
@login_required
def staff_list():
    organization_id = request.args.get('organization_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = current_user.get_accessible_organizations()
    
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
        staff = Staff.query.all()
    else:
        allowed_school_ids = [s.id for s in current_user.allowed_schools]
        staff = Staff.query.filter(Staff.school_id.in_(allowed_school_ids)).order_by(Staff.name).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Email', 'Phone', 'Status'])
    for s in staff:
        org_name = ''
        if s.school and s.school.organization_id:
            org = Organization.query.get(s.school.organization_id)
            org_name = org.name if org else ''
        writer.writerow([
            s.staff_id, 
            s.name, 
            org_name, 
            s.school.name if s.school else '', 
            s.department or '', 
            s.email or '', 
            s.phone or '', 
            'Active' if s.is_active else 'Inactive'
        ])
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
    if user.role != 'super_admin':
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
        
        period_start = request.form.get('period_start', '')
        period_end = request.form.get('period_end', '')
        
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
    
    accessible_school_ids = current_user.get_accessible_school_ids()
    organization_id = request.args.get('organization_id', type=int)
    branch_id = request.args.get('branch_id', type=int)
    period = request.args.get('period', 'all')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    
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
    
    staff_query = Staff.query.filter(Staff.is_active == True, Staff.department != 'Management')
    
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
    
    late_staff.sort(key=lambda x: x['late_count'], reverse=True)
    
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
    
    for a in attendance:
        org_id = a.staff.school.organization_id if a.staff.school else None
        a.sign_in_formatted = format_time_for_org(a.sign_in_time, org_id)
        a.sign_out_formatted = format_time_for_org(a.sign_out_time, org_id)
    
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
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late Duration', 'Overtime Duration'])
    for a in attendance:
        org_id = a.staff.school.organization_id if a.staff.school else None
        org_name = ''
        if a.staff.school and a.staff.school.organization_id:
            org = Organization.query.get(a.staff.school.organization_id)
            org_name = org.name if org else ''
        if a.staff.department == 'Management':
            status = 'Signed In'
            late_formatted = '-'
        else:
            late_formatted = format_minutes_to_hours(a.late_minutes) if a.is_late else 'On Time'
            status = f'Late ({late_formatted})' if a.is_late else 'On Time'
        overtime_formatted = format_minutes_to_hours(a.overtime_minutes)
        writer.writerow([
            a.date.strftime('%d/%m/%Y'), 
            a.staff.staff_id, 
            a.staff.name, 
            org_name, 
            a.staff.school.short_name or a.staff.school.name if a.staff.school else '', 
            a.staff.department, 
            format_time_for_org(a.sign_in_time, org_id), 
            format_time_for_org(a.sign_out_time, org_id), 
            status, 
            late_formatted, 
            overtime_formatted
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
            late_staff.append({'staff': s, 'times_late': times_late, 'punctuality': punctuality, 'lateness': lateness})
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
    writer.writerow(['Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
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
            org_name = ''
            if s.school and s.school.organization_id:
                org = Organization.query.get(s.school.organization_id)
                org_name = org.name if org else ''
            writer.writerow([
                s.staff_id, 
                s.name, 
                org_name, 
                s.school.short_name or s.school.name if s.school else '', 
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
            if s.school and not s.school.is_work_day(current_date.weekday()):
                continue
            attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
            if not attendance:
                absent_records.append({'date': current_date, 'staff': s})
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
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department'])
    current_date = start_date
    while current_date <= end_date:
        for s in all_staff:
            if s.department == 'Management':
                continue
            if s.school and not s.school.is_work_day(current_date.weekday()):
                continue
            attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
            if not attendance:
                org_name = ''
                if s.school and s.school.organization_id:
                    org = Organization.query.get(s.school.organization_id)
                    org_name = org.name if org else ''
                writer.writerow([
                    current_date.strftime('%d/%m/%Y'), 
                    s.staff_id, 
                    s.name, 
                    org_name, 
                    s.school.short_name or s.school.name if s.school else '', 
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
    
    for o in overtime:
        org_id = o.staff.school.organization_id if o.staff.school else None
        o.sign_in_formatted = format_time_for_org(o.sign_in_time, org_id)
        o.sign_out_formatted = format_time_for_org(o.sign_out_time, org_id)
    
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
    writer.writerow(['Date', 'Staff ID', 'Name', 'Organization', 'Branch', 'Department', 'Sign Out', 'Overtime'])
    for o in overtime:
        org_id = o.staff.school.organization_id if o.staff.school else None
        org_name = ''
        if o.staff.school and o.staff.school.organization_id:
            org = Organization.query.get(o.staff.school.organization_id)
            org_name = org.name if org else ''
        writer.writerow([
            o.date.strftime('%d/%m/%Y'), 
            o.staff.staff_id, 
            o.staff.name, 
            org_name, 
            o.staff.school.short_name or o.staff.school.name if o.staff.school else '', 
            o.staff.department, 
            format_time_for_org(o.sign_out_time, org_id), 
            format_minutes_to_hours(o.overtime_minutes)
        ])
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
                    day_of_week = a.date.weekday()
                    start_time, _ = get_school_schedule(s.school, day_of_week)
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
# ==================== SYNC API ====================

@app.route('/api/sync', methods=['POST'])
def sync_attendance():
    """Receive attendance data from school devices"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid authorization'}), 401
    
    api_key = auth_header.split(' ')[1]
    school = School.query.filter_by(api_key=api_key).first()
    
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    records = data.get('records', [])
    results = {'processed': 0, 'errors': []}
    
    for record in records:
        try:
            staff_id = record.get('staff_id')
            staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
            
            if not staff:
                results['errors'].append(f"Staff {staff_id} not found")
                continue
            
            date_str = record.get('date')
            attendance_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            attendance = Attendance.query.filter_by(
                staff_id=staff.id,
                date=attendance_date
            ).first()
            
            sign_in = record.get('sign_in_time')
            sign_out = record.get('sign_out_time')
            
            if not attendance:
                attendance = Attendance(
                    staff_id=staff.id,
                    date=attendance_date,
                    sign_in_time=sign_in,
                    sign_out_time=sign_out
                )
                db.session.add(attendance)
            else:
                if sign_in and not attendance.sign_in_time:
                    attendance.sign_in_time = sign_in
                if sign_out:
                    attendance.sign_out_time = sign_out
            
            # Calculate late status
            if attendance.sign_in_time:
                schedule = get_staff_schedule_for_date(staff, attendance_date)
                if schedule and schedule.get('start_time'):
                    late_info = calculate_late_status(
                        attendance.sign_in_time,
                        schedule['start_time'],
                        schedule.get('grace_period', 0)
                    )
                    attendance.status = 'late' if late_info['is_late'] else 'present'
                    attendance.minutes_late = late_info['minutes_late']
                else:
                    attendance.status = 'present'
            
            # Calculate overtime
            if attendance.sign_in_time and attendance.sign_out_time:
                schedule = get_staff_schedule_for_date(staff, attendance_date)
                if schedule and schedule.get('end_time'):
                    try:
                        sign_out_dt = datetime.strptime(attendance.sign_out_time, '%H:%M')
                        end_dt = datetime.strptime(schedule['end_time'], '%H:%M')
                        if sign_out_dt > end_dt:
                            diff = (sign_out_dt - end_dt).total_seconds() / 60
                            attendance.overtime_minutes = int(diff)
                    except:
                        pass
            
            db.session.commit()
            results['processed'] += 1
            
        except Exception as e:
            results['errors'].append(f"Error processing record: {str(e)}")
    
    return jsonify(results)


@app.route('/api/staff/<school_id>', methods=['GET'])
def get_staff_list(school_id):
    """Get staff list for a school (for device sync)"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid authorization'}), 401
    
    api_key = auth_header.split(' ')[1]
    school = School.query.filter_by(api_key=api_key, id=school_id).first()
    
    if not school:
        return jsonify({'error': 'Invalid API key or school'}), 401
    
    staff_list = Staff.query.filter_by(school_id=school.id, is_active=True).all()
    
    return jsonify({
        'staff': [{
            'staff_id': s.staff_id,
            'name': s.name,
            'department': s.department
        } for s in staff_list]
    })


@app.route('/api/dashboard-data')
@login_required
def dashboard_data():
    """API endpoint for real-time dashboard data"""
    today = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        accessible_ids = current_user.get_accessible_school_ids()
        schools = School.query.filter(School.id.in_(accessible_ids)).all()
    
    school_ids = [s.id for s in schools]
    
    total_staff = Staff.query.filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True
    ).count()
    
    today_attendance = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today
    ).count()
    
    today_late = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today,
        Attendance.status == 'late'
    ).count()
    
    # Get first check-in
    first_checkin = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date == today,
        Attendance.sign_in_time.isnot(None)
    ).order_by(Attendance.sign_in_time).first()
    
    first_checkin_time = None
    first_checkin_staff = None
    if first_checkin:
        staff = Staff.query.get(first_checkin.staff_id)
        school = School.query.get(staff.school_id) if staff else None
        org = Organization.query.get(school.organization_id) if school else None
        time_format = org.time_format if org and hasattr(org, 'time_format') else '12h'
        first_checkin_time = format_time_for_org(first_checkin.sign_in_time, time_format)
        first_checkin_staff = staff.name if staff else 'Unknown'
    
    return jsonify({
        'total_staff': total_staff,
        'today_attendance': today_attendance,
        'today_late': today_late,
        'attendance_rate': round((today_attendance / total_staff * 100) if total_staff > 0 else 0, 1),
        'first_checkin_time': first_checkin_time,
        'first_checkin_staff': first_checkin_staff
    })


@app.route('/api/organization-branches/<int:org_id>')
@login_required
def get_organization_branches(org_id):
    """Get branches for an organization"""
    branches = School.query.filter_by(organization_id=org_id).all()
    return jsonify({
        'branches': [{'id': b.id, 'name': b.name} for b in branches]
    })


@app.route('/api/branch-departments/<int:branch_id>')
@login_required
def get_branch_departments(branch_id):
    """Get departments available for a branch"""
    school = School.query.get_or_404(branch_id)
    departments = Department.query.filter_by(organization_id=school.organization_id).all()
    return jsonify({
        'departments': [{'id': d.id, 'name': d.name} for d in departments]
    })


@app.route('/api/branch-staff/<int:branch_id>')
@login_required
def get_branch_staff(branch_id):
    """Get staff for a specific branch with today's attendance"""
    school = School.query.get_or_404(branch_id)
    
    if current_user.role == 'school_admin':
        if school.id not in current_user.get_accessible_school_ids():
            return jsonify({'error': 'Access denied'}), 403
    
    today = datetime.now().date()
    staff_list = Staff.query.filter_by(school_id=school.id, is_active=True).all()
    
    org = Organization.query.get(school.organization_id) if school.organization_id else None
    time_format = org.time_format if org and hasattr(org, 'time_format') else '12h'
    
    result = []
    for staff in staff_list:
        attendance = Attendance.query.filter_by(
            staff_id=staff.id,
            date=today
        ).first()
        
        status = 'not_checked_in'
        sign_in = None
        sign_out = None
        
        if attendance:
            if attendance.sign_in_time:
                sign_in = format_time_for_org(attendance.sign_in_time, time_format)
                status = attendance.status or 'present'
            if attendance.sign_out_time:
                sign_out = format_time_for_org(attendance.sign_out_time, time_format)
        
        result.append({
            'id': staff.id,
            'staff_id': staff.staff_id,
            'name': staff.name,
            'department': staff.department,
            'status': status,
            'sign_in': sign_in,
            'sign_out': sign_out
        })
    
    return jsonify({'staff': result})


# ==================== INITIALIZE DATABASE ====================

@app.route('/init-db')
def init_db():
    """Initialize the database with default data"""
    try:
        db.create_all()
        
        # Create default system settings
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(
                company_name='Attendance System',
                company_logo_url=''
            )
            db.session.add(settings)
        
        # Create default super admin
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                role='super_admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Database initialized successfully',
            'default_login': {
                'username': 'admin',
                'password': 'admin123'
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
