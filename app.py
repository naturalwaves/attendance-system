from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import csv
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Association table for User-School many-to-many relationship
user_schools = db.Table('user_schools',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('school.id'), primary_key=True)
)

# Models
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Attendance System')
    logo_url = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    logo_url = db.Column(db.String(500), nullable=True)
    start_time = db.Column(db.String(10), default='08:00')
    late_time = db.Column(db.String(10), default='08:15')
    close_time = db.Column(db.String(10), default='17:00')
    is_active = db.Column(db.Boolean, default=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)
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
    
    def get_accessible_organizations(self):
        if self.role == 'super_admin':
            return Organization.query.filter_by(is_active=True).all()
        else:
            org_ids = set()
            for school in self.schools:
                if school.organization_id:
                    org_ids.add(school.organization_id)
            return Organization.query.filter(Organization.id.in_(org_ids), Organization.is_active == True).all()

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
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
    settings = SystemSettings.query.first()
    return dict(now=now, system_settings=settings)

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
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        total_schools = len(schools)
        total_staff = Staff.query.filter_by(is_active=True).count()
        total_users = User.query.filter_by(is_active=True).count()
    else:
        schools = current_user.schools
        total_schools = len(schools)
        school_ids = [s.id for s in schools]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
        total_users = None
    
    school_ids = [s.id for s in schools]
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == today
    ).count()
    
    school_stats = []
    for school in schools:
        staff_count = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        today_present = Attendance.query.filter_by(school_id=school.id, date=today).count()
        attendance_rate = (today_present / staff_count * 100) if staff_count > 0 else 0
        school_stats.append({
            'school': school,
            'staff_count': staff_count,
            'today_present': today_present,
            'attendance_rate': round(attendance_rate, 1)
        })
    
    return render_template('dashboard.html',
                         total_schools=total_schools,
                         total_staff=total_staff,
                         total_users=total_users,
                         today_attendance=today_attendance,
                         school_stats=school_stats)

