from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Dict, Any, Iterator
import requests

app = FastAPI()

# Allow local testing and cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    token: str


WORKABLE_BASE = "https://api.workable.com/v3/employees"


def _extract_name(emp: Dict[str, Any]) -> str:
    # Workable may return different name fields; try common ones.
    if not isinstance(emp, dict):
        return ""
    if emp.get("full_name"):
        return emp.get("full_name")
    if emp.get("name"):
        return emp.get("name")
    # Combine first/last if available
    if emp.get("first_name"):
        return (emp.get("first_name") + " " + emp.get("last_name", "")).strip()
    # Fallback: try common nested structures or id
    return emp.get("id", "")


def fetch_all_employees(token: str) -> List[Dict[str, str]]:
    headers = {"Authorization": f"Bearer {token}"}
    url = WORKABLE_BASE
    employees: List[Dict[str, str]] = []
    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Network error: {e}")
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: invalid token")
        if not resp.ok:
            raise HTTPException(
                status_code=502, detail=f"Upstream error: {resp.status_code}"
            )
        data = resp.json()
        # Workable returns a dict with 'employees' and 'paging'
        page_items = None
        if isinstance(data, dict):
            page_items = data.get("employees")
        if page_items is None and isinstance(data, list):
            page_items = data
        if not page_items:
            page_items = []
        for e in page_items:
            employees.append(
                {
                    "id": e.get("id"),
                    "name": _extract_name(e),
                }
            )
        paging = data.get("paging") if isinstance(data, dict) else None
        url = paging.get("next") if paging and isinstance(paging, dict) else None
    return employees


@app.post("/api/employees")
async def api_employees(req: TokenRequest):
    """Return JSON list of employees (id and name)."""
    employees = fetch_all_employees(req.token)
    return JSONResponse(content={"employees": employees})


@app.post("/api/employees/csv")
async def api_employees_csv(req: TokenRequest):
    """Return employees as a streamed CSV download."""
    employees = fetch_all_employees(req.token)

    def iter_csv() -> Iterator[bytes]:
        import io, csv

        buf = io.StringIO()
        writer = csv.writer(buf)
        # header
        writer.writerow(["id", "name"])
        yield buf.getvalue().encode("utf-8")
        buf.truncate(0)
        buf.seek(0)
        for e in employees:
            writer.writerow([e.get("id", ""), e.get("name", "")])
            yield buf.getvalue().encode("utf-8")
            buf.truncate(0)
            buf.seek(0)

    headers = {"Content-Disposition": "attachment; filename=employees.csv"}
    return StreamingResponse(iter_csv(), media_type="text/csv", headers=headers)


# Expose ASGI app as `handler` for Vercel's Python builder
handler = app
