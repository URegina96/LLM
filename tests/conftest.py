import os

# Тесты не трогают настоящий Postgres: база — SQLite в памяти.
# conftest.py pytest читает раньше самих тестов, поэтому адрес подставится до импорта audit.store.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"