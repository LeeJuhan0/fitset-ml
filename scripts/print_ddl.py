import argparse

from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.core import db


def render(dialect_name: str) -> str:
    """엔티티 메타데이터로 CREATE TABLE·INDEX 문 생성"""
    db._register_models()
    dialect = {"mysql": mysql.dialect(), "sqlite": sqlite.dialect()}[dialect_name]
    out = []
    for table in SQLModel.metadata.sorted_tables:
        out.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in table.indexes:
            out.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        out.append("")
    return "\n".join(out)


def main():
    """CLI 인자, --dialect mysql|sqlite, 표준 출력"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialect", choices=["mysql", "sqlite"], default="mysql")
    args = ap.parse_args()
    print(render(args.dialect))


if __name__ == "__main__":
    main()
