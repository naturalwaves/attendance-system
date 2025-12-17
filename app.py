from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Association table for User-School relationship
user_schools = db.Table('user_schools',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('school.id'), primary_key=True)
)

# Models
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Attendance System')
    logo_url = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    logo_url = db.Column(db.String(500))
    start_time = db.Column(db.String(10), default='08:00')
    late_time = db.Column(db.String(10), default='08:15')
    close_time = db.Column(db.String(10), default='17:00')
    is_active = db.Column(db.Boolean, default=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    staff = db.relationship('Staff', backref='school', lazy=True)
    attendance = db.relationship('Attendance', backref='school', lazy=True)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='school_admin')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', secondary=user_schools, lazy='subquery',
                              backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    position = db.Column(db.String(100))
    photo_url = db.Column(db.String(500))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    late_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance = db.relationship('Attendance', backref='staff', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    clock_in = db.Column(db.DateTime)
    clock_out = db.Column(db.DateTime)
    status = db.Column(db.String(20))
    overtime_minutes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Context processor for templates
@app.context_processor
def utility_processor():
    def now():
        return datetime.now()
    settings = None
    try:
        settings = SystemSettings.query.first()
    except:
        pass
    return dict(now=now, system_settings=settings)

# Decorators
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['super_admin', 'school_admin']:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_schools():
    if current_user.role == 'super_admin':
        return School.query.all()
    return current_user.schools

def get_user_school_ids():
    if current_user.role == 'super_admin':
        return [s.id for s in School.query.all()]
    return [s.id for s in current_user.schools]

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
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account is disabled.', 'danger')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    school_ids = get_user_school_ids()
    today = datetime.now().date()
    
    if not school_ids:
        total_staff = 0
        present_today = 0
        late_today = 0
        absent_today = 0
    else:
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
        present_today = Attendance.query.filter(
            Attendance.school_id.in_(school_ids),
            Attendance.date == today
        ).count()
        late_today = Attendance.query.filter(
            Attendance.school_id.in_(school_ids),
            Attendance.date == today,
            Attendance.status == 'late'
        ).count()
        absent_today = total_staff - present_today
    
    recent_attendance = []
    if school_ids:
        recent_attendance = Attendance.query.filter(
            Attendance.school_id.in_(school_ids)
        ).order_by(Attendance.created_at.desc()).limit(10).all()
    
    return render_template('dashboard.html',
                         total_staff=total_staff,
                         present_today=present_today,
                         late_today=late_today,
                         absent_today=absent_today,
                         recent_attendance=recent_attendance)

# Schools/Branches
@app.route('/schools')
@login_required
@admin_required
def schools():
    if current_user.role == 'super_admin':
        all_schools = School.query.all()
    else:
        all_schools = current_user.schools
    organizations = Organization.query.all()
    return render_template('schools.html', schools=all_schools, organizations=organizations)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_school():
    if request.method == 'POST':
        school = School(
            name=request.form.get('name'),
            address=request.form.get('address'),
            start_time=request.form.get('start_time', '08:00'),
            late_time=request.form.get('late_time', '08:15'),
            close_time=request.form.get('close_time', '17:00'),
            organization_id=request.form.get('organization_id') or None
        )
        db.session.add(school)
        db.session.commit()
        
        if current_user.role != 'super_admin':
            current_user.schools.append(school)
            db.session.commit()
        
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_school(id):
    school = School.query.get_or_404(id)
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.address = request.form.get('address')
        school.start_time = request.form.get('start_time', '08:00')
        school.late_time = request.form.get('late_time', '08:15')
        school.close_time = request.form.get('close_time', '17:00')
        school.organization_id = request.form.get('organization_id') or None
        school.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('edit_school.html', school=school, organizations=organizations)

@app.route('/schools/delete/<int:id>')
@login_required
@super_admin_required
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

# Organizations
@app.route('/organizations')
@login_required
@super_admin_required
def organizations():
    all_orgs = Organization.query.all()
    return render_template('organizations.html', organizations=all_orgs)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_organization():
    if request.method == 'POST':
        org = Organization(
            name=request.form.get('name'),
            logo_url=request.form.get('logo_url')
        )
        db.session.add(org)
        db.session.commit()
        flash('Organization added successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('add_organization.html')

@app.route('/organizations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url')
        org.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('edit_organization.html', organization=org)

@app.route('/organizations/delete/<int:id>')
@login_required
@super_admin_required
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('organizations'))

# Staff
@app.route('/staff')
@login_required
def staff():
    school_ids = get_user_school_ids()
    if not school_ids:
        all_staff = []
    else:
        all_staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
    schools = get_user_schools()
    return render_template('staff.html', staff=all_staff, schools=schools)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_staff():
    if request.method == 'POST':
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            first_name=request.form.get('first_name'),
            last_name=request.form.get('last_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            school_id=request.form.get('school_id')
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff'))
    schools = get_user_schools()
    return render_template('add_staff.html', schools=schools)

@app.route('/staff/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    if request.method == 'POST':
        staff.staff_id = request.form.get('staff_id')
        staff.first_name = request.form.get('first_name')
        staff.last_name = request.form.get('last_name')
        staff.email = request.form.get('email')
        staff.phone = request.form.get('phone')
        staff.department = request.form.get('department')
        staff.position = request.form.get('position')
        staff.school_id = request.form.get('school_id')
        staff.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('staff'))
    schools = get_user_schools()
    return render_template('edit_staff.html', staff=staff, schools=schools)

@app.route('/staff/delete/<int:id>')
@login_required
@admin_required
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff'))

# Users
@app.route('/users')
@login_required
@super_admin_required
def users():
    all_users = User.query.all()
    return render_template('users.html', users=all_users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_user():
    if request.method == 'POST':
        user = User(
            username=request.form.get('username'),
            email=request.form.get('email'),
            role=request.form.get('role', 'school_admin')
        )
        user.set_password(request.form.get('password'))
        db.session.add(user)
        db.session.commit()
        
        school_ids = request.form.getlist('schools')
        for school_id in school_ids:
            school = School.query.get(school_id)
            if school:
                user.schools.append(school)
        db.session.commit()
        
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    return render_template('add_user.html', schools=schools)

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role', 'school_admin')
        user.is_active = 'is_active' in request.form
        
        if request.form.get('password'):
            user.set_password(request.form.get('password'))
        
        user.schools = []
        school_ids = request.form.getlist('schools')
        for school_id in school_ids:
            school = School.query.get(school_id)
            if school:
                user.schools.append(school)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    return render_template('edit_user.html', user=user, schools=schools)

@app.route('/users/delete/<int:id>')
@login_required
@super_admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

# Attendance
@app.route('/attendance')
@login_required
def attendance():
    school_ids = get_user_school_ids()
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    school_filter = request.args.get('school', '')
    
    query = Attendance.query.filter(Attendance.date == selected_date)
    
    if school_filter:
        query = query.filter(Attendance.school_id == school_filter)
    elif school_ids:
        query = query.filter(Attendance.school_id.in_(school_ids))
    
    records = query.all()
    schools = get_user_schools()
    
    return render_template('attendance.html', 
                         attendance=records, 
                         schools=schools,
                         selected_date=date_str,
                         selected_school=school_filter)

@app.route('/attendance/clock-in', methods=['POST'])
@login_required
def clock_in():
    staff_id = request.form.get('staff_id')
    staff = Staff.query.filter_by(staff_id=staff_id).first()
    
    if not staff:
        flash('Staff not found.', 'danger')
        return redirect(url_for('attendance'))
    
    today = datetime.now().date()
    existing = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    if existing:
        flash('Already clocked in today.', 'warning')
        return redirect(url_for('attendance'))
    
    now = datetime.now()
    school = staff.school
    late_time = datetime.strptime(school.late_time or '08:15', '%H:%M').time()
    
    status = 'present'
    if now.time() > late_time:
        status = 'late'
        staff.late_count = (staff.late_count or 0) + 1
    
    attendance = Attendance(
        staff_id=staff.id,
        school_id=staff.school_id,
        date=today,
        clock_in=now,
        status=status
    )
    db.session.add(attendance)
    db.session.commit()
    
    flash(f'Clock in recorded for {staff.first_name} {staff.last_name}', 'success')
    return redirect(url_for('attendance'))

@app.route('/attendance/clock-out', methods=['POST'])
@login_required
def clock_out():
    staff_id = request.form.get('staff_id')
    staff = Staff.query.filter_by(staff_id=staff_id).first()
    
    if not staff:
        flash('Staff not found.', 'danger')
        return redirect(url_for('attendance'))
    
    today = datetime.now().date()
    attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    if not attendance:
        flash('No clock in record found for today.', 'warning')
        return redirect(url_for('attendance'))
    
    if attendance.clock_out:
        flash('Already clocked out today.', 'warning')
        return redirect(url_for('attendance'))
    
    now = datetime.now()
    attendance.clock_out = now
    
    school = staff.school
    close_time = datetime.strptime(school.close_time or '17:00', '%H:%M').time()
    close_datetime = datetime.combine(today, close_time)
    
    if now > close_datetime:
        overtime = (now - close_datetime).seconds // 60
        attendance.overtime_minutes = overtime
    
    db.session.commit()
    
    flash(f'Clock out recorded for {staff.first_name} {staff.last_name}', 'success')
    return redirect(url_for('attendance'))

# Reports
@app.route('/reports/attendance')
@login_required
def attendance_report():
    school_ids = get_user_school_ids()
    
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    school_filter = request.args.get('school', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    query = Attendance.query.filter(Attendance.date.between(start, end))
    
    if school_filter:
        query = query.filter(Attendance.school_id == school_filter)
    elif school_ids:
        query = query.filter(Attendance.school_id.in_(school_ids))
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = get_user_schools()
    
    return render_template('attendance_report.html',
                         attendance=records,
                         schools=schools,
                         start_date=start_date,
                         end_date=end_date,
                         selected_school=school_filter)

@app.route('/reports/late')
@login_required
def late_report():
    school_ids = get_user_school_ids()
    
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    school_filter = request.args.get('school', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    query = Attendance.query.filter(
        Attendance.date.between(start, end),
        Attendance.status == 'late'
    )
    
    if school_filter:
        query = query.filter(Attendance.school_id == school_filter)
    elif school_ids:
        query = query.filter(Attendance.school_id.in_(school_ids))
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = get_user_schools()
    
    return render_template('late_report.html',
                         attendance=records,
                         schools=schools,
                         start_date=start_date,
                         end_date=end_date,
                         selected_school=school_filter)

@app.route('/reports/absent')
@login_required
def absent_report():
    school_ids = get_user_school_ids()
    
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    school_filter = request.args.get('school', '')
    
    if school_filter:
        filter_ids = [int(school_filter)]
    elif school_ids:
        filter_ids = school_ids
    else:
        filter_ids = []
    
    if filter_ids:
        all_staff = Staff.query.filter(Staff.school_id.in_(filter_ids), Staff.is_active == True).all()
        present_staff_ids = [a.staff_id for a in Attendance.query.filter(
            Attendance.date == selected_date,
            Attendance.school_id.in_(filter_ids)
        ).all()]
        absent_staff = [s for s in all_staff if s.id not in present_staff_ids]
    else:
        absent_staff = []
    
    schools = get_user_schools()
    
    return render_template('absent_report.html',
                         staff=absent_staff,
                         schools=schools,
                         selected_date=date_str,
                         selected_school=school_filter)

@app.route('/reports/overtime')
@login_required
def overtime_report():
    school_ids = get_user_school_ids()
    
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    school_filter = request.args.get('school', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    query = Attendance.query.filter(
        Attendance.date.between(start, end),
        Attendance.overtime_minutes > 0
    )
    
    if school_filter:
        query = query.filter(Attendance.school_id == school_filter)
    elif school_ids:
        query = query.filter(Attendance.school_id.in_(school_ids))
    
    records = query.order_by(Attendance.date.desc()).all()
    schools = get_user_schools()
    
    return render_template('overtime_report.html',
                         attendance=records,
                         schools=schools,
                         start_date=start_date,
                         end_date=end_date,
                         selected_school=school_filter)

# Analytics
@app.route('/reports/analytics')
@login_required
def analytics():
    school_ids = get_user_school_ids()
    schools = get_user_schools()
    organizations = Organization.query.all() if current_user.role == 'super_admin' else []
    
    period = request.args.get('period', '30')
    school_filter = request.args.get('school', '')
    org_filter = request.args.get('organization', '')
    
    today = datetime.now().date()
    
    if period == 'custom':
        start_date = datetime.strptime(request.args.get('start_date', (today - timedelta(days=30)).strftime('%Y-%m-%d')), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.args.get('end_date', today.strftime('%Y-%m-%d')), '%Y-%m-%d').date()
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
        last_month_end = first_of_this_month - timedelta(days=1)
        start_date = last_month_end.replace(day=1)
        end_date = last_month_end
    elif period == '90':
        start_date = today - timedelta(days=90)
        end_date = today
    else:
        start_date = today - timedelta(days=int(period))
        end_date = today
    
    if org_filter:
        org_schools = School.query.filter_by(organization_id=org_filter).all()
        filter_ids = [s.id for s in org_schools]
    elif school_filter:
        filter_ids = [int(school_filter)]
    elif school_ids:
        filter_ids = school_ids
    else:
        filter_ids = []
    
    if filter_ids:
        total_staff = Staff.query.filter(Staff.school_id.in_(filter_ids), Staff.is_active == True).count()
        
        attendance_records = Attendance.query.filter(
            Attendance.school_id.in_(filter_ids),
            Attendance.date.between(start_date, end_date)
        ).all()
        
        total_present = len(attendance_records)
        total_late = len([a for a in attendance_records if a.status == 'late'])
        total_overtime = sum(a.overtime_minutes or 0 for a in attendance_records)
        
        working_days = sum(1 for i in range((end_date - start_date).days + 1) 
                         if (start_date + timedelta(days=i)).weekday() < 5)
        
        expected_attendance = total_staff * working_days if working_days > 0 else 1
        attendance_rate = round((total_present / expected_attendance) * 100, 1) if expected_attendance > 0 else 0
        late_rate = round((total_late / total_present) * 100, 1) if total_present > 0 else 0
        
        dates = []
        present_counts = []
        late_counts = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:
                dates.append(current_date.strftime('%b %d'))
                day_records = [a for a in attendance_records if a.date == current_date]
                present_counts.append(len(day_records))
                late_counts.append(len([a for a in day_records if a.status == 'late']))
            current_date += timedelta(days=1)
        
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        late_by_day = [0] * 5
        for a in attendance_records:
            if a.status == 'late' and a.date.weekday() < 5:
                late_by_day[a.date.weekday()] += 1
        
        dept_stats = {}
        for a in attendance_records:
            dept = a.staff.department or 'Unassigned'
            if dept not in dept_stats:
                dept_stats[dept] = {'present': 0, 'late': 0}
            dept_stats[dept]['present'] += 1
            if a.status == 'late':
                dept_stats[dept]['late'] += 1
        
        departments = list(dept_stats.keys())
        dept_present = [dept_stats[d]['present'] for d in departments]
        dept_late = [dept_stats[d]['late'] for d in departments]
        
        branch_stats = {}
        for a in attendance_records:
            branch = a.school.name
            if branch not in branch_stats:
                branch_stats[branch] = {'present': 0, 'late': 0}
            branch_stats[branch]['present'] += 1
            if a.status == 'late':
                branch_stats[branch]['late'] += 1
        
        branches = list(branch_stats.keys())
        branch_present = [branch_stats[b]['present'] for b in branches]
        branch_late = [branch_stats[b]['late'] for b in branches]
        
        staff_attendance = {}
        for a in attendance_records:
            sid = a.staff_id
            if sid not in staff_attendance:
                staff_attendance[sid] = {'staff': a.staff, 'present': 0, 'late': 0}
            staff_attendance[sid]['present'] += 1
            if a.status == 'late':
                staff_attendance[sid]['late'] += 1
        
        top_performers = sorted(staff_attendance.values(), 
                               key=lambda x: (x['present'], -x['late']), reverse=True)[:5]
        needs_attention = sorted(staff_attendance.values(), 
                                key=lambda x: x['late'], reverse=True)[:5]
    else:
        total_staff = 0
        total_present = 0
        total_late = 0
        total_overtime = 0
        attendance_rate = 0
        late_rate = 0
        dates = []
        present_counts = []
        late_counts = []
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        late_by_day = [0] * 5
        departments = []
        dept_present = []
        dept_late = []
        branches = []
        branch_present = []
        branch_late = []
        top_performers = []
        needs_attention = []
    
    return render_template('analytics.html',
                         schools=schools,
                         organizations=organizations,
                         period=period,
                         selected_school=school_filter,
                         selected_org=org_filter,
                         start_date=start_date.strftime('%Y-%m-%d'),
                         end_date=end_date.strftime('%Y-%m-%d'),
                         total_staff=total_staff,
                         total_present=total_present,
                         total_late=total_late,
                         total_overtime=total_overtime,
                         attendance_rate=attendance_rate,
                         late_rate=late_rate,
                         dates=dates,
                         present_counts=present_counts,
                         late_counts=late_counts,
                         day_names=day_names,
                         late_by_day=late_by_day,
                         departments=departments,
                         dept_present=dept_present,
                         dept_late=dept_late,
                         branches=branches,
                         branch_present=branch_present,
                         branch_late=branch_late,
                         top_performers=top_performers,
                         needs_attention=needs_attention)

# Settings
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@super_admin_required
def settings():
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings()
        db.session.add(settings)
        db.session.commit()
    
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name')
        settings.logo_url = request.form.get('logo_url')
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=settings)

# API endpoints for kiosk
@app.route('/api/clock-in', methods=['POST'])
def api_clock_in():
    data = request.get_json()
    staff_id = data.get('staff_id')
    
    staff = Staff.query.filter_by(staff_id=staff_id).first()
    if not staff:
        return jsonify({'success': False, 'message': 'Staff not found'})
    
    today = datetime.now().date()
    existing = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Already clocked in today'})
    
    now = datetime.now()
    school = staff.school
    late_time = datetime.strptime(school.late_time or '08:15', '%H:%M').time()
    
    status = 'present'
    if now.time() > late_time:
        status = 'late'
        staff.late_count = (staff.late_count or 0) + 1
    
    attendance = Attendance(
        staff_id=staff.id,
        school_id=staff.school_id,
        date=today,
        clock_in=now,
        status=status
    )
    db.session.add(attendance)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Welcome {staff.first_name}!',
        'status': status,
        'time': now.strftime('%H:%M:%S')
    })

@app.route('/api/clock-out', methods=['POST'])
def api_clock_out():
    data = request.get_json()
    staff_id = data.get('staff_id')
    
    staff = Staff.query.filter_by(staff_id=staff_id).first()
    if not staff:
        return jsonify({'success': False, 'message': 'Staff not found'})
    
    today = datetime.now().date()
    attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    if not attendance:
        return jsonify({'success': False, 'message': 'No clock in record found'})
    
    if attendance.clock_out:
        return jsonify({'success': False, 'message': 'Already clocked out'})
    
    now = datetime.now()
    attendance.clock_out = now
    
    school = staff.school
    close_time = datetime.strptime(school.close_time or '17:00', '%H:%M').time()
    close_datetime = datetime.combine(today, close_time)
    
    if now > close_datetime:
        overtime = (now - close_datetime).seconds // 60
        attendance.overtime_minutes = overtime
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Goodbye {staff.first_name}!',
        'time': now.strftime('%H:%M:%S'),
        'overtime': attendance.overtime_minutes
    })

@app.route('/api/staff/<staff_id>')
def api_get_staff(staff_id):
    staff = Staff.query.filter_by(staff_id=staff_id).first()
    if not staff:
        return jsonify({'success': False, 'message': 'Staff not found'})
    
    return jsonify({
        'success': True,
        'staff': {
            'id': staff.staff_id,
            'name': f'{staff.first_name} {staff.last_name}',
            'department': staff.department,
            'photo_url': staff.photo_url
        }
    })

# Debug route
@app.route('/debug-db')
def debug_db():
    try:
        schools = School.query.all()
        staff = Staff.query.all()
        users = User.query.all()
        
        output = f"Schools: {len(schools)}\n"
        for s in schools:
            output += f"  - {s.id}: {s.name}\n"
        
        output += f"\nStaff: {len(staff)}\n"
        for st in staff:
            output += f"  - {st.first_name} {st.last_name} (school_id={st.school_id})\n"
        
        output += f"\nUsers: {len(users)}\n"
        for u in users:
            output += f"  - {u.username} (role={u.role}, schools={len(u.schools)})\n"
        
        return f"<pre>{output}</pre>"
    except Exception as e:
        return f"Error: {str(e)}"

# Database initialization
@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                role='super_admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
        
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(company_name='Attendance System')
            db.session.add(settings)
            db.session.commit()
        
        return 'Database initialized successfully! Default admin credentials: username=admin, password=admin123'
    except Exception as e:
        return f'Error: {str(e)}'

if __name__ == '__main__':
    app.run(debug=True)
