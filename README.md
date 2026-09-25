# SAMS - Student Attendance Management System

A Django web app to manage students, mark attendance (Present / Absent / Leave), keep leave records and view attendance reports.

## Features

- Student add / edit / delete (with email, phone and photo)
- Daily attendance: Present, Absent, Leave, with bulk "Mark All Present"
- Leave records, which are applied to attendance automatically
- Reports with filters, a student-wise summary, a monthly trend chart, CSV export and print
- Login, registration, profile and account settings

## Requirements

- Python 3.10 or newer
- Git

## Setup (Windows)

```bat
git clone https://github.com/MANIKANDAN271005/SAMS.git
cd SAMS
python -m venv .venv
.venv\Scripts\activate
cd student_attendance_management_system\attendance_system
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with the user you created.

On macOS or Linux, activate the environment with `source .venv/bin/activate` instead.

## Database

The database is named **SAMS**. By default it is the SQLite file `SAMS.sqlite3`, created next to `manage.py` by `migrate`.

To use MySQL instead, create a database called `SAMS` and set these environment variables before running:

```bat
set SAMS_DB_ENGINE=mysql
set SAMS_DB_USER=root
set SAMS_DB_PASSWORD=yourpassword
set SAMS_DB_HOST=localhost
set SAMS_DB_PORT=3306
```

## Running the tests

```bat
python manage.py test students
```
