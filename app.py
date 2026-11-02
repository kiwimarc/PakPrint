"""
PakPrint - udskriv følgesedler fra Dinero på mobilen.

Kør:   python app.py           (starter web-appen)
Test:  python app.py check     (tjekker Dinero-forbindelsen fra terminalen)
Demo:  python app.py demo      (laver demo_foelgeseddel.pdf uden at kalde Dinero)
"""
import base64
import hmac
import io
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import (Flask, redirect, render_template_string, request,
                   send_file, session, url_for)
from fpdf import FPDF
from fpdf.fonts import FontFace

load_dotenv()

# --- KONFIGURATION (fra .env) ---
CLIENT_ID = os.getenv("DINERO_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DINERO_CLIENT_SECRET", "").strip()
API_KEY = os.getenv("DINERO_API_KEY", "").strip()
ORG_ID = os.getenv("DINERO_ORG_ID", "").strip()

SENDER_NAME = os.getenv("SENDER_NAME", "Mit Firma ApS")
SENDER_ADDRESS = os.getenv("SENDER_ADDRESS", "")
SENDER_CVR = os.getenv("SENDER_CVR", "")

APP_PASSWORD = os.getenv("APP_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")
DAYS_BACK = int(os.getenv("DAYS_BACK", "60"))

TOKEN_URL = "https://authz.dinero.dk/dineroapi/oauth/token"
API_BASE = "https://api.dinero.dk/v1"

app = Flask(__name__)
app.secret_key = SECRET_KEY or os.urandom(32)
app.permanent_session_lifetime = timedelta(days=180)  # forbliv logget ind på telefonen

# Dineros enhedskoder -> dansk tekst på følgesedlen
UNITS_DA = {
    "parts": "stk.", "hours": "timer", "km": "km", "day": "dage", "week": "uger",
    "month": "mdr.", "kilogram": "kg", "cubicMetre": "m³", "set": "sæt",
    "litre": "liter", "box": "æsker", "case": "kolli", "carton": "kartoner",
    "metre": "m", "package": "pakker", "shipment": "forsendelser",
    "squareMetre": "m²", "session": "sessioner", "tonne": "tons",
}

STATUS_DA = {
    "Draft": "Kladde", "Booked": "Bogført", "Paid": "Betalt",
    "OverPaid": "Overbetalt", "Overdue": "Forfalden",
}


class DineroError(Exception):
    pass


# ---------------------------------------------------------------------------
# Hjælpere
# ---------------------------------------------------------------------------
def g(d, key, default=None):
    """Case-insensitiv dict-opslag (Dinero svarer i PascalCase, men vi tager ingen chancer)."""
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    lower = key.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    return default


def fmt_date(value):
    """'2026-11-02' / '2026-11-02T10:00:00' -> '02-11-2026'."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%d-%m-%Y")
    except ValueError:
        return str(value)


def fmt_qty(q):
    try:
        q = float(q)
    except (TypeError, ValueError):
        return ""
    return str(int(q)) if q.is_integer() else f"{q:g}".replace(".", ",")


_REPLACEMENTS = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
                 "…": "...", "•": "-", "€": "EUR", "\u00a0": " ", "\t": " "}


def pdf_text(s):
    """PDF'ens indbyggede Helvetica kan kun latin-1 (æøå er fine).
    Øvrige tegn (fx emojis i et kundenavn) erstattes, så PDF'en aldrig crasher."""
    s = str(s or "")
    for a, b in _REPLACEMENTS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Dinero API
# ---------------------------------------------------------------------------
_token = {"value": None, "expires": 0.0}


def get_dinero_token():
    """OAuth2 password grant for personlig integration. Tokenet caches,
    så vi ikke beder om et nyt ved hvert klik (det kan Dinero ikke lide)."""
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]

    b64_auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {b64_auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "password", "scope": "read write",
              "username": API_KEY, "password": API_KEY},
        timeout=15,
    )
    if resp.status_code != 200:
        raise DineroError(
            f"Login hos Dinero fejlede (HTTP {resp.status_code}). "
            "Tjek DINERO_CLIENT_ID, DINERO_CLIENT_SECRET og DINERO_API_KEY i .env. "
            f"Svar: {resp.text[:200]}"
        )
    data = resp.json()
    _token["value"] = data["access_token"]
    # Tokenet holder typisk 3600 sek. Forny 5 min før.
    _token["expires"] = time.time() + int(data.get("expires_in", 3600)) - 300
    return _token["value"]


