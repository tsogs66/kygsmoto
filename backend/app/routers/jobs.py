"""Job queue: work tickets for bikes in the shop.

A job ticket collects the parts and labour for one motorcycle while the work is
under way, then converts into a sale at checkout. Stock moves at checkout, not
when the line is added, so a job sitting in the queue never quietly holds stock
that the counter could still sell.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..security import audit, current_user, has_permission, require
from . import pos

router = APIRouter(prefix="/api/pos/jobs", tags=["jobs"])

# queued -> in_progress -> ready -> completed, with cancel available until done.
OPEN_STATUSES = ("queued", "in_progress", "ready")
ALL_STATUSES = OPEN_STATUSES + ("completed", "cancelled")
ALLOWED_TRANSITIONS = {
    "queued": {"in_progress", "ready", "cancelled"},
    "in_progress": {"ready", "queued", "cancelled"},
    "ready": {"in_progress", "cancelled"},   # completed happens via checkout
    "completed": set(),
    "cancelled": set(),
}
STATUS_STAMP = {"in_progress": "started_at", "ready": "ready_at"}


class JobLineIn(BaseModel):
    line_type: str = "item"
    item_id: int | None = None
    service_id: int | None = None
    qty: float = Field(gt=0)
    unit_price: float | None = None
    discount: float = 0
    description: str | None = None


class JobIn(BaseModel):
    customer_name: str = ""
    contact: str = ""
    plate_no: str = ""
    motorcycle: str = ""
    complaint: str = ""
    notes: str = ""
    priority: str = "normal"
    assigned_to: int | None = None
    lines: list[JobLineIn] = []


class JobPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    customer_name: str | None = None
    contact: str | None = None
    plate_no: str | None = None
    motorcycle: str | None = None
    complaint: str | None = None
    notes: str | None = None
    assigned_to: int | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


class CheckoutIn(BaseModel):
    payments: list[pos.PaymentIn] = []
    order_discount: float = 0
    amount_tendered: float = 0
    allow_negative_stock: bool = False


def _next_job_no() -> str:
    stamp = date.today().strftime("%Y%m%d")
    row = db.query_one(
        "SELECT job_no FROM jobs WHERE job_no LIKE ? ORDER BY job_no DESC LIMIT 1",
        (f"JOB{stamp}-%",),
    )
    nxt = int(row["job_no"].split("-")[1]) + 1 if row else 1
    return f"JOB{stamp}-{nxt:03d}"


def _resolve_line(line: JobLineIn):
    """Turn a request line into stored columns, pricing from the catalogue."""
    if line.line_type == "item":
        if not line.item_id:
            raise HTTPException(status_code=400, detail="Item line is missing item_id")
        item = db.query_one("SELECT * FROM items WHERE id = ?", (line.item_id,))
        if item is None:
            raise HTTPException(status_code=404, detail=f"Item {line.item_id} not found")
        return {
            "line_type": "item", "item_id": item["id"], "service_id": None,
            "sku": item["sku"], "description": item["description"],
            "unit_price": (line.unit_price if line.unit_price is not None
                           else float(item["retail_price"] or 0)),
        }

    if line.line_type == "service":
        if line.service_id:
            svc = db.query_one("SELECT * FROM services WHERE id = ?", (line.service_id,))
            if svc is None:
                raise HTTPException(status_code=404,
                                    detail=f"Service {line.service_id} not found")
            return {
                "line_type": "service", "item_id": None, "service_id": svc["id"],
                "sku": svc["code"], "description": svc["name"],
                "unit_price": (line.unit_price if line.unit_price is not None
                               else float(svc["fee"] or 0)),
            }
        if not line.description:
            raise HTTPException(status_code=400,
                                detail="A custom labour line needs a description")
        return {
            "line_type": "service", "item_id": None, "service_id": None, "sku": "",
            "description": line.description,
            "unit_price": line.unit_price or 0.0,
        }

    raise HTTPException(status_code=400, detail=f"Unknown line type '{line.line_type}'")


def _payload(job_id: int):
    job = db.query_one(
        """SELECT j.*, u.username AS created_by_name, a.username AS assigned_to_name,
                  s.receipt_no
             FROM jobs j
             JOIN users u ON u.id = j.created_by
             LEFT JOIN users a ON a.id = j.assigned_to
             LEFT JOIN sales s ON s.id = j.sale_id
            WHERE j.id = ?""",
        (job_id,),
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    lines = db.query(
        """SELECT l.*, i.stock_qty AS on_hand
             FROM job_lines l
             LEFT JOIN items i ON i.id = l.item_id
            WHERE l.job_id = ? ORDER BY l.id""",
        (job_id,),
    )

    out, parts, labour = [], 0.0, 0.0
    for line in lines:
        total = round(float(line["qty"]) * float(line["unit_price"]) - float(line["discount"]), 2)
        entry = dict(line)
        entry["total"] = total
        # Flag shortages now so the counter is not surprised at checkout.
        entry["short"] = (line["line_type"] == "item"
                          and line["on_hand"] is not None
                          and float(line["on_hand"]) < float(line["qty"]))
        out.append(entry)
        if line["line_type"] == "item":
            parts += total
        else:
            labour += total

    return {
        "job": dict(job),
        "lines": out,
        "totals": {
            "parts": round(parts, 2),
            "labour": round(labour, 2),
            "total": round(parts + labour, 2),
            "lines": len(out),
            "short_lines": sum(1 for line in out if line["short"]),
        },
    }


@router.get("/board")
def board(user=Depends(require("pos.sell"))):
    """Counts and the open queue — what the shop is working on right now."""
    counts = {status: 0 for status in ALL_STATUSES}
    for row in db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
        counts[row["status"]] = row["n"]

    rows = db.query(
        f"""SELECT j.*, a.username AS assigned_to_name,
                   (SELECT COUNT(*) FROM job_lines WHERE job_id = j.id) AS line_count,
                   (SELECT COALESCE(SUM(qty * unit_price - discount), 0)
                      FROM job_lines WHERE job_id = j.id) AS total,
                   CAST((julianday('now') - julianday(j.created_at)) * 24 AS INT) AS hours_open
              FROM jobs j
              LEFT JOIN users a ON a.id = j.assigned_to
             WHERE j.status IN ({','.join('?' * len(OPEN_STATUSES))})
          ORDER BY CASE j.priority WHEN 'urgent' THEN 0 ELSE 1 END,
                   CASE j.status WHEN 'ready' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                   j.created_at""",
        OPEN_STATUSES,
    )
    jobs = [{**dict(r), "total": round(float(r["total"] or 0), 2)} for r in rows]

    return {
        "counts": counts,
        "open_total": sum(counts[s] for s in OPEN_STATUSES),
        "open_value": round(sum(j["total"] for j in jobs), 2),
        "jobs": jobs,
    }


@router.get("")
def list_jobs(
    status: str | None = None,
    q: str = "",
    limit: int = Query(default=100, le=500),
    user=Depends(require("pos.sell")),
):
    where, params = ["1=1"], []
    if status == "open":
        where.append(f"j.status IN ({','.join('?' * len(OPEN_STATUSES))})")
        params += list(OPEN_STATUSES)
    elif status:
        where.append("j.status = ?")
        params.append(status)
    if q:
        where.append("(j.job_no LIKE ? OR j.customer_name LIKE ? OR j.plate_no LIKE ? "
                     "OR j.motorcycle LIKE ?)")
        params += [f"%{q}%"] * 4

    rows = db.query(
        f"""SELECT j.*, a.username AS assigned_to_name,
                   (SELECT COUNT(*) FROM job_lines WHERE job_id = j.id) AS line_count,
                   (SELECT COALESCE(SUM(qty * unit_price - discount), 0)
                      FROM job_lines WHERE job_id = j.id) AS total
              FROM jobs j
              LEFT JOIN users a ON a.id = j.assigned_to
             WHERE {' AND '.join(where)}
          ORDER BY j.id DESC LIMIT ?""",
        (*params, limit),
    )
    return {"jobs": [{**dict(r), "total": round(float(r["total"] or 0), 2)} for r in rows]}


@router.get("/{job_id}")
def get_job(job_id: int, user=Depends(require("pos.sell"))):
    return _payload(job_id)


@router.post("")
def create_job(body: JobIn, user=Depends(require("pos.sell"))):
    if body.priority not in ("normal", "urgent"):
        raise HTTPException(status_code=400, detail="Priority must be normal or urgent")

    with db.transaction():
        job_no = _next_job_no()
        cur = db.execute(
            """INSERT INTO jobs(job_no, customer_name, contact, plate_no, motorcycle,
                                complaint, notes, priority, assigned_to, created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (job_no, body.customer_name.strip(), body.contact.strip(),
             body.plate_no.strip().upper(), body.motorcycle.strip(), body.complaint.strip(),
             body.notes.strip(), body.priority, body.assigned_to, user["id"]),
        )
        job_id = cur.lastrowid
        for line in body.lines:
            resolved = _resolve_line(line)
            db.execute(
                """INSERT INTO job_lines(job_id, line_type, item_id, service_id, sku,
                                         description, qty, unit_price, discount)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (job_id, resolved["line_type"], resolved["item_id"], resolved["service_id"],
                 resolved["sku"], resolved["description"], line.qty, resolved["unit_price"],
                 line.discount),
            )

    audit(user, "job.created", "job", job_id, {"job_no": job_no, "plate": body.plate_no})
    return _payload(job_id)


@router.patch("/{job_id}")
def update_job(job_id: int, body: JobPatch, user=Depends(require("pos.sell"))):
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    data = body.model_dump(exclude_none=True)
    if "status" in data:
        new = data["status"]
        if new not in ALL_STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"Status must be one of {list(ALL_STATUSES)}")
        if new == "completed":
            raise HTTPException(
                status_code=400,
                detail="Finish a job by taking payment, not by setting its status.",
            )
        if new != job["status"] and new not in ALLOWED_TRANSITIONS[job["status"]]:
            raise HTTPException(
                status_code=409,
                detail=f"A {job['status']} job cannot move to {new}.",
            )
    if "priority" in data and data["priority"] not in ("normal", "urgent"):
        raise HTTPException(status_code=400, detail="Priority must be normal or urgent")

    if not data:
        return _payload(job_id)

    sets = ", ".join(f"{key} = ?" for key in data)
    values = list(data.values())
    # Stamp the first time a job reaches each stage.
    stamp = STATUS_STAMP.get(data.get("status", ""))
    if stamp and not job[stamp]:
        sets += f", {stamp} = datetime('now')"

    db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*values, job_id))
    audit(user, "job.updated", "job", job_id, data)
    return _payload(job_id)


@router.post("/{job_id}/lines")
def add_line(job_id: int, body: JobLineIn, user=Depends(require("pos.sell"))):
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in OPEN_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Cannot add work to a {job['status']} job")
    if body.discount > 0 and not has_permission(user, "pos.discount"):
        raise HTTPException(status_code=403,
                            detail="Your role cannot apply discounts")

    resolved = _resolve_line(body)
    db.execute(
        """INSERT INTO job_lines(job_id, line_type, item_id, service_id, sku, description,
                                 qty, unit_price, discount)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (job_id, resolved["line_type"], resolved["item_id"], resolved["service_id"],
         resolved["sku"], resolved["description"], body.qty, resolved["unit_price"],
         body.discount),
    )
    return _payload(job_id)


