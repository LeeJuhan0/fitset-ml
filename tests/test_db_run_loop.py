from app.core import db


def test_run_reuses_one_loop():
    import asyncio

    async def current():
        return asyncio.get_running_loop()

    assert db.run(current()) is db.run(current())
