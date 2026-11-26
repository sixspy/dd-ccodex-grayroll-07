"""失败测乙：求值把未确认的全量影子当成已全量。

事故残留：prod 上 feed.ranking_v3 被一键写成 100%，对比侧没有分步确认记录，
求值却全员命中。正确性口径：确认或分步后求值才全开；
未确认的全量（无确认账、无分步账）一律不放开。
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import app
from db import connect

PROD_ENV_ID = 3
SUBJECTS = ["u-1001", "u-2002", "u-3003", "u-4004", "u-5005"]


def _login(client, user, password):
    r = client.post("/api/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _ensure_flag(client, headers, key, title):
    for it in client.get("/api/flags", headers=headers).json()["items"]:
        if it["key"] == key:
            return it["id"]
    r = client.post("/api/flags", headers=headers, json={"key": key, "title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _plant_unconfirmed_full_rule(flag_id, env_id=PROD_ENV_ID):
    """直接落一笔无确认账的百分百正式规则，复刻事故残留（账实不符）。"""
    with connect() as conn:
        conn.execute(
            "DELETE FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1",
            (flag_id, env_id),
        )
        conn.execute(
            "INSERT INTO flag_rules(flag_id, env_id, kind, percent, cohort_id, version, official, updated_at) "
            "VALUES(?,?,?,?,NULL,?,1,?)",
            (flag_id, env_id, "percent", 100, 1, time.time()),
        )
        conn.commit()


def _eval_all(client, headers, flag_key, env_code="prod"):
    out = []
    for s in SUBJECTS:
        r = client.post(
            "/api/evaluate",
            headers=headers,
            json={"flag_key": flag_key, "env_code": env_code, "subject_key": s},
        )
        assert r.status_code == 200, r.text
        out.append(r.json())
    return out


def test_unconfirmed_full_rule_not_served_as_full():
    """失败测乙核心：无确认/分步账的百分百正式规则，求值不得当成已全量。"""
    key = "feed.ranking_v3_eval"
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, key, "信息流排序 v3 求值复现")
        _plant_unconfirmed_full_rule(fid)
        results = _eval_all(client, admin, key)
        assert all(r["enabled"] is False for r in results), (
            f"未确认全量不得命中任何主体，实际 {[(r['subject_key'], r['enabled']) for r in results]}"
        )
        assert all(r["reason"] == "prod_full_unconfirmed" for r in results), (
            f"未确认全量须给出阻断原因 prod_full_unconfirmed，实际 {[r['reason'] for r in results]}"
        )


def test_confirmed_full_shadow_opens_evaluation():
    """乙路径末端：影子全量经二次确认原子升正后，求值才全开。"""
    key = "feed.ranking_v3_eval_ok"
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        writer = _login(client, "writer", "writer123")
        fid = _ensure_flag(client, admin, key, "信息流排序 v3 确认全开")
        r = client.post(
            "/api/releases/publish",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": PROD_ENV_ID,
                "kind": "percent",
                "percent": 100,
                "summary": "影子全量，确认后升正",
                "use_shadow": True,
            },
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        c = client.post(f"/api/releases/shadow/{sid}/confirm", headers=writer, json={})
        assert c.status_code == 200, f"二次确认须可用，实际 {c.status_code} {c.text}"
        p = client.post(f"/api/releases/shadow/{sid}/promote", headers=admin, json={})
        assert p.status_code == 200, f"确认后须原子升正，实际 {p.status_code} {p.text}"
        results = _eval_all(client, admin, key)
        assert all(r["enabled"] is True for r in results), (
            f"确认升正后求值须全开，实际 {[(r['subject_key'], r['enabled']) for r in results]}"
        )


def test_stepwise_full_opens_evaluation_and_one_step_forbidden():
    """分步爬坡到 100% 求值才全开；一步打满是变相一键全量，须被生产闸拒写。"""
    key = "feed.ranking_v3_eval_steps"
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, key, "信息流排序 v3 分步全开")
        one = client.post(
            "/api/schedules",
            headers=admin,
            json={"flag_id": fid, "env_id": PROD_ENV_ID, "steps_json": '[{"percent":100}]', "note": "一步打满"},
        )
        assert one.status_code == 200, one.text
        jump = client.post(f"/api/schedules/{one.json()['id']}/apply-next", headers=admin, json={})
        assert jump.status_code == 409, (
            f"prod 一步打满须被生产闸拒写（禁止第三路），实际 {jump.status_code} {jump.text}"
        )
        two = client.post(
            "/api/schedules",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": PROD_ENV_ID,
                "steps_json": '[{"percent":10},{"percent":100}]',
                "note": "分步到全量",
            },
        )
        assert two.status_code == 200, two.text
        sid = two.json()["id"]
        s1 = client.post(f"/api/schedules/{sid}/apply-next", headers=admin, json={})
        assert s1.status_code == 200 and s1.json()["applied_percent"] == 10, s1.text
        s2 = client.post(f"/api/schedules/{sid}/apply-next", headers=admin, json={})
        assert s2.status_code == 200 and s2.json()["applied_percent"] == 100, s2.text
        results = _eval_all(client, admin, key)
        assert all(r["enabled"] is True for r in results), (
            f"分步到全量后求值须全开，实际 {[(r['subject_key'], r['enabled']) for r in results]}"
        )
