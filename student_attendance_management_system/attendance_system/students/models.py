from django.db import models


class Student(models.Model):
    roll_no = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=100, db_index=True)
    department = models.CharField(max_length=50, db_index=True)
    year = models.IntegerField(db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    profile_image = models.FileField(upload_to='students/', blank=True)

    def __str__(self):
        return self.name


class Attendance(models.Model):
    PRESENT = 'Present'
    ABSENT = 'Absent'
    LEAVE = 'Leave'
    STATUS_CHOICES = [
        (PRESENT, 'Present'),
        (ABSENT, 'Absent'),
        (LEAVE, 'Leave'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, db_index=True)
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['student', 'date'], name='unique_attendance_per_student_per_day'),
        ]

    def __str__(self):
        return self.student.name


class LeaveRecord(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='leave_records')
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date', '-id']

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return f'{self.student.name} ({self.start_date} - {self.end_date})'
