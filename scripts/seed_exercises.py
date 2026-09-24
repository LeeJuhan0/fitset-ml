import argparse

from app.core import db
from app.exercises.service import seed


def main():
    """인자 파싱, 마이그레이션된 DB 에 시드 실행"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    args = ap.parse_args()
    async def go():
        """마이그레이션 확인 후 시드 실행"""
        await db.require_tables("exercises")
        async with db.session() as s:
            return await seed(s, args.source)

    print(db.run(go()))


if __name__ == "__main__":
    main()
