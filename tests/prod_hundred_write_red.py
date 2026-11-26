"""失败测甲：prod 一键百分百仍建成正式发布与规则。

夹具「prod 环境一键百分百发布尝试」：feed.ranking_v3 对 prod 一次打满 100%。
正确性口径（乙路径，当日封死，禁止第三路）：
  全量意图只进影子全量草案，二次确认后才原子升正，此前正式零改；
  一键直写正式 → 整笔拒写发布与规则，违者正式零增。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import app

# 点名夹具：prod 环境一键百分百发布尝试
PROD_ONE_CLICK_FULL_ATTEMPT = {
    "name": "prod 环境一键百分百发布尝试",
    "flag_key": "feed.ranking_v3",
    "flag_title": "信息流排序 v3",
    "env_id": 3,  # prod（风险级 3）
    "kind": "percent",
    "percent": 100,
    "summary": "prod 环境一键百分百发布尝试",
    "use_shadow": False,
}


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


def _official_ledger(client, headers, flag_id, env_id):
    """正式账：(正式发布笔数, 正式规则笔数, 其中百分百规则笔数)。"""
    rels = client.get("/api/releases", headers=headers).json()["official"]
    rules = client.get("/api/rules", headers=headers).json()["official"]
    n_rel = sum(1 for r in rels if r["flag_id"] == flag_id and r["env_id"] == env_id)
    n_rule = sum(1 for r in rules if r["flag_id"] == flag_id and r["env_id"] == env_id)
    n_full = sum(
        1
        for r in rules
        if r["flag_id"] == flag_id and r["env_id"] == env_id and int(r["percent"]) >= 100
    )
    return n_rel, n_rule, n_full


def test_prod_one_click_hundred_rejected_official_zero_gain():
    """失败测甲核心：prod 且比例一百 → 整笔拒写发布与规则，违者正式零增。"""
    fx = PROD_ONE_CLICK_FULL_ATTEMPT
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, fx["flag_key"], fx["flag_title"])
        before = _official_ledger(client, admin, fid, fx["env_id"])
        r = client.post(
            "/api/releases/publish",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": fx["env_id"],
                "kind": fx["kind"],
                "percent": fx["percent"],
                "summary": fx["summary"],
                "use_shadow": False,
            },
        )
        assert r.status_code == 409, (
            f"{fx['name']}：一键全量须被生产闸整笔拒写，实际 {r.status_code} {r.text}"
        )
        after = _official_ledger(client, admin, fid, fx["env_id"])
        assert after == before, f"{fx['name']}：违者须正式零增，实际账 {before} → {after}"


def test_full_intent_only_enters_shadow_draft():
    """乙路径：全量意图只进影子全量草案，升正前正式零改。"""
    fx = PROD_ONE_CLICK_FULL_ATTEMPT
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, fx["flag_key"], fx["flag_title"])
        before = _official_ledger(client, admin, fid, fx["env_id"])
        r = client.post(
            "/api/releases/publish",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": fx["env_id"],
                "kind": fx["kind"],
                "percent": fx["percent"],
                "summary": fx["summary"] + "（影子）",
                "use_shadow": True,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "shadow"
        after = _official_ledger(client, admin, fid, fx["env_id"])
        assert after == before, f"影子全量草案不得改动正式账，实际 {before} → {after}"
        shadows = client.get("/api/releases", headers=admin).json()["shadows"]
        sh = next(s for s in shadows if s["id"] == r.json()["id"])
        assert sh["status"] == "open" and int(sh["percent"]) == 100


def test_unconfirmed_shadow_promote_rejected():
    """未二次确认的全量影子不得升正：升正即拒，正式零增。"""
    fx = PROD_ONE_CLICK_FULL_ATTEMPT
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, fx["flag_key"], fx["flag_title"])
        r = client.post(
            "/api/releases/publish",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": fx["env_id"],
                "kind": fx["kind"],
                "percent": fx["percent"],
                "summary": fx["summary"] + "（未确认即升正）",
                "use_shadow": True,
            },
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        before = _official_ledger(client, admin, fid, fx["env_id"])
        p = client.post(f"/api/releases/shadow/{sid}/promote", headers=admin, json={})
        assert p.status_code == 409, f"未确认的全量影子升正须被拒，实际 {p.status_code} {p.text}"
        after = _official_ledger(client, admin, fid, fx["env_id"])
        assert after == before, f"未确认升正须正式零增，实际账 {before} → {after}"


def test_confirmed_shadow_promote_atomic():
    """二次确认后才原子升正：影子 → 他人确认 → 升正 → 正式生效。"""
    fx = PROD_ONE_CLICK_FULL_ATTEMPT
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        writer = _login(client, "writer", "writer123")
        fid = _ensure_flag(client, admin, fx["flag_key"], fx["flag_title"])
        r = client.post(
            "/api/releases/publish",
            headers=admin,
            json={
                "flag_id": fid,
                "env_id": fx["env_id"],
                "kind": fx["kind"],
                "percent": fx["percent"],
                "summary": fx["summary"] + "（确认后升正）",
                "use_shadow": True,
            },
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        c = client.post(f"/api/releases/shadow/{sid}/confirm", headers=writer, json={})
        assert c.status_code == 200, f"二次确认须可用（四眼），实际 {c.status_code} {c.text}"
        assert c.json()["status"] == "confirmed"
        before = _official_ledger(client, admin, fid, fx["env_id"])
        p = client.post(f"/api/releases/shadow/{sid}/promote", headers=admin, json={})
        assert p.status_code == 200, f"确认后须原子升正，实际 {p.status_code} {p.text}"
        assert p.json()["mode"] == "official"
        after = _official_ledger(client, admin, fid, fx["env_id"])
        # 正式发布是流水账：升正须 +1 笔。
        assert after[0] == before[0] + 1, f"确认升正须新增一笔正式发布，实际账 {before} → {after}"
        # 正式规则按 (开关,环境) 唯一：升正是整笔替换，笔数不增，但须落成为百分百。
        assert after[1] == before[1], f"正式规则须整笔替换而非另起一笔，实际账 {before} → {after}"
        rules = client.get("/api/rules", headers=admin).json()["official"]
        rule = next(r for r in rules if r["flag_id"] == fid and r["env_id"] == fx["env_id"])
        assert int(rule["percent"]) == 100 and rule["version"] == p.json()["version"]
        # 账实同源：放行账须与正式规则同版本，对比侧可查。
        cmp_body = client.get(f"/api/compare/flag/{fid}/env/{fx['env_id']}", headers=admin).json()
        gate = cmp_body["official_full_gate"]
        assert gate and gate["granted"] is True, f"确认升正须有同版放行账，实际 {gate}"
        assert any(g["source"] == "confirmed_shadow" for g in cmp_body["full_open_grants"])
