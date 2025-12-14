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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Database configuration - Use PostgreSQL on Render, SQLite locally
database_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')

# Fix for Render's postgres:// vs postgresql://
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class School(db.Model):
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
    staff = db.relationship('Staff', backref='school', lazy=True)
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='school_admin')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    times_late = db.Column(db.Integer, default=0)
    attendance = db.relationship('Attendance', backref='staff', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime, nullable=True)
    sign_out_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='present')
    is_late = db.Column(db.Boolean, default=False)
    late_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Role decorators
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

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
        total_staff = Staff.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today).count()
        late_today = Attendance.query.filter_by(date=today, is_late=True).count()
    elif current_user.role in ['hr_viewer', 'ceo_viewer']:
        schools = School.query.all()
        total_staff = Staff.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today).count()
        late_today = Attendance.query.filter_by(date=today, is_late=True).count()
    else:
        schools = [current_user.school] if current_user.school else []
        if current_user.school:
            total_staff = Staff.query.filter_by(school_id=current_user.school_id, is_active=True).count()
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
            today_attendance = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today).count()
            late_today = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today, Attendance.is_late == True).count()
        else:
            total_staff = 0
            today_attendance = 0
            late_today = 0
    
    return render_template('dashboard.html', 
                         schools=schools, 
                         total_staff=total_staff, 
                         today_attendance=today_attendance,
                         late_today=late_today)

# School Management
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
        api_key = secrets.token_hex(32)
        
        school = School(name=name, short_name=short_name, api_key=api_key)
        
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        
        db.session.add(school)
        db.session.commit()
        flash('School added successfully!', 'success')
        return redirect(url_for('schools'))
    
    return render_template('add_school.html')

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
        flash('School updated successfully!', 'success')
        return redirect(url_for('schools'))
    
    return render_template('edit_school.html', school=school)

