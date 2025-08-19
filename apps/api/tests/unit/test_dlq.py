from __future__ import annotations

from app.services import dlq


def test_push_list_requeue_smoke(monkeypatch):
    # DB çağrılarını no-op mockla; yalnızca fonksiyonlar çağrılabilsin
    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, *a, **kw):
            return None

        def commit(self):
            return None

        def query(self, *a, **kw):
            class Q:
                def order_by(self, *a, **kw):
                    return self

                def offset(self, *a, **kw):
                    return self

                def limit(self, *a, **kw):
                    return self

                def all(self):
                    return []

            return Q()

        def get(self, *a, **kw):
            class Obj:
                type = "cam"

            return Obj()

    monkeypatch.setattr("app.services.dlq.db_session", lambda: DummySession())
    monkeypatch.setattr(
        "app.services.dlq.celery_app",
        type("C", (), {"send_task": staticmethod(lambda *a, **k: None)}),
    )
    dlq.push_dead(1, "t", "r")
    assert isinstance(dlq.list_dead(), list)
    assert dlq.requeue(1) is True
