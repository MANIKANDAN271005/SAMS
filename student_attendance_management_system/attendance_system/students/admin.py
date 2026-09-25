from django.contrib import admin

from .models import Attendance, LeaveRecord, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('roll_no', 'name', 'department', 'year')
    search_fields = ('roll_no', 'name', 'department')
    list_filter = ('year', 'department')


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'status')
    list_filter = ('status', 'date')
    search_fields = ('student__name', 'student__roll_no')


@admin.register(LeaveRecord)
class LeaveRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'start_date', 'end_date', 'reason')
    search_fields = ('student__name', 'student__roll_no', 'reason')
