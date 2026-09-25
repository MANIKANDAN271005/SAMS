try:
    import pymysql  # noqa: F401
    pymysql.install_as_MySQLdb()
except ImportError:
    pass