def dinero_get(path, params=None):
    token = get_dinero_token()
    resp = requests.get(
        f"{API_BASE}/{ORG_ID}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params, timeout=15,
    )
    if resp.status_code == 401:
        _token["value"] = None  # tvinger nyt token næste gang
        raise DineroError("Dinero afviste adgangen (401). Er DINERO_ORG_ID korrekt, "
                          "og er API-nøglen oprettet i netop den virksomhed?")
    if resp.status_code == 429:
        raise DineroError("For mange kald til Dinero lige nu. Vent et minut og prøv igen.")
    if resp.status_code != 200:
        raise DineroError(f"Dinero svarede HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def get_latest_invoices(limit=25):
    """Seneste fakturaer + kladder. Dinero kan kun sortere på VoucherNumber/VoucherDate,
    så vi henter en periode og sorterer selv på oprettelsestidspunkt."""
    params = {
        "startDate": (date.today() - timedelta(days=DAYS_BACK)).isoformat(),
        "endDate": (date.today() + timedelta(days=60)).isoformat(),
        "fields": "Guid,Number,ContactName,Date,Status,CreatedAt,UpdatedAt",
        "page": 0,
        "pageSize": 200,
    }
    items = g(dinero_get("/invoices", params), "Collection", []) or []
    items.sort(key=lambda i: str(g(i, "CreatedAt") or g(i, "Date") or ""), reverse=True)
    return items[:limit]


def get_invoice_details(guid):
    return dinero_get(f"/invoices/{guid}")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def split_address(invoice):
    """Dinero gemmer modtageradressen som ét felt med linjeskift."""
    name = g(invoice, "ContactName") or "Ukendt kunde"
    lines = [l.strip() for l in str(g(invoice, "Address") or "").splitlines() if l.strip()]
    if lines and lines[0].lower() == name.lower():
        lines = lines[1:]  # undgå at navnet står to gange
    return name, lines


def build_delivery_note_pdf(invoice):
    """Printklar følgeseddel uden priser."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # Afsender (højre) og titel (venstre)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(120, 15)
    pdf.multi_cell(75, 4.5, pdf_text(SENDER_NAME), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    for line in [l.strip() for l in SENDER_ADDRESS.split(",") if l.strip()]:
        pdf.multi_cell(75, 4.5, pdf_text(line), align="R", new_x="LEFT", new_y="NEXT")
    if SENDER_CVR:
        pdf.multi_cell(75, 4.5, pdf_text(f"CVR: {SENDER_CVR}"), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    pdf.set_xy(15, 15)
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(100, 12, pdf_text("FØLGESEDDEL"))
    pdf.set_y(45)

    # Modtager + ordredata
    name, addr_lines = split_address(invoice)
    number = g(invoice, "Number")
    status = g(invoice, "Status")
    ref = g(invoice, "ExternalReference")

    top = pdf.get_y()
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(110, 6, "Leveres til:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for line in [name] + addr_lines:
        pdf.cell(110, 5.5, pdf_text(line), new_x="LMARGIN", new_y="NEXT")
    bottom_left = pdf.get_y()

    pdf.set_xy(125, top)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(70, 6, "Ordredetaljer:", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    details = [
        f"Fakturanr.: {number}" if number else "Fakturanr.: (kladde)",
        f"Dato: {fmt_date(g(invoice, 'Date'))}",
        f"Leveringsdato: {date.today().strftime('%d-%m-%Y')}",
    ]
    if ref:
        details.append(f"Reference: {ref}")
    for line in details:
        pdf.cell(70, 5.5, pdf_text(line), new_x="LEFT", new_y="NEXT")
    pdf.set_xy(15, max(bottom_left, pdf.get_y()) + 10)

    # Varelinjer (ingen priser). fpdf2's table ombryder lange tekster automatisk.
    pdf.set_font("Helvetica", "", 10)
    with pdf.table(
        col_widths=(120, 30, 30),
        text_align=("LEFT", "RIGHT", "LEFT"),
        borders_layout="HORIZONTAL_LINES",
        headings_style=FontFace(emphasis="BOLD", fill_color=(235, 235, 235)),
        line_height=6,
        padding=2,
    ) as table:
        head = table.row()
        for h in ("Varebeskrivelse", "Antal", "Enhed"):
            head.cell(h)

        for line in g(invoice, "ProductLines", []) or []:
            desc = pdf_text(g(line, "Description") or "")
            extra = g(line, "Comments")
            if extra:
                desc += "\n" + pdf_text(extra)
            line_type = str(g(line, "LineType") or "Product")
            qty = g(line, "Quantity")

            row = table.row()
            if line_type.lower() == "text" or not qty:
                # Tekstlinje: hele bredden, kursiv
                row.cell(desc, colspan=3, style=FontFace(emphasis="ITALICS"))
            else:
                unit_code = g(line, "Unit") or "parts"
                row.cell(desc)
                row.cell(fmt_qty(qty))
                row.cell(pdf_text(UNITS_DA.get(unit_code, unit_code)))

    # Bemærkning fra fakturaen
    comment = g(invoice, "Comment")
    if comment:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, pdf_text("Bemærkning:"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, pdf_text(comment))

    # Kvitteringsfelt
    if pdf.get_y() > 250:
        pdf.add_page()
    pdf.set_y(max(pdf.get_y() + 20, 255))
    pdf.set_font("Helvetica", "", 9)
    pdf.line(15, pdf.get_y(), 90, pdf.get_y())
    pdf.line(115, pdf.get_y(), 195, pdf.get_y())
    pdf.cell(100, 5, "Dato")
    pdf.cell(80, 5, "Modtaget af (underskrift)")

    return io.BytesIO(pdf.output())


# ---------------------------------------------------------------------------
# Web (mobilvenlig)
# ---------------------------------------------------------------------------
BASE_HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="PakPrint">
<meta name="theme-color" content="#0066ff">
<title>PakPrint</title>
<style>
  :root { color-scheme: light dark; --bg:#f4f6f8; --card:#fff; --text:#1a1a1a; --muted:#666; --accent:#0066ff; }
  @media (prefers-color-scheme: dark) { :root { --bg:#111; --card:#1d1f23; --text:#eee; --muted:#9aa; } }
  body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text);
         margin: 0; padding: 16px; padding-top: calc(16px + env(safe-area-inset-top)); }
  h2 { margin: 0 0 12px; display:flex; justify-content:space-between; align-items:center; }
  a.refresh { font-size: .9rem; color: var(--accent); text-decoration: none; font-weight: 600; }
  .card { display:flex; justify-content:space-between; align-items:center; gap:12px;
          background: var(--card); padding: 16px; margin-bottom: 12px; border-radius: 12px;
          box-shadow: 0 2px 5px rgba(0,0,0,.06); text-decoration:none; color: inherit; }
  .info strong { font-size: 1.05rem; display:block; margin-bottom: 4px; }
  .info span { color: var(--muted); font-size: .9rem; }
  .badge { font-size:.75rem; padding:2px 7px; border-radius:6px; background:#ffe9b3; color:#6b4b00; margin-left:6px; }
  .btn { background: var(--accent); color:#fff; padding: 10px 14px; border-radius: 8px;
         font-weight:600; font-size:.9rem; white-space:nowrap; border:0; }
  .error { background:#ffe5e5; color:#7a0000; padding:14px; border-radius:10px; }
  input { font-size: 1.1rem; padding: 12px; width: 100%; box-sizing: border-box; border-radius: 8px;
          border: 1px solid #ccc; margin: 8px 0 12px; }
</style>
"""

LIST_HTML = """<!doctype html><html lang="da"><head>""" + BASE_HEAD + """</head><body>
  <h2>Seneste ordrer <a class="refresh" href="/">↻ Opdatér</a></h2>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% for inv in invoices %}
    <a class="card" href="/pdf/{{ inv.guid }}" target="_blank">
      <div class="info">
        <strong>{{ inv.name }}</strong>
        <span>{{ ('Nr. ' ~ inv.number) if inv.number else 'Kladde' }} • {{ inv.date }}</span>
        {% if inv.draft %}<span class="badge">Kladde</span>{% endif %}
      </div>
      <div class="btn">Følgeseddel</div>
    </a>
  {% else %}
    {% if not error %}<p>Ingen fakturaer de seneste {{ days }} dage.</p>{% endif %}
  {% endfor %}
</body></html>"""

LOGIN_HTML = """<!doctype html><html lang="da"><head>""" + BASE_HEAD + """</head><body>
  <h2>PakPrint</h2>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="post">
    <label>Adgangskode</label>
    <input type="password" name="password" autofocus autocomplete="current-password">
    <button class="btn" type="submit">Log ind</button>
  </form>
</body></html>"""

ERROR_HTML = """<!doctype html><html lang="da"><head>""" + BASE_HEAD + """</head><body>
  <div class="error">{{ error }}</div><p><a href="/">Tilbage</a></p></body></html>"""


@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint in ("login", "static"):
        return None
    if not session.get("ok"):
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), APP_PASSWORD):
            session.permanent = True
            session["ok"] = True
            return redirect(url_for("index"))
        time.sleep(1)  # bremser gætteri
        error = "Forkert adgangskode"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/")
