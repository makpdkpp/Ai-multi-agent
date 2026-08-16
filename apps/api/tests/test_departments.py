import pytest
from pydantic import ValidationError

from agentdesk_api.api.departments import DepartmentCreate, DepartmentUpdate


def test_department_create_normalizes_code_and_name() -> None:
    department = DepartmentCreate(code=" Sales-TH ", name=" ฝ่ายขาย ")

    assert department.code == "sales-th"
    assert department.name == "ฝ่ายขาย"
    assert department.timezone == "Asia/Bangkok"
    assert department.retention_days == 90


@pytest.mark.parametrize("code", ["1sales", "sales_team", "s", "Sales Team"])
def test_department_rejects_invalid_code(code: str) -> None:
    with pytest.raises(ValidationError):
        DepartmentCreate(code=code, name="Sales")


def test_department_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError):
        DepartmentUpdate(timezone="Bangkok/Unknown")


def test_department_rejects_retention_outside_policy() -> None:
    with pytest.raises(ValidationError):
        DepartmentCreate(code="sales", name="Sales", retention_days=0)
