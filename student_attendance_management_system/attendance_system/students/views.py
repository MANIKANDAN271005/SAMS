import csv
import datetime
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from .forms import RegisterForm
from .helpers import (
    clear_dashboard_cache,
    get_dashboard_stats,
    get_form_value,
    get_monthly_trend,
    get_recent_reports,
    get_student_summaries,
    get_students_on_leave,
    parse_date,
    parse_int,
    summarize_attendance,
    validate_leave_data,
    validate_profile_image,
    validate_student_data,
)
from .models import Attendance, LeaveRecord, Student

User = get_user_model()
VALID_STATUSES = {choice for choice, _ in Attendance.STATUS_CHOICES}


def home_view(request):
    return render(request, 'home.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Your account has been created.')
        return redirect('dashboard')

    return render(request, 'register.html', {'form': form})


def wishlist_view(request):
    return render(request, 'wishlist.html')


def cart_view(request):
    return render(request, 'cart.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = AuthenticationForm(request, data=request.POST or None)
    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)

        if request.POST.get('remember_me'):
            request.session.set_expiry(60 * 60 * 24 * 30)
        else:
            request.session.set_expiry(0)

        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('dashboard')

    if request.method == 'POST':
        messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html', {'form': form, 'next': next_url})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been signed out securely.')
    return redirect('login')


@login_required(login_url='login')
def dashboard(request):
    today, stats = get_dashboard_stats()
    context = {
        **stats,
        'reports': get_recent_reports(limit=6),
        'today': today.strftime('%b %d, %Y'),
        'today_iso': today.strftime('%Y-%m-%d'),
    }
    return render(request, 'dashboard.html', context)


@login_required(login_url='login')
def attendance(request):
    today = timezone.localdate()
    source = request.POST if request.method == 'POST' else request.GET
    selected_date = parse_date(source.get('date'), today)
    year_filter = parse_int(source.get('class'))

    if selected_date > today:
        messages.warning(request, 'Attendance cannot be recorded for a future date.')
        selected_date = today

    students = Student.objects.order_by('name')
    if year_filter:
        students = students.filter(year=year_filter)

    if request.method == 'POST':
        saved = 0
        with transaction.atomic():
            for student in students:
                status = request.POST.get(f'status_{student.id}', '')
                if status in VALID_STATUSES:
                    Attendance.objects.update_or_create(
                        student=student, date=selected_date, defaults={'status': status}
                    )
                    saved += 1
        clear_dashboard_cache(selected_date)

        if saved:
            messages.success(request, f'Attendance saved for {saved} student(s) on {selected_date:%b %d, %Y}.')
        else:
            messages.warning(request, 'No attendance was marked. Choose Present, Absent or Leave for at least one student.')

        query = {'date': selected_date.isoformat()}
        if year_filter:
            query['class'] = year_filter
        return redirect(f"{reverse('attendance')}?{urlencode(query)}")

    records = dict(Attendance.objects.filter(date=selected_date).values_list('student_id', 'status'))
    on_leave_ids = get_students_on_leave(selected_date)

    student_rows = []
    for student in students:
        status = records.get(student.id, '')
        student_rows.append({
            'student': student,
            'status': status or (Attendance.LEAVE if student.id in on_leave_ids else ''),
            'saved': bool(status),
            'on_leave': student.id in on_leave_ids,
        })

    status_counts = {value: 0 for value in VALID_STATUSES}
    for row in student_rows:
        if row['saved']:
            status_counts[row['status']] += 1

    year_values = Student.objects.order_by('year').values_list('year', flat=True).distinct()
    classes = [{'id': year, 'name': f'Year {year}'} for year in year_values]

    context = {
        'student_rows': student_rows,
        'classes': classes,
        'selected_class': year_filter,
        'today': selected_date.isoformat(),
        'max_date': today.isoformat(),
        'total_students': len(student_rows),
        'present_count': status_counts[Attendance.PRESENT],
        'absent_count': status_counts[Attendance.ABSENT],
        'leave_count': status_counts[Attendance.LEAVE],
        'last_updated': selected_date.strftime('%b %d, %Y'),
    }
    return render(request, 'attendance.html', context)


