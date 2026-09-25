import datetime
import re

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from .models import Attendance, LeaveRecord, Student

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9\s()-]{7,15}$")
NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ .,'-]{2,100}$")
ROLL_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,20}$")
DEPARTMENT_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ0-9 .,'-]{2,50}$")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_LEAVE_DAYS = 90


def get_form_value(post_data, field_name):
    return (post_data.get(field_name, '') or '').strip()


def parse_date(value, default=None):
    try:
        return datetime.date.fromisoformat((value or '').strip())
    except ValueError:
        return default


def parse_int(value, default=None):
    try:
        return int((value or '').strip())
    except (TypeError, ValueError):
        return default


def validate_student_data(post_data, instance=None):
    errors = {}
    form_data = {
        'roll_no': get_form_value(post_data, 'roll_no'),
        'name': get_form_value(post_data, 'name'),
        'department': get_form_value(post_data, 'department'),
        'year': get_form_value(post_data, 'year'),
        'email': get_form_value(post_data, 'email'),
        'phone': get_form_value(post_data, 'phone'),
    }

    duplicate_roll = Student.objects.filter(roll_no__iexact=form_data['roll_no'])
    if instance is not None:
        duplicate_roll = duplicate_roll.exclude(pk=instance.pk)

    if not form_data['roll_no']:
        errors['roll_no'] = 'Roll number is required.'
    elif not ROLL_PATTERN.match(form_data['roll_no']):
        errors['roll_no'] = 'Roll number contains invalid characters.'
    elif duplicate_roll.exists():
        errors['roll_no'] = 'A student with this roll number already exists.'

    if not form_data['name']:
        errors['name'] = 'Student name is required.'
    elif not NAME_PATTERN.match(form_data['name']):
        errors['name'] = 'Student name contains unsupported characters.'
    elif len(form_data['name']) < 2:
        errors['name'] = 'Student name must be at least 2 characters long.'

    if not form_data['department']:
        errors['department'] = 'Department is required.'
    elif not DEPARTMENT_PATTERN.match(form_data['department']):
        errors['department'] = 'Department contains unsupported characters.'

    if not form_data['year']:
        errors['year'] = 'Please select a year.'
    else:
        year_value = parse_int(form_data['year'])
        if year_value is None:
            errors['year'] = 'Year must be a valid number.'
        elif year_value not in {1, 2, 3, 4}:
            errors['year'] = 'Year must be between 1 and 4.'

    if form_data['email'] and not EMAIL_PATTERN.match(form_data['email']):
        errors['email'] = 'Please enter a valid email address.'

    if form_data['phone'] and not PHONE_PATTERN.match(form_data['phone']):
        errors['phone'] = 'Please enter a valid phone number.'

    return errors, form_data


def validate_profile_image(uploaded_file):
    if uploaded_file is None:
        return None
    if uploaded_file.size > MAX_IMAGE_SIZE:
        return 'Profile image must be 5MB or smaller.'
    if not (uploaded_file.content_type or '').startswith('image/'):
        return 'Profile image must be a valid image file.'
    return None


def validate_leave_data(post_data):
    errors = {}
    form_data = {
        'student': get_form_value(post_data, 'student'),
        'start_date': get_form_value(post_data, 'start_date'),
        'end_date': get_form_value(post_data, 'end_date'),
        'reason': get_form_value(post_data, 'reason'),
    }

    student = Student.objects.filter(pk=parse_int(form_data['student'])).first()
    if student is None:
        errors['student'] = 'Please select a student.'

    start_date = parse_date(form_data['start_date'])
    end_date = parse_date(form_data['end_date'])
    if start_date is None:
        errors['start_date'] = 'Please enter a valid start date.'
    if end_date is None:
        errors['end_date'] = 'Please enter a valid end date.'
    if start_date and end_date:
        if end_date < start_date:
            errors['end_date'] = 'End date cannot be before the start date.'
        elif (end_date - start_date).days + 1 > MAX_LEAVE_DAYS:
            errors['end_date'] = f'A single leave record cannot exceed {MAX_LEAVE_DAYS} days.'

    if not form_data['reason']:
        errors['reason'] = 'Please enter a reason for the leave.'
    elif len(form_data['reason']) > 255:
        errors['reason'] = 'Reason must be 255 characters or fewer.'

    cleaned = {'student': student, 'start_date': start_date, 'end_date': end_date, 'reason': form_data['reason']}
    return errors, form_data, cleaned


def get_students_on_leave(date):
    return set(
        LeaveRecord.objects.filter(start_date__lte=date, end_date__gte=date).values_list('student_id', flat=True)
    )


def dashboard_cache_key(date):
    return f'dashboard_stats:{date}'


def clear_dashboard_cache(date=None):
    cache.delete(dashboard_cache_key(date or timezone.localdate()))


def get_dashboard_stats():
    today = timezone.localdate()
    cache_key = dashboard_cache_key(today)
    stats = cache.get(cache_key)

    if stats is None:
        counts = Attendance.objects.filter(date=today).aggregate(
            present=Count('id', filter=Q(status=Attendance.PRESENT)),
            absent=Count('id', filter=Q(status=Attendance.ABSENT)),
            leave=Count('id', filter=Q(status=Attendance.LEAVE)),
        )
        stats = {
            'total_students': Student.objects.count(),
            'present_today': counts['present'],
            'absent_today': counts['absent'],
            'leave_today': counts['leave'],
        }
        cache.set(cache_key, stats, 60)

    return today, stats


def get_recent_reports(limit=8):
    return (
        Attendance.objects.select_related('student')
        .only('id', 'date', 'status', 'student__id', 'student__name', 'student__roll_no')
        .order_by('-date', '-id')[:limit]
    )


def summarize_attendance(queryset):
    counts = queryset.aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(status=Attendance.PRESENT)),
        absent=Count('id', filter=Q(status=Attendance.ABSENT)),
        leave=Count('id', filter=Q(status=Attendance.LEAVE)),
    )
    total = counts['total']
    counts['percentage'] = round(counts['present'] / total * 100, 1) if total else 0
    counts['absent_percentage'] = round(counts['absent'] / total * 100, 1) if total else 0
    counts['leave_percentage'] = round(counts['leave'] / total * 100, 1) if total else 0
    return counts


def get_student_summaries(queryset):
    rows = (
        queryset.values('student_id', 'student__roll_no', 'student__name', 'student__department')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status=Attendance.PRESENT)),
            absent=Count('id', filter=Q(status=Attendance.ABSENT)),
            leave=Count('id', filter=Q(status=Attendance.LEAVE)),
        )
        .order_by('student__name')
    )
    summaries = []
    for row in rows:
        row['percentage'] = round(row['present'] / row['total'] * 100, 1) if row['total'] else 0
        summaries.append(row)
    return summaries


def get_monthly_trend(queryset, months=12):
    """Present percentage for each of the last `months` months (oldest first)."""
    today = timezone.localdate()
    month_starts = []
    year, month = today.year, today.month
    for _ in range(months):
        month_starts.append(datetime.date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_starts.reverse()

    rows = queryset.filter(date__gte=month_starts[0]).values_list('date', 'status')
    totals = {start: [0, 0] for start in month_starts}
    for date, status in rows:
        bucket = totals.get(date.replace(day=1))
        if bucket is not None:
            bucket[0] += 1
            if status == Attendance.PRESENT:
                bucket[1] += 1

    labels = [start.strftime('%b %Y') for start in month_starts]
    values = [round(present / total * 100, 1) if total else 0 for total, present in totals.values()]
    return labels, values
