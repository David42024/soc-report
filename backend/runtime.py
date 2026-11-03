"""Redis cache and routing queue; PostgreSQL remains the source of pending work."""
import json
import time

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from redis.exceptions import RedisError

from .db import REPORTS


class RuntimeServices:
    def __init__(self, db, security):
        self.db = db
        self.redis = security.redis
        self.last_scan = 0

    def metrics(self):
        if not self.redis:
            return self.db.metrics()
        try:
            cached = self.redis.get("soc:metrics")
            if cached:
                return json.loads(cached)
            result = self.db.metrics()
            self.redis.set("soc:metrics", json.dumps(jsonable_encoder(result)), ex=5)
            return result
        except RedisError:
            raise HTTPException(503, "Redis no está disponible.") from None

    def invalidate(self):
        if self.redis:
            try:
                self.redis.delete("soc:metrics")
            except RedisError:
                # A committed report must still be returned when cache eviction fails.
                pass

    def enqueue(self, report_id):
        if self.redis:
            try:
                self.redis.zadd("soc:routing", {report_id: time.time() + 30}, nx=True)
            except RedisError:
                # Startup and periodic scans restore queued work from PostgreSQL.
                pass

    def tick(self, dispatch):
        if not self.redis:
            return
        now = time.time()
        if now - self.last_scan > 60:
            with self.db.session() as execute:
                rows = execute(REPORTS + " WHERE n.ocurrido_at IS NULL ORDER BY r.recibido_at LIMIT 1000").fetchall()
            for row in rows:
                self.enqueue(row["id"])
            self.last_scan = now
        for report_id in self.redis.zrangebyscore("soc:routing", 0, now, start=0, num=10):
            lock = self.redis.lock(f"soc:routing-lock:{report_id}", timeout=90, blocking=False)
            if not lock.acquire():
                continue
            try:
                report = self.db.report(report_id)
                if report is None or dispatch(report)["notificado_at"]:
                    self.redis.zrem("soc:routing", report_id)
                else:
                    self.redis.zadd("soc:routing", {report_id: now + 60})
            finally:
                lock.release()