@router.delete("/{job_id}/lines/{line_id}")
def remove_line(job_id: int, line_id: int, user=Depends(require("pos.sell"))):
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in OPEN_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Cannot change a {job['status']} job")
    db.execute("DELETE FROM job_lines WHERE id = ? AND job_id = ?", (line_id, job_id))
    return _payload(job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, body: CancelIn, user=Depends(require("pos.sell"))):
    job = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in OPEN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Job is already {job['status']}")

    db.execute(
        "UPDATE jobs SET status = 'cancelled', cancelled_at = datetime('now'), "
        "cancel_reason = ? WHERE id = ?",
        (body.reason, job_id),
    )
    audit(user, "job.cancelled", "job", job_id,
          {"job_no": job["job_no"], "reason": body.reason})
    return _payload(job_id)


@router.post("/{job_id}/checkout")
def checkout_job(job_id: int, body: CheckoutIn, user=Depends(require("pos.sell"))):
    """Turn a finished job into a sale. Stock moves here, and only here."""
    payload = _payload(job_id)
    job = payload["job"]

    if job["status"] not in OPEN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Job is already {job['status']}")
    if not payload["lines"]:
        raise HTTPException(status_code=400,
                            detail="Add parts or labour before taking payment")

    sale_lines = [
        pos.CartLine(
            line_type=line["line_type"],
            item_id=line["item_id"],
            service_id=line["service_id"],
            qty=line["qty"],
            unit_price=line["unit_price"],
            discount=line["discount"],
            description=line["description"] if line["service_id"] is None else None,
        )
        for line in payload["lines"]
    ]

    sale = pos.create_sale(
        pos.SaleIn(
            lines=sale_lines,
            payments=body.payments,
            customer_name=job["customer_name"],
            plate_no=job["plate_no"],
            order_discount=body.order_discount,
            amount_tendered=body.amount_tendered,
            note=f"{job['job_no']} {job['motorcycle']}".strip(),
            allow_negative_stock=body.allow_negative_stock,
        ),
        user,
    )

    db.execute(
        "UPDATE jobs SET status = 'completed', completed_at = datetime('now'), sale_id = ? "
        "WHERE id = ?",
        (sale["sale"]["id"], job_id),
    )
    audit(user, "job.completed", "job", job_id,
          {"job_no": job["job_no"], "receipt": sale["sale"]["receipt_no"],
           "total": sale["sale"]["total"]})

    sale["job"] = _payload(job_id)["job"]
    return sale