@login_required(login_url='login')
def leave_list(request):
    errors, form_data = {}, {}

    if request.method == 'POST':
        errors, form_data, cleaned = validate_leave_data(request.POST)
        if not errors:
            with transaction.atomic():
                LeaveRecord.objects.create(**cleaned)
                # Past and current days of the leave are recorded as "Leave" in attendance;
                # future days are pre-filled on the attendance page when that day is taken.
                today = timezone.localdate()
                day = cleaned['start_date']
                while day <= min(cleaned['end_date'], today):
                    Attendance.objects.update_or_create(
                        student=cleaned['student'], date=day, defaults={'status': Attendance.LEAVE}
                    )
                    day += datetime.timedelta(days=1)
            clear_dashboard_cache()
            messages.success(request, f"Leave recorded for {cleaned['student'].name}.")
            return redirect('leave')

    leaves = LeaveRecord.objects.select_related('student')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        leaves = leaves.filter(
            Q(student__name__icontains=search_query)
            | Q(student__roll_no__icontains=search_query)
            | Q(reason__icontains=search_query)
        )

    today = timezone.localdate()
    context = {
        'leaves': leaves,
        'students': Student.objects.order_by('name').only('id', 'name', 'roll_no'),
        'errors': errors,
        'form_data': form_data,
        'query': search_query,
        'today': today.isoformat(),
        'total_leaves': LeaveRecord.objects.count(),
        'active_leaves': LeaveRecord.objects.filter(start_date__lte=today, end_date__gte=today).count(),
        'upcoming_leaves': LeaveRecord.objects.filter(start_date__gt=today).count(),
    }
    return render(request, 'leave.html', context)


@login_required(login_url='login')
@require_POST
def delete_leave(request, id):
    leave = get_object_or_404(LeaveRecord, id=id)
    leave.delete()
    messages.success(request, 'Leave record deleted. Attendance already saved for those dates was not changed.')
    return redirect('leave')


@login_required(login_url='login')
def report(request):
    today = timezone.localdate()
    start_date = parse_date(request.GET.get('start'))
    end_date = parse_date(request.GET.get('end'))
    year_filter = parse_int(request.GET.get('class'))
    department_filter = request.GET.get('department', '').strip()
    status_filter = request.GET.get('status', '').strip()
    search_query = request.GET.get('q', '').strip()

    records = Attendance.objects.select_related('student')
    if year_filter:
        records = records.filter(student__year=year_filter)
    if department_filter:
        records = records.filter(student__department__iexact=department_filter)
    if search_query:
        records = records.filter(Q(student__name__icontains=search_query) | Q(student__roll_no__icontains=search_query))

    # The trend chart ignores the date/status filters so it always shows the full year.
    trend_labels, trend_values = get_monthly_trend(records)

    if start_date:
        records = records.filter(date__gte=start_date)
    if end_date:
        records = records.filter(date__lte=end_date)
    summary_records = records
    if status_filter in VALID_STATUSES:
        records = records.filter(status=status_filter)
    records = records.order_by('-date', 'student__name')

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sams_attendance_{today.isoformat()}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Roll No', 'Student Name', 'Department', 'Year', 'Status'])
        for item in records:
            writer.writerow([item.date.isoformat(), item.student.roll_no, item.student.name,
                             item.student.department, item.student.year, item.status])
        return response

    summary = summarize_attendance(summary_records)
    page = Paginator(records, 25).get_page(request.GET.get('page'))
    filter_params = request.GET.copy()
    filter_params.pop('page', None)
    filter_params.pop('export', None)

    return render(
        request,
        'report.html',
        {
            'reports': page,
            'page_obj': page,
            'filter_query': filter_params.urlencode(),
            'student_summaries': get_student_summaries(summary_records),
            'attendance_percentage': summary['percentage'],
            'absent_percentage': summary['absent_percentage'],
            'leave_percentage': summary['leave_percentage'],
            'present_count': summary['present'],
            'absent_count': summary['absent'],
            'leave_count': summary['leave'],
            'report_count': summary['total'],
            'trend_labels': json.dumps(trend_labels),
            'trend_values': json.dumps(trend_values),
            'departments': Student.objects.order_by('department').values_list('department', flat=True).distinct(),
            'filters': {
                'start': start_date.isoformat() if start_date else '',
                'end': end_date.isoformat() if end_date else '',
                'class': year_filter or '',
                'department': department_filter,
                'status': status_filter,
                'q': search_query,
            },
            'has_filters': any([start_date, end_date, year_filter, department_filter, status_filter, search_query]),
            'today': today.strftime('%b %d, %Y'),
        },
    )


