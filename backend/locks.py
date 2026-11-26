"""行锁与争用痕（嵌进发布/熔断主写路径）。"""
from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])
TTL = 20.0

_UPSERT = (
    "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?) "
    "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at "
    "WHERE row_locks.expires_at<=? OR row_locks.holder=?"
)


def _lose(conn, key: str, holder: str, winner: str, now: float) -> None:
    """败方只写争用痕，随后 409；不得触碰正式账。

    争用痕走独立连接落账：调用方连接可能带着抢锁失败的事务现场，
    在其上写痕会被 SQLite 死锁规避立即拒绝。
    """
    try:
        with connect() as mark_conn:
            mark_conn.execute(
                "INSERT INTO contention_marks(lock_key, loser, winner, created_at) VALUES(?,?,?,?)",
                (key, holder, winner, now),
            )
            mark_conn.commit()
    except sqlite3.OperationalError:
        pass  # 争用痕尽力而为，不阻塞 409
    raise HTTPException(409, detail="发布锁争用，请稍后重试")


def acquire(conn, key: str, holder: str) -> None:
    """原子抢「生产发布互斥」：先读已落库的锁行，再单条 UPSERT...WHERE 一锤定音。

    胜方的锁行立即落库，其他连接立即可见；败方只写争用痕后 409。
    抢锁写语句 busy_timeout=0 一次定胜负——若排队等待，败方的判定语句会
    滑到胜方放锁之后才执行，互斥形同虚设（无锁双成的根因）。
    """
    now = time.time()
    row = conn.execute("SELECT * FROM row_locks WHERE lock_key=?", (key,)).fetchone()
    if row and row["expires_at"] > now and row["holder"] != holder:
        _lose(conn, key, holder, row["holder"], now)
    conn.execute("PRAGMA busy_timeout=0")
    try:
        cur = conn.execute(_UPSERT, (key, holder, now + TTL, now, holder))
        got = cur.rowcount == 1
    except sqlite3.OperationalError:
        got = False
    finally:
        conn.execute("PRAGMA busy_timeout=5000")
    if not got:
        conn.rollback()  # 清掉抢锁失败的事务现场：避免与胜方提交互等成死锁
        row = conn.execute("SELECT holder FROM row_locks WHERE lock_key=?", (key,)).fetchone()
        _lose(conn, key, holder, row["holder"] if row else "unknown", now)
    conn.commit()  # 锁立即落库，其他连接立即可见


def release(conn, key: str, holder: str) -> None:
    conn.execute("DELETE FROM row_locks WHERE lock_key=? AND holder=?", (key, holder))


@router.get("/contention")
def list_contention(authorization: str | None = Header(default=None), limit: int = 40):
    current_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contention_marks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
