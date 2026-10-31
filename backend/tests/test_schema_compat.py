"""MySQL compatibility checks that do not need a MySQL server: the DDL must compile for the MySQL dialect."""
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.database import Base
import app.models  # noqa: F401


def test_every_table_compiles_for_mysql_with_innodb_friendly_types():
    ddl = []
    for table in Base.metadata.sorted_tables:
        ddl.append(str(CreateTable(table).compile(dialect=mysql.dialect())))
        ddl.extend(str(CreateIndex(i).compile(dialect=mysql.dialect())) for i in table.indexes)
    text = "\n".join(ddl)
    assert "VARCHAR(" in text and "CREATE TABLE appointments" in text
    assert "VARCHAR NOT NULL" not in text and "VARCHAR," not in text  # MySQL requires VARCHAR lengths


def test_expected_tables_exist():
    assert set(Base.metadata.tables) == {
        "roles", "users", "departments", "staff", "staff_availability", "visitors", "visit_logs",
        "appointments", "appointment_reminders", "faqs", "organization_info", "conversations", "messages", "notifications"}