@login_required(login_url='login')
def student_list(request):
    queryset = Student.objects.annotate(attendance_count=Count('attendance')).order_by('name')

    search_query = request.GET.get('q', '').strip()
    year_filter = request.GET.get('class', '').strip()
    department_filter = request.GET.get('department', '').strip()
    attendance_filter = request.GET.get('attendance', '').strip()

    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) | Q(roll_no__icontains=search_query) | Q(department__icontains=search_query)
        )
    year_value = parse_int(year_filter)
    if year_value is not None:
        queryset = queryset.filter(year=year_value)
    if department_filter:
        queryset = queryset.filter(department__iexact=department_filter)
    if attendance_filter == 'recorded':
        queryset = queryset.filter(attendance_count__gt=0)
    elif attendance_filter == 'pending':
        queryset = queryset.filter(attendance_count=0)

    all_students = Student.objects.all()
    return render(
        request,
        'student_list.html',
        {
            'students': queryset,
            'query': search_query,
            'year_filter': year_filter,
            'department_filter': department_filter,
            'attendance_filter': attendance_filter,
            'departments': all_students.order_by('department').values_list('department', flat=True).distinct(),
            'total_students': all_students.count(),
            'recorded_students': all_students.filter(attendance__isnull=False).distinct().count(),
            'department_count': all_students.values('department').distinct().count(),
            'present_today': Attendance.objects.filter(date=timezone.localdate(), status=Attendance.PRESENT).count(),
        },
    )


@login_required(login_url='login')
def add_student(request):
    if request.method == 'POST':
        errors, form_data = validate_student_data(request.POST)
        uploaded_file = request.FILES.get('profile_image')
        image_error = validate_profile_image(uploaded_file)
        if image_error:
            errors['profile_image'] = image_error

        if errors:
            return render(request, 'add_student.html', {'errors': errors, 'form_data': form_data})

        Student.objects.create(
            roll_no=form_data['roll_no'],
            name=form_data['name'],
            department=form_data['department'],
            year=int(form_data['year']),
            email=form_data['email'],
            phone=form_data['phone'],
            profile_image=uploaded_file or '',
        )
        clear_dashboard_cache()
        messages.success(request, 'Student added successfully.')
        return redirect('students')

    return render(request, 'add_student.html', {'errors': {}, 'form_data': {}})


@login_required(login_url='login')
def update_student(request, id):
    student = get_object_or_404(Student, id=id)
    errors = {}
    form_data = {
        'roll_no': student.roll_no,
        'name': student.name,
        'department': student.department,
        'year': str(student.year),
        'email': student.email,
        'phone': student.phone,
    }

    if request.method == 'POST':
        errors, form_data = validate_student_data(request.POST, instance=student)
        uploaded_file = request.FILES.get('profile_image')
        image_error = validate_profile_image(uploaded_file)
        if image_error:
            errors['profile_image'] = image_error

        if not errors:
            student.roll_no = form_data['roll_no']
            student.name = form_data['name']
            student.department = form_data['department']
            student.year = int(form_data['year'])
            student.email = form_data['email']
            student.phone = form_data['phone']
            if uploaded_file is not None:
                if student.profile_image:
                    student.profile_image.delete(save=False)
                student.profile_image = uploaded_file
            student.save()
            messages.success(request, 'Student updated successfully.')
            return redirect('students')

    return render(request, 'update_student.html', {'student': student, 'errors': errors, 'form_data': form_data})


@login_required(login_url='login')
def profile_view(request):
    return render(request, 'profile.html', {'user': request.user})


@login_required(login_url='login')
def settings_view(request):
    user = request.user

    if request.method == 'POST':
        full_name = get_form_value(request.POST, 'full_name')
        email = get_form_value(request.POST, 'email')
        username = get_form_value(request.POST, 'username')

        try:
            User.username_validator(username)
            if email:
                validate_email(email)
        except ValidationError:
            valid = False
        else:
            valid = True

        if not username:
            messages.error(request, 'Username is required.')
        elif not valid:
            messages.error(request, 'Please enter a valid username and email address.')
        elif User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
            messages.error(request, 'That username is already taken.')
        else:
            first_name, _, last_name = full_name.partition(' ')
            user.first_name = first_name[:150]
            user.last_name = last_name.strip()[:150]
            user.email = email
            user.username = username
            user.save(update_fields=['first_name', 'last_name', 'email', 'username'])
            messages.success(request, 'Account details updated.')
            return redirect('settings')

    return render(request, 'settings.html', {'user': user})


@login_required(login_url='login')
@require_POST
def delete_student(request, id):
    student = get_object_or_404(Student, id=id)
    if student.profile_image:
        student.profile_image.delete(save=False)
    student.delete()
    clear_dashboard_cache()
    messages.success(request, 'Student deleted successfully.')
    return redirect('students')
