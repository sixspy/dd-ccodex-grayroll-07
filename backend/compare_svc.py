"""正式规则 vs 影子草案对比（含全量确认/分步记录与放行账核对）。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect
from policies import is_prod_grade
from validators import require_int

router = APIRouter(prefix="/api/compare", tags=["compare"])


@router.get("/flag/{flag_id}/env/{env_id}")
def compare_flag_env(flag_id: int, env_id: int, authorization: str | None = Header(default=None)):
    current_user(authorization)
    fid = require_int(flag_id, "开关", 1)
    eid = require_int(env_id, "环境", 1)
    with connect() as conn:
        fl = conn.execute("SELECT id, key, title, status FROM flags WHERE id=?", (fid,)).fetchone()
        env = conn.execute("SELECT id, code, title, risk_level FROM environments WHERE id=?", (eid,)).fetchone()
        if not fl or not env:
            raise HTTPException(404, detail="开关或环境不存在")
        official = conn.execute(
            "SELECT * FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1", (fid, eid)
        ).fetchone()
        rule_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM rule_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        release_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM release_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        kill_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM kill_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        recent_releases = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM releases WHERE flag_id=? AND env_id=? AND official=1 ORDER BY id DESC LIMIT 5",
                (fid, eid),
            ).fetchall()
        ]
        full_open_grants = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM full_open_grants WHERE flag_id=? AND env_id=? ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        confirm_records = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM change_history WHERE flag_id=? AND env_id=? AND action='full_confirm' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        step_records = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM change_history WHERE flag_id=? AND env_id=? AND action='schedule_step' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
    diffs = []
    if official and release_shadows:
        sh = release_shadows[0]
        for field in ("kind", "percent", "cohort_id"):
            if official[field] != sh.get(field):
                diffs.append({"field": field, "official": official[field], "shadow": sh.get(field)})
    official_full_gate = None
    if official and int(official["percent"]) >= 100:
        official_full_gate = {
            "prod_grade": is_prod_grade(env),
            "percent": official["percent"],
            "version": official["version"],
            "granted": any(g["version"] == official["version"] for g in full_open_grants),
        }
    return {
        "flag": dict(fl),
        "env": dict(env),
        "official_rule": dict(official) if official else None,
        "open_rule_shadows": rule_shadows,
        "open_release_shadows": release_shadows,
        "open_kill_shadows": kill_shadows,
        "recent_releases": recent_releases,
        "diffs": diffs,
        "has_pending_shadow": bool(rule_shadows or release_shadows or kill_shadows),
        "full_open_grants": full_open_grants,
        "confirm_records": confirm_records,
        "step_records": step_records,
        "official_full_gate": official_full_gate,
    }


@router.get("/matrix")
def compare_matrix(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        flags = [dict(r) for r in conn.execute("SELECT id, key, status FROM flags ORDER BY id").fetchall()]
        envs = [dict(r) for r in conn.execute("SELECT id, code FROM environments ORDER BY risk_level").fetchall()]
        rules = {
            (r["flag_id"], r["env_id"]): dict(r)
            for r in conn.execute("SELECT * FROM flag_rules WHERE official=1").fetchall()
        }
        matrix = []
        for f in flags:
            row = {"flag_id": f["id"], "flag_key": f["key"], "status": f["status"], "cells": []}
            for e in envs:
                rule = rules.get((f["id"], e["id"]))
                row["cells"].append(
                    {
                        "env_id": e["id"],
                        "env_code": e["code"],
                        "has_rule": rule is not None,
                        "percent": rule["percent"] if rule else None,
                        "version": rule["version"] if rule else None,
                        "kind": rule["kind"] if rule else None,
                    }
                )
            matrix.append(row)
    return {"envs": envs, "matrix": matrix}