def index():
    invoices, error = [], None
    try:
        for i in get_latest_invoices():
            invoices.append({
                "guid": g(i, "Guid"),
                "name": g(i, "ContactName") or "Ukendt kunde",
                "number": g(i, "Number"),
                "date": fmt_date(g(i, "Date")),
                "draft": g(i, "Status") == "Draft",
            })
    except (DineroError, requests.RequestException) as e:
        error = str(e)
    return render_template_string(LIST_HTML, invoices=invoices, error=error, days=DAYS_BACK)


@app.route("/pdf/<guid>")
def download_pdf(guid):
    try:
        invoice = get_invoice_details(guid)
    except (DineroError, requests.RequestException) as e:
        return render_template_string(ERROR_HTML, error=str(e)), 502
    pdf_buffer = build_delivery_note_pdf(invoice)
    inv_no = g(invoice, "Number") or "kladde"
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=False,
                     download_name=f"foelgeseddel_{inv_no}.pdf")


# ---------------------------------------------------------------------------
# Terminal-kommandoer
# ---------------------------------------------------------------------------
def check_config():
    missing = [k for k, v in {"DINERO_CLIENT_ID": CLIENT_ID, "DINERO_CLIENT_SECRET": CLIENT_SECRET,
                              "DINERO_API_KEY": API_KEY, "DINERO_ORG_ID": ORG_ID}.items()
               if not v or v.endswith("_her")]
    return missing


