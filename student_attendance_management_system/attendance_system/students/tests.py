import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, LeaveRecord, Student


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='admin', password='secret123')
        self.client.force_login(self.user)
        self.student = Student.objects.create(roll_no='S-1', name='Alice Johnson', department='Science', year=2)
        self.today = timezone.localdate()


class DatabaseConfigTests(TestCase):
    def test_database_is_named_sams(self):
        # Django swaps DATABASES NAME for a test database during tests, so check the configured name.
        self.assertEqual(settings.DB_NAME, 'SAMS')


class PageRenderTests(LoggedInTestCase):
    def test_all_pages_render(self):
        for name in ['dashboard', 'students', 'attendance', 'leave', 'report', 'add_student', 'profile', 'settings']:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_pages_require_login(self):
        self.client.logout()
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_login_redirects_to_dashboard(self):
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': 'admin', 'password': 'secret123'})
        self.assertRedirects(response, reverse('dashboard'))


class StudentCrudTests(LoggedInTestCase):
    def test_add_student(self):
        response = self.client.post(reverse('add_student'), {
            'roll_no': 'S-2', 'name': 'Bob Smith', 'department': 'Commerce', 'year': '1',
            'email': 'bob@example.com', 'phone': '555-123-4567',
        })
        self.assertRedirects(response, reverse('students'))
        student = Student.objects.get(roll_no='S-2')
        self.assertEqual(student.email, 'bob@example.com')

    def test_add_student_rejects_duplicate_roll(self):
        response = self.client.post(reverse('add_student'), {'roll_no': 's-1', 'name': 'Bob', 'department': 'Arts', 'year': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('roll_no', response.context['errors'])

    def test_update_student_keeps_own_roll_number(self):
        response = self.client.post(reverse('update_student', args=[self.student.id]), {
            'roll_no': 'S-1', 'name': 'Alice Brown', 'department': 'Science', 'year': '3',
        })
        self.assertRedirects(response, reverse('students'))
        self.student.refresh_from_db()
        self.assertEqual((self.student.name, self.student.year), ('Alice Brown', 3))

    def test_update_student_validates_year(self):
        response = self.client.post(reverse('update_student', args=[self.student.id]), {
            'roll_no': 'S-1', 'name': 'Alice', 'department': 'Science', 'year': 'abc',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('year', response.context['errors'])

    def test_delete_student(self):
        response = self.client.post(reverse('delete_student', args=[self.student.id]))
        self.assertRedirects(response, reverse('students'))
        self.assertFalse(Student.objects.exists())

    def test_student_list_ignores_invalid_class_filter(self):
        response = self.client.get(reverse('students'), {'class': 'abc'})
        self.assertEqual(response.status_code, 200)


class AttendanceTests(LoggedInTestCase):
    def test_save_present_absent_leave(self):
        other = Student.objects.create(roll_no='S-2', name='Bob', department='Arts', year=2)
        third = Student.objects.create(roll_no='S-3', name='Cara', department='Arts', year=2)
        response = self.client.post(reverse('attendance'), {
            'date': self.today.isoformat(),
            f'status_{self.student.id}': 'Present',
            f'status_{other.id}': 'Absent',
            f'status_{third.id}': 'Leave',
        })
        self.assertEqual(response.status_code, 302)
        statuses = dict(Attendance.objects.values_list('student_id', 'status'))
        self.assertEqual(statuses, {self.student.id: 'Present', other.id: 'Absent', third.id: 'Leave'})

    def test_saving_twice_updates_instead_of_duplicating(self):
        url = reverse('attendance')
        self.client.post(url, {'date': self.today.isoformat(), f'status_{self.student.id}': 'Present'})
        self.client.post(url, {'date': self.today.isoformat(), f'status_{self.student.id}': 'Absent'})
        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().status, 'Absent')

    def test_invalid_status_is_ignored(self):
        self.client.post(reverse('attendance'), {'date': self.today.isoformat(), f'status_{self.student.id}': 'Late'})
        self.assertFalse(Attendance.objects.exists())

    def test_dashboard_reflects_saved_attendance(self):
        self.client.get(reverse('dashboard'))  # warm the stats cache
        self.client.post(reverse('attendance'), {'date': self.today.isoformat(), f'status_{self.student.id}': 'Present'})
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['present_today'], 1)

    def test_student_on_leave_is_prefilled(self):
        LeaveRecord.objects.create(student=self.student, start_date=self.today, end_date=self.today, reason='Sick')
        response = self.client.get(reverse('attendance'))
        row = response.context['student_rows'][0]
        self.assertEqual(row['status'], 'Leave')
        self.assertTrue(row['on_leave'])


class LeaveTests(LoggedInTestCase):
    def test_create_leave_marks_past_days_as_leave(self):
        start = self.today - datetime.timedelta(days=2)
        end = self.today + datetime.timedelta(days=3)
        response = self.client.post(reverse('leave'), {
            'student': self.student.id, 'start_date': start.isoformat(), 'end_date': end.isoformat(), 'reason': 'Medical',
        })
        self.assertRedirects(response, reverse('leave'))
        self.assertEqual(LeaveRecord.objects.count(), 1)
        self.assertEqual(Attendance.objects.filter(status='Leave').count(), 3)

    def test_leave_end_before_start_is_rejected(self):
        response = self.client.post(reverse('leave'), {
            'student': self.student.id, 'start_date': self.today.isoformat(),
            'end_date': (self.today - datetime.timedelta(days=1)).isoformat(), 'reason': 'x',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('end_date', response.context['errors'])

    def test_delete_leave(self):
        leave = LeaveRecord.objects.create(student=self.student, start_date=self.today, end_date=self.today, reason='Trip')
        self.client.post(reverse('delete_leave', args=[leave.id]))
        self.assertFalse(LeaveRecord.objects.exists())


class ReportTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        Attendance.objects.create(student=self.student, date=self.today, status='Present')
        Attendance.objects.create(student=self.student, date=self.today - datetime.timedelta(days=1), status='Absent')
        Attendance.objects.create(student=self.student, date=self.today - datetime.timedelta(days=2), status='Leave')

    def test_report_summary(self):
        response = self.client.get(reverse('report'))
        self.assertEqual(response.context['report_count'], 3)
        self.assertEqual(response.context['leave_count'], 1)
        self.assertEqual(response.context['attendance_percentage'], 33.3)

    def test_report_status_filter(self):
        response = self.client.get(reverse('report'), {'status': 'Absent'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_report_csv_export(self):
        response = self.client.get(reverse('report'), {'export': 'csv'})
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertEqual(len(response.content.decode().strip().splitlines()), 4)


class AccountTests(TestCase):
    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'teacher', 'email': 'teacher@example.com',
            'password1': 'Str0ng-Passw0rd!', 'password2': 'Str0ng-Passw0rd!',
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(get_user_model().objects.filter(username='teacher').exists())

    def test_settings_updates_account(self):
        user = get_user_model().objects.create_user(username='admin', password='secret123')
        self.client.force_login(user)
        self.client.post(reverse('settings'), {'full_name': 'Jane Doe', 'email': 'jane@example.com', 'username': 'admin'})
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name, user.email), ('Jane', 'Doe', 'jane@example.com'))


class StudentUpdateFlowTests(TestCase):
    def test_update_student_page_renders_for_existing_student(self):
        user = get_user_model().objects.create_user(username='admin', password='secret123')
        student = Student.objects.create(
            roll_no='S-100',
            name='Alice Johnson',
            department='Science',
            year=2,
        )

        self.client.force_login(user)
        response = self.client.get(reverse('update_student', args=[student.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'update_student.html')


class ProfileAndSettingsPageTests(TestCase):
    def test_profile_page_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='admin', password='secret123')

        self.client.force_login(user)
        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'profile.html')

    def test_settings_page_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='admin', password='secret123')

        self.client.force_login(user)
        response = self.client.get(reverse('settings'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'settings.html')


class PrimeBasketRoutingTests(TestCase):
    def test_home_page_renders_primebasket_home_template(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

    def test_login_page_renders_primebasket_login_template(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')

    def test_register_page_renders_primebasket_register_template(self):
        response = self.client.get(reverse('register'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')

    def test_wishlist_page_renders_primebasket_wishlist_template(self):
        response = self.client.get(reverse('wishlist'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wishlist.html')

    def test_cart_page_renders_primebasket_cart_template(self):
        response = self.client.get(reverse('cart'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'cart.html')
