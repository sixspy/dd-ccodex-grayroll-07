"""并发双请求对打脚本：duel_prod_forbid_hundred。

对打一（禁一键全量）：两个会话同时向 prod 一键直写 100% 正式发布，
  期望双双被生产闸 409 拒写，正式账零增。
对打二（生产发布互斥）：两个会话同时向 prod 发布 50%，
  期望一胜一败——胜方唯一正式成功，败方只写争用痕（409 + contention_marks）。

自包含（TestClient 起应用），退出码 0=全部符合预期，1=有违例。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import releases_svc  # noqa: E402
from app import app  # noqa: E402

PROD_ENV_ID = 3
MUTEX_NAME = "生产发布互斥"


def _login(client, user, password):
    r = client.post("/api/login", json={"username": user, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _ensure_flag(client, headers, key, title):
    for it in client.get("/api/flags", headers=headers).json()["items"]:
        if it["key"] == key:
            return it["id"]
    r = client.post("/api/flags", headers=headers, json={"key": key, "title": title})
    r.raise_for_status()
    return r.json()["id"]


def _ledger(client, headers, flag_id):
    rels = client.get("/api/releases", headers=headers).json()["official"]
    rules = client.get("/api/rules", headers=headers).json()["official"]
    marks = client.get("/api/locks/contention", headers=headers).json()["items"]
    return {
        "official_releases": sum(1 for r in rels if r["flag_id"] == flag_id and r["env_id"] == PROD_ENV_ID),
        "official_rules": sum(1 for r in rules if r["flag_id"] == flag_id and r["env_id"] == PROD_ENV_ID),
        "contention_marks": [m for m in marks if m["lock_key"] == f"flag-release:{flag_id}:{PROD_ENV_ID}"],
    }


def _duel(flag_id, percent, tag, rendezvous=False):
    """两路会话并发同键发布；rendezvous=True 时强制同一拍抢锁。"""
    restore_acquire = None
    barrier = threading.Barrier(2)
    if rendezvous:
        real_acquire = releases_svc.acquire

        def synced(conn, key, holder):
            barrier.wait(timeout=30)
            return real_acquire(conn, key, holder)

        releases_svc.acquire = synced
        restore_acquire = real_acquire
    results = []

    def player(username, password):
        with TestClient(app) as client:
            headers = _login(client, username, password)
            r = client.post(
                "/api/releases/publish",
                headers=headers,
                json={
                    "flag_id": flag_id,
                    "env_id": PROD_ENV_ID,
                    "kind": "percent",
                    "percent": percent,
                    "summary": f"{tag}-{username}",
                    "use_shadow": False,
                },
            )
            results.append((username, r.status_code, r.json()))

    try:
        threads = [
            threading.Thread(target=player, args=("admin", "admin123")),
            threading.Thread(target=player, args=("writer", "writer123")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        if restore_acquire is not None:
            releases_svc.acquire = restore_acquire
    return sorted(results, key=lambda x: x[0])


def main() -> int:
    ok = True
    with TestClient(app) as client:
        admin = _login(client, "admin", "admin123")
        fid = _ensure_flag(client, admin, "feed.ranking_v3_duel", "信息流排序 v3 对打")

        print(f"== 对打一：prod 一键百分百（禁一键全量） flag={fid} ==")
        before = _ledger(client, admin, fid)
        results = _duel(fid, 100, "一键百分百")
        for user, status, body in results:
            print(f"  {user}: {status} {body.get('detail', body)}")
        after = _ledger(client, admin, fid)
        print(f"  正式账: releases {before['official_releases']}→{after['official_releases']} "
              f"rules {before['official_rules']}→{after['official_rules']}")
        if [s for _, s, _ in results] != [409, 409]:
            print("  违例：一键全量未被生产闸双双拒写")
            ok = False
        if (after["official_releases"], after["official_rules"]) != (
            before["official_releases"], before["official_rules"]
        ):
            print("  违例：被拒方出现正式增量（违者须正式零增）")
            ok = False

        print(f"== 对打二：prod 五成灰度（{MUTEX_NAME}） ==")
        before = _ledger(client, admin, fid)
        results = _duel(fid, 50, "互斥对打", rendezvous=True)
        for user, status, body in results:
            print(f"  {user}: {status} {body.get('detail', body)}")
        after = _ledger(client, admin, fid)
        marks_delta = len(after["contention_marks"]) - len(before["contention_marks"])
        print(f"  正式账: releases {before['official_releases']}→{after['official_releases']} "
              f"rules {before['official_rules']}→{after['official_rules']} 争用痕 +{marks_delta}")
        statuses = sorted(s for _, s, _ in results)
        if statuses != [200, 409]:
            print(f"  违例：须一胜一败，不得无锁双成，实际 {statuses}")
            ok = False
        if after["official_releases"] != before["official_releases"] + 1:
            print("  违例：正式账不只胜方 +1（败方有正式成功）")
            ok = False
        if marks_delta < 1:
            print("  违例：败方未留争用痕")
            ok = False

    print("结果:", "全部符合预期" if ok else "存在违例")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
