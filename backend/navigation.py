"""Track browser visits and distinguish observed exits from expired leases."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

LEASE_SECONDS = 180


def observe(db, visit, sequence, module, actor):
    now = datetime.now(timezone.utc).isoformat()
    owner = actor["id"] + ":" + actor.get("jti", actor["role"])
    with db.session(write=True) as execute:
        execute("""INSERT INTO audit_visits (id,owner,user_id,role,ip,sequence,last_seen)
            VALUES (%s,%s,%s,%s,%s,0,%s) ON CONFLICT (id) DO NOTHING""",
            (visit, owner, actor["id"], actor["role"], actor["ip"], now))
        lock = " FOR UPDATE" if db.url else ""
        saved = execute("SELECT owner,module,sequence FROM audit_visits WHERE id=%s" + lock, (visit,)).fetchone()
        if saved["owner"] != owner:
            raise HTTPException(403, "Visita de navegación no autorizada.")
        if sequence <= saved["sequence"]:
            return
        previous = saved["module"]
        if previous != module:
            if previous:
                db.access_event(execute, actor, "module_exit", previous, "navigation", entity=visit)
            if module:
                db.access_event(execute, actor, "module_enter", module, "navigation", entity=visit)
        execute("UPDATE audit_visits SET module=%s,sequence=%s,last_seen=%s WHERE id=%s", (module, sequence, now, visit))


def expire_visits(db, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=LEASE_SECONDS)).isoformat()
    lock = " FOR UPDATE SKIP LOCKED" if db.url else ""
    with db.session(write=True) as execute:
        stale = list(execute("""SELECT id,user_id,role,ip,module FROM audit_visits
            WHERE module IS NOT NULL AND last_seen <= %s ORDER BY last_seen LIMIT 500""" + lock, (cutoff,)))
        for row in stale:
            actor = {"id": row["user_id"], "role": row["role"], "ip": row["ip"]}
            db.access_event(execute, actor, "module_exit", row["module"], "navigation", entity=row["id"], outcome="expirado")
            execute("UPDATE audit_visits SET module=NULL,last_seen=%s WHERE id=%s", (now.isoformat(), row["id"]))
        execute("DELETE FROM audit_visits WHERE module IS NULL AND last_seen < %s", ((now - timedelta(days=1)).isoformat(),))
