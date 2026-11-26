"""环境目录（含生产闸元数据：风险级联查结果与全量策略）。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect
from policies import is_prod_grade

router = APIRouter(prefix="/api/envs", tags=["envs"])

FULL_POLICY_GATED = "禁一键全量：全量意图只进影子全量草案，二次确认或分步爬坡后求值才全开"
FULL_POLICY_OPEN = "标准灰度：可按比例发布"


def _annotate(row: dict) -> dict:
    gated = is_prod_grade(row)
    row["prod_gate"] = gated
    row["full_policy"] = FULL_POLICY_GATED if gated else FULL_POLICY_OPEN
    return row


@router.get("")
def list_envs(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = [
            _annotate(dict(r))
            for r in conn.execute("SELECT * FROM environments ORDER BY risk_level, id").fetchall()
        ]
    return {"items": rows}


@router.get("/{env_id}")
def get_env(env_id: int, authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        row = conn.execute("SELECT * FROM environments WHERE id=?", (env_id,)).fetchone()
    if not row:
        raise HTTPException(404, detail="环境不存在")
    return _annotate(dict(row))