# Schools/Branches Management
@app.route('/schools')
@login_required
def schools():
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.schools
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('schools.html', schools=schools, organizations=organizations)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school = School(
            name=request.form.get('name'),
            address=request.form.get('address'),
            logo_url=request.form.get('logo_url'),
            start_time=request.form.get('start_time', '08:00'),
            late_time=request.form.get('late_time', '08:15'),
            close_time=request.form.get('close_time', '17:00'),
            organization_id=request.form.get('organization_id') or None
        )
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if current_user.role != 'super_admin' and school not in current_user.schools:
        flash('Access denied', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.address = request.form.get('address')
        school.logo_url = request.form.get('logo_url')
        school.start_time = request.form.get('start_time', '08:00')
        school.late_time = request.form.get('late_time', '08:15')
        school.close_time = request.form.get('close_time', '17:00')
        school.organization_id = request.form.get('organization_id') or None
        school.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('edit_school.html', school=school, organizations=organizations)

# Organization Management
@app.route('/organizations')
@login_required
def organizations():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    orgs = Organization.query.all()
    return render_template('organizations.html', organizations=orgs)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
def add_organization():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
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

@app.route('/organizations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_organization(id):
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    org = Organization.query.get_or_404(id)
    
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url')
        org.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('edit_organization.html', organization=org)

# Staff Management
@app.route('/staff')
@login_required
def staff_list():
    if current_user.role == 'super_admin':
        staff = Staff.query.all()
        schools = School.query.filter_by(is_active=True).all()
    else:
        school_ids = [s.id for s in current_user.schools]
        staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
        schools = current_user.schools
    
    return render_template('staff_list.html', staff=staff, schools=schools)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        
        if current_user.role != 'super_admin':
            school_ids = [s.id for s in current_user.schools]
            if int(school_id) not in school_ids:
                flash('Access denied', 'danger')
                return redirect(url_for('staff_list'))
        
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            photo_url=request.form.get('photo_url'),
            school_id=school_id
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    
    return render_template('add_staff.html', schools=schools)

@app.route('/staff/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if current_user.role != 'super_admin':
        school_ids = [s.id for s in current_user.schools]
        if staff.school_id not in school_ids:
            flash('Access denied', 'danger')
            return redirect(url_for('staff_list'))
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if request.method == 'POST':
        staff.staff_id = request.form.get('staff_id')
        staff.name = request.form.get('name')
        staff.email = request.form.get('email')
        staff.phone = request.form.get('phone')
        staff.department = request.form.get('department')
        staff.position = request.form.get('position')
        staff.photo_url = request.form.get('photo_url')
        staff.school_id = request.form.get('school_id')
        staff.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('staff_list'))
    
    return render_template('edit_staff.html', staff=staff, schools=schools)

@app.route('/staff/upload', methods=['GET', 'POST'])
@login_required
def upload_staff():
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        
        if current_user.role != 'super_admin':
            school_ids = [s.id for s in current_user.schools]
            if int(school_id) not in school_ids:
                flash('Access denied', 'danger')
                return redirect(url_for('staff_list'))
        
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(url_for('upload_staff'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(url_for('upload_staff'))
        
        if file and file.filename.endswith('.csv'):
            try:
                stream = io.StringIO(file.stream.read().decode('UTF8'), newline=None)
                csv_reader = csv.DictReader(stream)
                count = 0
                for row in csv_reader:
                    existing = Staff.query.filter_by(staff_id=row.get('staff_id', '').strip()).first()
                    if not existing:
                        staff = Staff(
                            staff_id=row.get('staff_id', '').strip(),
                            name=row.get('name', '').strip(),
                            email=row.get('email', '').strip(),
                            phone=row.get('phone', '').strip(),
                            department=row.get('department', '').strip(),
                            position=row.get('position', '').strip(),
                            school_id=school_id
                        )
                        db.session.add(staff)
                        count += 1
                db.session.commit()
                flash(f'{count} staff members uploaded successfully!', 'success')
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'danger')
        else:
            flash('Please upload a CSV file', 'danger')
        
        return redirect(url_for('staff_list'))
    
    return render_template('upload_staff.html', schools=schools)

# User Management
@app.route('/users')
@login_required
def users():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    schools = School.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        school_ids = request.form.getlist('schools')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('add_user'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('add_user'))
        
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        
        for school_id in school_ids:
            school = School.query.get(school_id)
            if school:
                user.schools.append(school)
        
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    
    return render_template('add_user.html', schools=schools)

@app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(id)
    schools = School.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role')
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
    
    return render_template('edit_user.html', user=user, schools=schools)

# Reports
@app.route('/reports/attendance')
@login_required
def attendance_report():
    if current_user.role not in ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_school_id = request.args.get('school_id', type=int)
    selected_organization_id = request.args.get('organization_id', type=int)
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        selected_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        organizations = current_user.get_accessible_organizations()
        schools = [s for s in current_user.schools if s.is_active]
    else:
        schools = [s for s in current_user.schools if s.is_active]
        organizations = []
    
    if selected_organization_id:
        schools = [s for s in schools if s.organization_id == selected_organization_id]
    
    if selected_school_id:
        school_ids = [selected_school_id]
        selected_school = School.query.get(selected_school_id)
    else:
        school_ids = [s.id for s in schools]
        selected_school = None
    
    attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == selected_date
    ).all()
    
    total = len(attendance)
    on_time = sum(1 for a in attendance if a.status == 'on_time')
    late = sum(1 for a in attendance if a.status == 'late')
    
    return render_template('attendance_report.html',
                         attendance=attendance,
                         selected_date=date_str,
                         schools=schools,
                         organizations=organizations,
                         selected_school_id=selected_school_id,
                         selected_organization_id=selected_organization_id,
                         selected_school=selected_school,
                         total=total,
                         on_time=on_time,
                         late=late)

@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_school_id = request.args.get('school_id', type=int)
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        selected_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if selected_school_id:
        school_ids = [selected_school_id]
    else:
        school_ids = [s.id for s in schools]
    
    attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == selected_date
    ).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Date', 'Clock In', 'Clock Out', 'Status'])
    
    for record in attendance:
        writer.writerow([
            record.staff.staff_id,
            record.staff.name,
            record.school.name,
            record.date.strftime('%Y-%m-%d'),
            record.clock_in.strftime('%H:%M:%S') if record.clock_in else '',
            record.clock_out.strftime('%H:%M:%S') if record.clock_out else '',
            record.status
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=attendance_{date_str}.csv'}
    )

@app.route('/reports/late')
@login_required
def late_report():
    if current_user.role not in ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_school_id = request.args.get('school_id', type=int)
    selected_organization_id = request.args.get('organization_id', type=int)
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        organizations = current_user.get_accessible_organizations()
        schools = [s for s in current_user.schools if s.is_active]
    else:
        schools = [s for s in current_user.schools if s.is_active]
        organizations = []
    
    if selected_organization_id:
        schools = [s for s in schools if s.organization_id == selected_organization_id]
    
    if selected_school_id:
        school_ids = [selected_school_id]
        selected_school = School.query.get(selected_school_id)
    else:
        school_ids = [s.id for s in schools]
        selected_school = None
    
    staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).all()
    
    late_staff = []
    for staff in staff_list:
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                period_attendance = Attendance.query.filter(
                    Attendance.staff_id == staff.id,
                    Attendance.date >= start,
                    Attendance.date <= end
                )
                period_total = period_attendance.count()
                
                if period_total == 0:
                    continue
                
                period_late = period_attendance.filter(Attendance.status == 'late').count()
                period_on_time = period_total - period_late
                punctuality = (period_on_time / period_total * 100) if period_total > 0 else 100
            except:
                period_late = 0
                period_total = 0
                punctuality = 100
        else:
            period_late = staff.late_count
            period_total = Attendance.query.filter_by(staff_id=staff.id).count()
            period_on_time = period_total - period_late
            punctuality = (period_on_time / period_total * 100) if period_total > 0 else 100
        
        late_staff.append({
            'staff': staff,
            'late_count': period_late if start_date and end_date else staff.late_count,
            'total_attendance': period_total,
            'punctuality': round(punctuality, 1)
        })
    
    late_staff.sort(key=lambda x: x['late_count'], reverse=True)
    
    return render_template('late_report.html',
                         late_staff=late_staff,
                         start_date=start_date,
                         end_date=end_date,
                         schools=schools,
                         organizations=organizations,
                         selected_school_id=selected_school_id,
                         selected_organization_id=selected_organization_id,
                         selected_school=selected_school)

@app.route('/reports/late/download')
@login_required
def download_late_report():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_school_id = request.args.get('school_id', type=int)
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if selected_school_id:
        school_ids = [selected_school_id]
    else:
        school_ids = [s.id for s in schools]
    
    staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Late Count', 'Total Attendance', 'Punctuality %'])
    
    for staff in staff_list:
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                period_attendance = Attendance.query.filter(
                    Attendance.staff_id == staff.id,
                    Attendance.date >= start,
                    Attendance.date <= end
                )
                period_total = period_attendance.count()
                
                if period_total == 0:
                    continue
                
                period_late = period_attendance.filter(Attendance.status == 'late').count()
                late_count = period_late
            except:
                period_total = Attendance.query.filter_by(staff_id=staff.id).count()
                late_count = staff.late_count
        else:
            period_total = Attendance.query.filter_by(staff_id=staff.id).count()
            late_count = staff.late_count
        
        period_on_time = period_total - late_count
        punctuality = (period_on_time / period_total * 100) if period_total > 0 else 100
        
        writer.writerow([
            staff.staff_id,
            staff.name,
            staff.school.name,
            staff.department,
            late_count,
            period_total,
            round(punctuality, 1)
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=late_report.csv'}
    )

@app.route('/reports/late/reset', methods=['POST'])
@login_required
def reset_late_counters():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('late_report'))
    
    school_id = request.form.get('school_id', type=int)
    
    if school_id:
        staff = Staff.query.filter_by(school_id=school_id).all()
    else:
        staff = Staff.query.all()
    
    for s in staff:
        s.late_count = 0
    
    db.session.commit()
    flash('Late counters have been reset!', 'success')
    return redirect(url_for('late_report'))

@app.route('/reports/absent')
@login_required
def absent_report():
    if current_user.role not in ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_school_id = request.args.get('school_id', type=int)
    selected_organization_id = request.args.get('organization_id', type=int)
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        selected_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        organizations = current_user.get_accessible_organizations()
        schools = [s for s in current_user.schools if s.is_active]
    else:
        schools = [s for s in current_user.schools if s.is_active]
        organizations = []
    
    if selected_organization_id:
        schools = [s for s in schools if s.organization_id == selected_organization_id]
    
    if selected_school_id:
        school_ids = [selected_school_id]
        selected_school = School.query.get(selected_school_id)
    else:
        school_ids = [s.id for s in schools]
        selected_school = None
    
    all_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).all()
    
    present_staff_ids = db.session.query(Attendance.staff_id).filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == selected_date
    ).all()
    present_staff_ids = [p[0] for p in present_staff_ids]
    
    absent_staff = [s for s in all_staff if s.id not in present_staff_ids]
    
    return render_template('absent_report.html',
                         absent_staff=absent_staff,
                         selected_date=date_str,
                         schools=schools,
                         organizations=organizations,
                         selected_school_id=selected_school_id,
                         selected_organization_id=selected_organization_id,
                         selected_school=selected_school)

