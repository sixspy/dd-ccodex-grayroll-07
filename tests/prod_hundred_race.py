"""争用失败测：两路抢「生产发布互斥」无锁双成。

会话对打：admin 与 writer 同时抢同一开关的 prod 发布互斥锁。
正确性口径：胜方唯一正式成功，败方只写争用痕（409 + contention_marks），
不得无锁双成。
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

import releases_svc
from app import app

MUTEX_NAME = "生产发布互斥"
PROD_ENV_ID = 3


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


def _official_release_count(client, headers, flag_id, env_id):
    rels = client.get("/api/releases", headers=headers).json()["official"]
    return sum(1 for r in rels if r["flag_id"] == flag_id and r["env_id"] == env_id)


def _contention_marks(client, headers, lock_key):
    items = client.get("/api/locks/contention", headers=headers).json()["items"]
    return [m for m in items if m["lock_key"] == lock_key]


def _duel_publish(flag_id, env_id, percent):
    """两个会话并发抢同一把发布锁，返回 [(user, status, body), ...]。

    测试侧会合点：把 releases_svc.acquire 包一层 barrier，强制两路在同一拍
    抢锁——判定结果完全由真实锁逻辑给出，杜绝调度巧合。
    """
    real_acquire = releases_svc.acquire
    rendezvous = threading.Barrier(2)

    def synced_acquire(conn, key, holder):
        rendezvous.wait(timeout=30)
        return real_acquire(conn, key, holder)

    results = []
    lock = threading.Lock()

    def player(username, password, tag):
        with TestClient(app) as client:
            headers = _login(client, username, password)
            r = client.post(
                "/api/releases/publish",
                headers=headers,
                json={
                    "flag_id": flag_id,
                    "env_id": env_id,
                    "kind": "percent",
                    "percent": percent,
                    "summary": f"{MUTEX_NAME}对打-{tag}",
                    "use_shadow": False,
                },
            )
            with lock:
                results.append((username, r.status_code, r.json()))

    releases_svc.acquire = synced_acquire
    try:
        threads = [
            threading.Thread(target=player, args=("admin", "admin123", "甲")),
            threading.Thread(target=player, args=("writer", "writer123", "乙")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        releases_svc.acquire = real_acquire
    return results


def test_prod_publish_mutex_no_double_win():
    """争用失败测核心：两路抢「生产发布互斥」，须一胜一败，败方只写争用痕。"""
    key = "feed.ranking_v3_race"
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, key, "信息流排序 v3 争用复现")
        lock_key = f"flag-release:{fid}:{PROD_ENV_ID}"
        before_rel = _official_release_count(client, admin, fid, PROD_ENV_ID)
        before_marks = len(_contention_marks(client, admin, lock_key))

        results = _duel_publish(fid, PROD_ENV_ID, percent=50)

        statuses = sorted(s for _, s, _ in results)
        assert statuses == [200, 409], (
            f"「{MUTEX_NAME}」须一胜一败，不得无锁双成，实际 {[(u, s) for u, s, _ in results]}"
        )
        loser = next((u, b) for u, s, b in results if s == 409)
        assert "争用" in str(loser[1].get("detail", "")), f"败方须收到锁争用说明，实际 {loser[1]}"

        after_rel = _official_release_count(client, admin, fid, PROD_ENV_ID)
        assert after_rel == before_rel + 1, (
            f"正式账只许胜方 +1（败方无正式成功），实际 {before_rel} → {after_rel}"
        )
        marks = _contention_marks(client, admin, lock_key)
        assert len(marks) >= before_marks + 1, f"败方须留下争用痕，实际 {marks}"
        latest = max(marks, key=lambda m: m["id"])
        assert latest["loser"] == loser[0], f"争用痕败方须为 {loser[0]}，实际 {latest}"