def cmd_check():
    missing = check_config()
    if missing:
        print("✗ Mangler i .env:", ", ".join(missing))
        return 1
    try:
        get_dinero_token()
        print("✓ Login hos Dinero virker (Client ID/Secret + API-nøgle er OK)")
        invs = get_latest_invoices(limit=5)
        print(f"✓ Adgang til organisation {ORG_ID}. Seneste fakturaer:")
        for i in invs:
            print(f"   - {g(i, 'Number') or 'Kladde':>6}  {fmt_date(g(i, 'Date'))}  {g(i, 'ContactName')}")
        if invs:
            build_delivery_note_pdf(get_invoice_details(g(invs[0], "Guid")))
            print("✓ Følgeseddel-PDF kunne bygges for den nyeste faktura")
    except (DineroError, requests.RequestException) as e:
        print("✗", e)
        return 1
    if not APP_PASSWORD:
        print("! APP_PASSWORD er ikke sat - alle på netværket kan se dine fakturaer.")
    return 0


def cmd_demo():
    demo = {
        "ContactName": "Den Lille Delikatesse ApS", "Number": 1042, "Date": date.today().isoformat(),
        "Address": "Den Lille Delikatesse ApS\nHovedgaden 12\n4000 Roskilde\nDanmark",
        "ExternalReference": "Julebestilling", "Comment": "Leveres ved bagindgangen.",
        "ProductLines": [
            {"Description": "Juleknas med pekannødder 250 g", "Quantity": 24, "Unit": "parts", "LineType": "Product"},
            {"Description": "Gløggsirup – økologisk, 50 cl", "Quantity": 12, "Unit": "parts", "LineType": "Product",
             "Comments": "Holdbarhed: 31-03-2027"},
            {"Description": "Gaveæsker, blandet", "Quantity": 2, "Unit": "carton", "LineType": "Product"},
            {"Description": "Husk at returnere tomme kasser ved næste levering", "LineType": "Text"},
        ],
    }
    with open("demo_foelgeseddel.pdf", "wb") as f:
        f.write(build_delivery_note_pdf(demo).getvalue())
    print("✓ demo_foelgeseddel.pdf er lavet")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "check":
        sys.exit(cmd_check())
    if cmd == "demo":
        cmd_demo()
        sys.exit(0)
    missing = check_config()
    if missing:
        sys.exit("Mangler i .env: " + ", ".join(missing) + "  (se README.md)")
    if not APP_PASSWORD:
        print("ADVARSEL: APP_PASSWORD er ikke sat - appen er åben for alle på netværket.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
