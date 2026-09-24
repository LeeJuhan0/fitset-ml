import argparse

from app.core import db
from app.exercises.schemas import SeedRequest
from app.exercises.service import seed


def main():
    """인자 파싱, 테이블 생성, 시드 실행"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    args = ap.parse_args()
    async def go():
        """테이블 생성 후 시드 실행"""
        await db.init_db()
        async with db.session() as s:
            return await seed(s, SeedRequest(source=args.source))

    print(db.run(go()))


if __name__ == "__main__":
    main()