@app.route('/schools/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('School deleted successfully!', 'success')
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

# Staff Management
@app.route('/staff')
@login_required
def staff_list():
    today = date.today()
    
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        staff = Staff.query.all()
    else:
        staff = Staff.query.filter_by(school_id=current_user.school_id).all()
    
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
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = [current_user.school]
    
    departments = ['Academic', 'Admin', 'Non-Academic', 'Management']
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
                
                if department not in ['Academic', 'Admin', 'Non-Academic', 'Management']:
                    department = 'Academic'
                
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

# User Management
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
        school_id = request.form.get('school_id') or None
        
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists!', 'danger')
            return redirect(url_for('add_user'))
        
        user = User(username=username, role=role, school_id=school_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('add_user.html', schools=schools, roles=roles)

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

# Reports
@app.route('/reports/attendance')
@login_required
def attendance_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter_by(date=datetime.strptime(selected_date, '%Y-%m-%d').date())
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    
    attendance = query.all()
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('attendance_report.html', 
                         attendance=attendance, 
                         schools=schools, 
                         selected_date=selected_date,
                         school_id=school_id)

@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter_by(date=datetime.strptime(selected_date, '%Y-%m-%d').date())
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    
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
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=attendance_{selected_date}.csv'}
    )

@app.route('/reports/late')
@login_required
def late_report():
    period = request.args.get('period', 'all')
    school_id = request.args.get('school_id', '')
    
    if period == 'today':
        start_date = date.today()
        end_date = date.today()
    elif period == 'week':
        start_date = date.today() - timedelta(days=date.today().weekday())
        end_date = date.today()
    elif period == 'month':
        start_date = date.today().replace(day=1)
        end_date = date.today()
    else:
        start_date = None
        end_date = None
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    staff_list = staff_query.all()
    
    late_staff = []
    for s in staff_list:
        if s.department == 'Management':
            continue
        
        att_query = Attendance.query.filter_by(staff_id=s.id)
        
        if start_date and end_date:
            att_query = att_query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
        
        total_attendance = att_query.count()
        late_count = att_query.filter_by(is_late=True).count()
        
        if s.times_late > 0 or late_count > 0:
            if total_attendance > 0:
                punctuality = round(((total_attendance - late_count) / total_attendance) * 100, 1)
                lateness = round((late_count / total_attendance) * 100, 1)
            else:
                punctuality = 100.0
                lateness = 0.0
            
            late_staff.append({
                'staff': s,
                'times_late': s.times_late if period == 'all' else late_count,
                'punctuality': punctuality,
                'lateness': lateness
            })
    
    late_staff.sort(key=lambda x: x['times_late'], reverse=True)
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('late_report.html', 
                         late_staff=late_staff, 
                         schools=schools, 
                         period=period,
                         school_id=school_id)

@app.route('/reports/late/download')
@login_required
def download_late_report():
    school_id = request.args.get('school_id', '')
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    staff_list = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
    
    for s in staff_list:
        if s.department == 'Management':
            continue
        
        total_attendance = Attendance.query.filter_by(staff_id=s.id).count()
        late_count = Attendance.query.filter_by(staff_id=s.id, is_late=True).count()
        
        if total_attendance > 0:
            punctuality = round(((total_attendance - late_count) / total_attendance) * 100, 1)
            lateness = round((late_count / total_attendance) * 100, 1)
        else:
            punctuality = 100.0
            lateness = 0.0
        
        if s.times_late > 0:
            writer.writerow([
                s.staff_id,
                s.name,
                s.school.short_name or s.school.name,
                s.department,
                s.times_late,
                punctuality,
                lateness
            ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=late_report_{date.today()}.csv'}
    )

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
        school_name = 'all schools'
    
    for s in staff:
        s.times_late = 0
    
    db.session.commit()
    flash(f'Late counters reset for {school_name}!', 'success')
    return redirect(url_for('late_report'))

@app.route('/reports/absent')
@login_required
def absent_report():
    selected_date = request.args.get('date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    check_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    
    if check_date.weekday() >= 5:
        flash('Selected date is a weekend. No attendance expected.', 'info')
        absent_staff = []
    else:
        staff_query = Staff.query.filter_by(is_active=True)
        
        if school_id:
            staff_query = staff_query.filter_by(school_id=school_id)
        elif current_user.role == 'school_admin':
            staff_query = staff_query.filter_by(school_id=current_user.school_id)
        
        all_staff = staff_query.all()
        
        absent_staff = []
        for s in all_staff:
            if s.department == 'Management':
                continue
            
            attendance = Attendance.query.filter_by(staff_id=s.id, date=check_date).first()
            if not attendance:
                absent_staff.append(s)
    
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('absent_report.html', 
                         absent_staff=absent_staff, 
                         schools=schools, 
                         selected_date=selected_date,
                         school_id=school_id)

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
            writer.writerow([
                s.staff_id,
                s.name,
                s.school.short_name or s.school.name,
                s.department
            ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=absent_{selected_date}.csv'}
    )

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
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    
    overtime = query.all()
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('overtime_report.html', 
                         overtime=overtime, 
                         schools=schools, 
                         selected_date=selected_date,
                         school_id=school_id)

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
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids))
    
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
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=overtime_{selected_date}.csv'}
    )

# API for Kiosk
@app.route('/api/sync', methods=['GET', 'POST', 'OPTIONS'])
def api_sync():
    # Handle preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        return response
    
    # Handle GET for testing
    if request.method == 'GET':
        response = jsonify({'status': 'API is working', 'message': 'Use POST with X-API-Key header'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    # Handle POST
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
        staff_list = [{'id': s.staff_id, 'name': s.name, 'department': s.department} for s in staff]
        response = jsonify({'staff': staff_list, 'school_name': school.name})
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
                        # Check if late
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
                                
                                # Update staff late counter
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
                        
                        # Calculate overtime
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
        
        response = jsonify({
            'success': True,
            'synced': synced,
            'errors': errors
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    elif action == 'check_status':
        staff_id = data.get('staff_id')
        staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
        
        if not staff:
            response = jsonify({'error': 'Staff not found'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 404
        
        today = date.today()
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
        
        if attendance:
            if attendance.sign_out_time:
                status = 'signed_out'
            else:
                status = 'signed_in'
        else:
            status = 'not_signed_in'
        
        response = jsonify({
            'staff_name': staff.name,
            'status': status
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    response = jsonify({'error': 'Invalid action'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 400

# Initialize database
with app.app_context():
    db.create_all()
    
    # Create default super admin if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='super_admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
@app.route('/init-db')
def init_db():
    db.create_all()
    # Create default admin if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='super_admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    return 'Database initialized!'
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