@app.route('/reports/absent/download')
@login_required
def download_absent_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    selected_school_id = request.args.get('school_id', type=int)
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        selected_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if selected_school_id:
        school_ids = [selected_school_id]
    else:
        school_ids = [s.id for s in schools]
    
    all_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).all()
    
    present_staff_ids = db.session.query(Attendance.staff_id).filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date == selected_date
    ).all()
    present_staff_ids = [p[0] for p in present_staff_ids]
    
    absent_staff = [s for s in all_staff if s.id not in present_staff_ids]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Position'])
    
    for staff in absent_staff:
        writer.writerow([
            staff.staff_id,
            staff.name,
            staff.school.name,
            staff.department,
            staff.position
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=absent_{date_str}.csv'}
    )

@app.route('/reports/overtime')
@login_required
def overtime_report():
    if current_user.role not in ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_school_id = request.args.get('school_id', type=int)
    selected_organization_id = request.args.get('organization_id', type=int)
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        organizations = current_user.get_accessible_organizations()
        schools = [s for s in current_user.schools if s.is_active]
    else:
        schools = [s for s in current_user.schools if s.is_active]
        organizations = []
    
    if selected_organization_id:
        schools = [s for s in schools if s.organization_id == selected_organization_id]
    
    if selected_school_id:
        school_ids = [selected_school_id]
        selected_school = School.query.get(selected_school_id)
    else:
        school_ids = [s.id for s in schools]
        selected_school = None
    
    query = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.overtime_minutes > 0
    )
    
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Attendance.date >= start, Attendance.date <= end)
        except:
            pass
    
    overtime_records = query.all()
    
    staff_overtime = {}
    for record in overtime_records:
        if record.staff_id not in staff_overtime:
            staff_overtime[record.staff_id] = {
                'staff': record.staff,
                'total_minutes': 0,
                'days': 0
            }
        staff_overtime[record.staff_id]['total_minutes'] += record.overtime_minutes
        staff_overtime[record.staff_id]['days'] += 1
    
    overtime_list = list(staff_overtime.values())
    overtime_list.sort(key=lambda x: x['total_minutes'], reverse=True)
    
    return render_template('overtime_report.html',
                         overtime=overtime_list,
                         start_date=start_date,
                         end_date=end_date,
                         schools=schools,
                         organizations=organizations,
                         selected_school_id=selected_school_id,
                         selected_organization_id=selected_organization_id,
                         selected_school=selected_school)

