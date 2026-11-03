"""Per-visitor alerts, push bookkeeping, and the API surface, on a temp database."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import alerts, db, push


@pytest.fixture()
def seeded(conn):
    conn.execute("INSERT OR REPLACE INTO stocks(symbol, name, in_portfolio) VALUES ('AAA','Alpha Ltd',1)")
    from backend import config
    today = config.now_ist().date()
    closes = [100] * 13 + [112]                                   # +12% on the last session
    vols = [1000] * 13 + [9000]                                   # 9x average (the rule needs >= 10 prior sessions)
    for i, (c, v) in enumerate(zip(closes, vols)):
        d = (today - __import__("datetime").timedelta(days=len(closes) - 1 - i)).isoformat()
        conn.execute("INSERT OR REPLACE INTO prices(symbol,date,open,high,low,close,volume) VALUES ('AAA',?,?,?,?,?,?)", (d, c, c, c, c, v))
    conn.execute("""INSERT OR REPLACE INTO announcements(id,symbol,ann_dt,nse_desc,text,category,priority,why,fetched_at)
                    VALUES ('1','AAA',?, 'Outcome','results','results',92,'Financial results filed',datetime('now'))""",
                 (config.now_ist().isoformat(timespec="seconds"),))
    conn.commit()
    return conn


def kinds(conn, **st):
    s = db.visitor_settings(conn, "v-test-1234")
    s.update(st)
    return sorted(a["kind"] for a in alerts.derive(conn, s))


def test_thresholds_decide_what_is_unusual(seeded):
    assert kinds(seeded) == ["announcement", "price_move", "volume_spike"]
    assert "price_move" not in kinds(seeded, price_move_pct=15)
    assert "volume_spike" not in kinds(seeded, volume_multiple=20)
    assert "announcement" not in kinds(seeded, alert_categories=["litigation"])


def test_visitor_settings_are_private(seeded):
    seeded.execute("INSERT INTO visitor_settings(visitor,key,value) VALUES ('v-aaaa-1111','price_move_pct','30')")
    assert db.visitor_settings(seeded, "v-aaaa-1111")["price_move_pct"] == 30
    assert db.visitor_settings(seeded, "v-bbbb-2222")["price_move_pct"] == 5.0


def test_push_only_new_alerts_and_keeps_pending_when_undelivered(seeded):
    sent = []
    push.subscribe(seeded, "v-test-1234", {"endpoint": "https://push.example/1", "keys": {"p256dh": "a", "auth": "b"}})
    assert push.notify_new(seeded, lambda s, p: sent.append(p) or True) == 0           # existing alerts are not re-announced
    seeded.execute("INSERT OR REPLACE INTO visitor_settings(visitor,key,value) VALUES ('v-test-1234','price_move_pct','1')")
    seeded.execute("INSERT INTO announcements(id,symbol,ann_dt,nse_desc,category,priority,why,fetched_at) "
                   "VALUES ('2','AAA',datetime('now'),'Change','management_change',86,'CEO change',datetime('now'))")
    assert push.notify_new(seeded, lambda s, p: False) == 0                            # dead endpoint: nothing lost
    assert push.notify_new(seeded, lambda s, p: sent.append(p) or True) >= 1           # delivered on the next run
    assert push.notify_new(seeded, lambda s, p: sent.append(p) or True) == 0           # and never twice


def test_push_rejects_malformed_subscription(conn):
    with pytest.raises(ValueError):
        push.subscribe(conn, "v-test-1234", {"endpoint": "http://insecure", "keys": {}})


def test_api_isolation_and_validation(seeded):
    from backend.main import app
    c = TestClient(app)
    a, b = {"x-visitor": "visitor-aaaa-1111"}, {"x-visitor": "visitor-bbbb-2222"}
    assert c.put("/api/settings", json={"price_move_pct": 15}, headers=a).status_code == 200
    assert c.get("/api/settings", headers=a).json()["price_move_pct"] == 15
    assert c.get("/api/settings", headers=b).json()["price_move_pct"] == 5.0
    key = c.get("/api/alerts", headers=b).json()["alerts"][0]["key"]
    c.post(f"/api/alerts/{key}/seen", headers=b)
    assert c.get("/api/alerts?unseen_only=true", headers=b).json()["count"] == c.get("/api/alerts", headers=b).json()["count"] - 1
    assert c.get("/api/alerts?unseen_only=true", headers=a).json()["count"] == c.get("/api/alerts", headers=a).json()["count"]
    assert c.put("/api/settings", json={"alert_categories": ["nonsense"]}, headers=a).status_code == 422
    assert c.put("/api/settings", json={"price_move_pct": -1}, headers=a).status_code == 422
    assert c.get("/api/research/bad$sym").status_code in (400, 404)


def test_llm_endpoints_say_so_without_a_key(seeded, monkeypatch):
    from backend import screener
    from backend.main import app
    monkeypatch.setattr(screener, "fetch", lambda s: (_ for _ in ()).throw(screener.ScreenerError(f"{s} not found on screener.in")))
    r = TestClient(app).post("/api/ask", json={"question": "anything at all", "symbol": "AAA"})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    assert TestClient(app).get("/api/status").json()["llm"]["provider"] is None
