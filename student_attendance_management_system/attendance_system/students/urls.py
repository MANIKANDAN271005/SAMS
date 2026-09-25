from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('students/', views.student_list, name='students'),
    path('students/<int:id>/edit/', views.update_student, name='update_student'),
    path('students/<int:id>/delete/', views.delete_student, name='delete_student'),
    path('attendance/', views.attendance, name='attendance'),
    path('leave/', views.leave_list, name='leave'),
    path('leave/<int:id>/delete/', views.delete_leave, name='delete_leave'),
    path('report/', views.report, name='report'),
    path('add-student/', views.add_student, name='add_student'),
    path('profile/', views.profile_view, name='profile'),
    path('settings/', views.settings_view, name='settings'),
]