@app.route('/reports/overtime/download')
@login_required
def download_overtime_report():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_school_id = request.args.get('school_id', type=int)
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
    else:
        schools = current_user.schools
    
    if selected_school_id:
        school_ids = [selected_school_id]
    else:
        school_ids = [s.id for s in schools]
    
    query = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.overtime_minutes > 0
    )
    
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Attendance.date >= start, Attendance.date <= end)
        except:
            pass
    
    overtime_records = query.all()
    
    staff_overtime = {}
    for record in overtime_records:
        if record.staff_id not in staff_overtime:
            staff_overtime[record.staff_id] = {
                'staff': record.staff,
                'total_minutes': 0,
                'days': 0
            }
        staff_overtime[record.staff_id]['total_minutes'] += record.overtime_minutes
        staff_overtime[record.staff_id]['days'] += 1
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Total Overtime (mins)', 'Total Overtime (hrs)', 'Days'])
    
    for data in staff_overtime.values():
        staff = data['staff']
        writer.writerow([
            staff.staff_id,
            staff.name,
            staff.school.name,
            staff.department,
            data['total_minutes'],
            round(data['total_minutes'] / 60, 2),
            data['days']
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=overtime_report.csv'}
    )

# Analytics
@app.route('/reports/analytics')
@login_required
def analytics():
    if current_user.role not in ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    period = request.args.get('period', 'this_week')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    selected_organization_id = request.args.get('organization_id', type=int)
    selected_school_id = request.args.get('school_id', type=int)
    
    today = datetime.now().date()
    
    if period == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except:
            start_date = today - timedelta(days=today.weekday())
            end_date = today
    elif period == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = start_date + timedelta(days=6)
    elif period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'last_month':
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif period == '90':
        start_date = today - timedelta(days=90)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
        period = '30'
    
    if current_user.role == 'super_admin':
        all_schools = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        organizations = current_user.get_accessible_organizations()
        all_schools = School.query.filter_by(is_active=True).filter(
            School.id.in_([s.id for s in current_user.schools])
        ).all()
    else:
        all_schools = list(current_user.schools)
        organizations = []
    
    schools = all_schools.copy() if isinstance(all_schools, list) else list(all_schools)
    
    if selected_organization_id:
        schools = [s for s in schools if s.organization_id == selected_organization_id]
    
    if selected_school_id:
        schools = [s for s in schools if s.id == selected_school_id]
    
    school_ids = [s.id for s in schools]
    
    staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True)
    total_staff = staff_query.count()
    branch_count = len(schools)
    
    attendance_query = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    total_records = attendance_query.count()
    
    total_days = 0
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            total_days += 1
        current_date += timedelta(days=1)
    
    total_possible = total_staff * total_days
    attendance_rate = (total_records / total_possible * 100) if total_possible > 0 else 0
    
    on_time_records = attendance_query.filter(Attendance.status == 'on_time').count()
    punctuality_rate = (on_time_records / total_records * 100) if total_records > 0 else 0
    
    period_days = (end_date - start_date).days + 1
    prev_start = start_date - timedelta(days=period_days)
    prev_end = start_date - timedelta(days=1)
    
    prev_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date >= prev_start,
        Attendance.date <= prev_end
    )
    prev_total = prev_attendance.count()
    
    prev_total_days = 0
    current_date = prev_start
    while current_date <= prev_end:
        if current_date.weekday() < 5:
            prev_total_days += 1
        current_date += timedelta(days=1)
    
    prev_possible = total_staff * prev_total_days
    prev_attendance_rate = (prev_total / prev_possible * 100) if prev_possible > 0 else 0
    attendance_trend = attendance_rate - prev_attendance_rate
    
    prev_on_time = prev_attendance.filter(Attendance.status == 'on_time').count()
    prev_punctuality_rate = (prev_on_time / prev_total * 100) if prev_total > 0 else 0
    punctuality_trend = punctuality_rate - prev_punctuality_rate
    
    trend_labels = []
    trend_data = []
    punctuality_data = []
    
    current_date = start_date
    while current_date <= end_date:
        trend_labels.append(current_date.strftime('%b %d'))
        
        day_attendance = Attendance.query.filter(
            Attendance.school_id.in_(school_ids),
            Attendance.date == current_date
        ).count()
        
        day_on_time = Attendance.query.filter(
            Attendance.school_id.in_(school_ids),
            Attendance.date == current_date,
            Attendance.status == 'on_time'
        ).count()
        
        day_rate = (day_attendance / total_staff * 100) if total_staff > 0 else 0
        day_punctuality = (day_on_time / day_attendance * 100) if day_attendance > 0 else 0
        
        trend_data.append(round(day_rate, 1))
        punctuality_data.append(round(day_punctuality, 1))
        
        current_date += timedelta(days=1)
    
    late_by_day = [0, 0, 0, 0, 0, 0, 0]
    late_records = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.status == 'late'
    ).all()
    
    for record in late_records:
        day_of_week = record.date.weekday()
        late_by_day[day_of_week] += 1
    
    departments = db.session.query(Staff.department).filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True,
        Staff.department.isnot(None),
        Staff.department != ''
    ).distinct().all()
    
    department_labels = []
    department_data = []
    
    for dept in departments:
        dept_name = dept[0]
        if dept_name:
            dept_staff = Staff.query.filter(
                Staff.school_id.in_(school_ids),
                Staff.department == dept_name,
                Staff.is_active == True
            ).all()
            
            dept_staff_ids = [s.id for s in dept_staff]
            dept_attendance = Attendance.query.filter(
                Attendance.staff_id.in_(dept_staff_ids),
                Attendance.date >= start_date,
                Attendance.date <= end_date
            ).count()
            
            dept_possible = len(dept_staff) * total_days
            dept_rate = (dept_attendance / dept_possible * 100) if dept_possible > 0 else 0
            
            department_labels.append(dept_name)
            department_data.append(round(dept_rate, 1))
    
    branch_labels = []
    branch_attendance = []
    branch_punctuality = []
    
    for school in schools:
        branch_labels.append(school.name[:20])
        
        school_staff_count = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        school_attendance = Attendance.query.filter(
            Attendance.school_id == school.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        school_total = school_attendance.count()
        school_on_time = school_attendance.filter(Attendance.status == 'on_time').count()
        
        school_possible = school_staff_count * total_days
        school_att_rate = (school_total / school_possible * 100) if school_possible > 0 else 0
        school_punct_rate = (school_on_time / school_total * 100) if school_total > 0 else 0
        
        branch_attendance.append(round(school_att_rate, 1))
        branch_punctuality.append(round(school_punct_rate, 1))
    
    top_performers = []
    all_staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).all()
    
    staff_performance = []
    for staff in all_staff_list:
        staff_attendance = Attendance.query.filter(
            Attendance.staff_id == staff.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        total = staff_attendance.count()
        if total > 0:
            on_time = staff_attendance.filter(Attendance.status == 'on_time').count()
            punctuality = (on_time / total * 100)
            staff_performance.append({
                'name': staff.name,
                'branch': staff.school.name if staff.school else 'N/A',
                'punctuality': punctuality,
                'total': total
            })
    
    staff_performance.sort(key=lambda x: (-x['punctuality'], -x['total']))
    top_performers = staff_performance[:5]
    
    needs_attention = []
    for staff in all_staff_list:
        late_count = Attendance.query.filter(
            Attendance.staff_id == staff.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date,
            Attendance.status == 'late'
        ).count()
        
        if late_count > 0:
            needs_attention.append({
                'name': staff.name,
                'branch': staff.school.name if staff.school else 'N/A',
                'late_count': late_count
            })
    
    needs_attention.sort(key=lambda x: -x['late_count'])
    needs_attention = needs_attention[:5]
    
    return render_template('analytics.html',
        period=period,
        start_date=start_date_str or start_date.strftime('%Y-%m-%d'),
        end_date=end_date_str or end_date.strftime('%Y-%m-%d'),
        organizations=organizations,
        selected_organization_id=selected_organization_id,
        schools=all_schools,
        selected_school_id=selected_school_id,
        attendance_rate=attendance_rate,
        attendance_trend=attendance_trend,
        punctuality_rate=punctuality_rate,
        punctuality_trend=punctuality_trend,
        total_staff=total_staff,
        branch_count=branch_count,
        total_records=total_records,
        trend_labels=trend_labels,
        trend_data=trend_data,
        punctuality_data=punctuality_data,
        late_by_day=late_by_day,
        department_labels=department_labels,
        department_data=department_data,
        branch_labels=branch_labels,
        branch_attendance=branch_attendance,
        branch_punctuality=branch_punctuality,
        top_performers=top_performers,
        needs_attention=needs_attention
    )

# Settings
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings()
        db.session.add(settings)
        db.session.commit()
    
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name', 'Attendance System')
        settings.logo_url = request.form.get('logo_url', '')
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=settings)

# Kiosk
@app.route('/kiosk/<int:school_id>')
def kiosk(school_id):
    school = School.query.get_or_404(school_id)
    return render_template('kiosk.html', school=school)

# API Endpoints
@app.route('/api/sync', methods=['POST'])
def api_sync():
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    action = data.get('action')
    school_id = data.get('school_id')
    
    if not school_id:
        return jsonify({'error': 'School ID required'}), 400
    
    school = School.query.get(school_id)
    if not school:
        return jsonify({'error': 'School not found'}), 404
    
    if action == 'get_staff':
        staff = Staff.query.filter_by(school_id=school_id, is_active=True).all()
        staff_list = [{
            'id': s.id,
            'staff_id': s.staff_id,
            'name': s.name,
            'department': s.department,
            'position': s.position,
            'photo_url': s.photo_url
        } for s in staff]
        return jsonify({'staff': staff_list, 'school': {
            'name': school.name,
            'start_time': school.start_time,
            'late_time': school.late_time,
            'close_time': school.close_time
        }})
    
    elif action == 'clock_in':
        staff_id = data.get('staff_id')
        staff = Staff.query.get(staff_id)
        
        if not staff:
            return jsonify({'error': 'Staff not found'}), 404
        
        today = datetime.now().date()
        existing = Attendance.query.filter_by(staff_id=staff_id, date=today).first()
        
        if existing:
            return jsonify({'error': 'Already clocked in today', 'attendance': {
                'clock_in': existing.clock_in.strftime('%H:%M:%S') if existing.clock_in else None
            }}), 400
        
        now = datetime.now()
        late_time = datetime.strptime(school.late_time, '%H:%M').time()
        
        if now.time() > late_time:
            status = 'late'
            staff.late_count += 1
        else:
            status = 'on_time'
        
        attendance = Attendance(
            staff_id=staff_id,
            school_id=school_id,
            date=today,
            clock_in=now,
            status=status
        )
        db.session.add(attendance)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Clock in successful - {status.replace("_", " ").title()}',
            'attendance': {
                'clock_in': now.strftime('%H:%M:%S'),
                'status': status
            }
        })
    
    elif action == 'clock_out':
        staff_id = data.get('staff_id')
        staff = Staff.query.get(staff_id)
        
        if not staff:
            return jsonify({'error': 'Staff not found'}), 404
        
        today = datetime.now().date()
        attendance = Attendance.query.filter_by(staff_id=staff_id, date=today).first()
        
        if not attendance:
            return jsonify({'error': 'No clock in record for today'}), 400
        
        if attendance.clock_out:
            return jsonify({'error': 'Already clocked out today'}), 400
        
        now = datetime.now()
        attendance.clock_out = now
        
        close_time = datetime.strptime(school.close_time, '%H:%M').time()
        close_datetime = datetime.combine(today, close_time)
        
        if now > close_datetime:
            overtime = (now - close_datetime).seconds // 60
            attendance.overtime_minutes = overtime
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Clock out successful',
            'attendance': {
                'clock_out': now.strftime('%H:%M:%S'),
                'overtime_minutes': attendance.overtime_minutes
            }
        })
    
    elif action == 'sync_offline':
        records = data.get('records', [])
        synced = 0
        errors = []
        
        for record in records:
            try:
                staff_id = record.get('staff_id')
                date_str = record.get('date')
                clock_in_str = record.get('clock_in')
                clock_out_str = record.get('clock_out')
                
                record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                existing = Attendance.query.filter_by(staff_id=staff_id, date=record_date).first()
                
                if not existing:
                    staff = Staff.query.get(staff_id)
                    if not staff:
                        errors.append(f'Staff {staff_id} not found')
                        continue
                    
                    clock_in = datetime.strptime(f'{date_str} {clock_in_str}', '%Y-%m-%d %H:%M:%S')
                    late_time = datetime.strptime(school.late_time, '%H:%M').time()
                    
                    if clock_in.time() > late_time:
                        status = 'late'
                        staff.late_count += 1
                    else:
                        status = 'on_time'
                    
                    attendance = Attendance(
                        staff_id=staff_id,
                        school_id=school_id,
                        date=record_date,
                        clock_in=clock_in,
                        status=status
                    )
                    
                    if clock_out_str:
                        clock_out = datetime.strptime(f'{date_str} {clock_out_str}', '%Y-%m-%d %H:%M:%S')
                        attendance.clock_out = clock_out
                        
                        close_time = datetime.strptime(school.close_time, '%H:%M').time()
                        close_datetime = datetime.combine(record_date, close_time)
                        
                        if clock_out > close_datetime:
                            overtime = (clock_out - close_datetime).seconds // 60
                            attendance.overtime_minutes = overtime
                    
                    db.session.add(attendance)
                    synced += 1
                elif not existing.clock_out and clock_out_str:
                    clock_out = datetime.strptime(f'{date_str} {clock_out_str}', '%Y-%m-%d %H:%M:%S')
                    existing.clock_out = clock_out
                    
                    close_time = datetime.strptime(school.close_time, '%H:%M').time()
                    close_datetime = datetime.combine(record_date, close_time)
                    
                    if clock_out > close_datetime:
                        overtime = (clock_out - close_datetime).seconds // 60
                        existing.overtime_minutes = overtime
                    
                    synced += 1
            except Exception as e:
                errors.append(str(e))
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'synced': synced,
            'errors': errors
        })
    
    elif action == 'check_status':
        staff_id = data.get('staff_id')
        today = datetime.now().date()
        
        attendance = Attendance.query.filter_by(staff_id=staff_id, date=today).first()
        
        if attendance:
            return jsonify({
                'clocked_in': True,
                'clocked_out': attendance.clock_out is not None,
                'clock_in': attendance.clock_in.strftime('%H:%M:%S') if attendance.clock_in else None,
                'clock_out': attendance.clock_out.strftime('%H:%M:%S') if attendance.clock_out else None,
                'status': attendance.status
            })
        else:
            return jsonify({
                'clocked_in': False,
                'clocked_out': False
            })
    
    return jsonify({'error': 'Invalid action'}), 400

# Database initialization
@app.route('/init-db')
def init_db():
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
    
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings(company_name='Attendance System')
        db.session.add(settings)
    
    db.session.commit()
    
    return 'Database initialized successfully! Default admin credentials: username=admin, password=admin123'

if __name__ == '__main__':
    app.run(debug=True)
