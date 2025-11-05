import os, json, re
from typing import Any, Dict, Optional
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None  # allow /health to run

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

client = Anthropic(api_key=ANTHROPIC_API_KEY) if (Anthropic and ANTHROPIC_API_KEY) else None

app = FastAPI(title="Claude Notes API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ------------------ Prompt & schema ------------------

SYSTEM = (
    "You are a clinical documentation assistant creating wound-care notes for the EHR.\n"
    "Strict rules:\n"
    "1) Output **ONLY valid JSON**, no prolog, no markdown fences.\n"
    "2) Do **NOT** invent values. If missing, write null or 'unspecified'.\n"
    "3) Prefer units: area cm^2, depth mm, volume cm^3. Round: area 1dp, depth 1dp, volume 2dp, percentages 0dp.\n"
    "4) Be concise, EPIC SmartText style. Use bullets, not paragraphs.\n"
    "5) Do not diagnose; this is decision support.\n"
    "Required JSON shape:\n"
    "{\n"
    '  "note_md": string,                  // chart-ready Markdown only\n'
    '  "flowsheet": {                      // key EHR-friendly fields for import\n'
    '      "surface_area_cm2": number|null,\n'
    '      "avg_depth_mm": number|null,\n'
    '      "max_depth_mm": number|null,\n'
    '      "volume_cm3": number|null,\n'
    '      "tissue_pct": {"granulation":number|null,"slough":number|null,"eschar":number|null,"epithelial":number|null}\n'
    "  },\n"
    '  "codes": {                          // optional suggestions (strings only)\n'
    '      "icd10": string[],\n'
    '      "cpt": string[]\n'
    "  },\n"
    '  "orders": string[],                 // e.g., dressing/offloading/ABI/toe-pressure\n'
    '  "flags": string[]                   // e.g., "Consider infection workup", "Ischemia data missing"\n'
    "}\n"
)

NOTE_STYLE_EPIC = (
    "Create an EPIC-style SmartText note with sections:\n"
    "## Wound Assessment\n"
    "### Characteristics\n"
    "- Surface area: {surface_area_cm2} cm^2\n"
    "- Avg depth: {avg_depth_mm} mm; Max depth: {max_depth_mm} mm\n"
    "- Volume: {volume_cm3} cm^3\n"
    "### Tissue Composition\n"
    "- Granulation: {granulation}% | Slough: {slough}% | Eschar: {eschar}% | Epithelial: {epithelial}%\n"
    "### Classification & Etiology (decision support)\n"
    "- Primary staging system(s) applicable and label(s)\n"
    "- Top etiologies with simple %\n"
    "### Plan / Next Steps\n"
    "- Concrete, brief bullets: cleansing, debridement (if indicated), dressing, offloading/pressure relief, infection risk, perfusion data needed (ABI/toe), follow-up window\n"
    "### Uncertainty / Data Gaps\n"
    "- Single line, if any\n"
)

def _num(x: Optional[float]) -> Optional[float]:
    try:
        if x is None: return None
        return float(x)
    except Exception:
        return None

def build_payload(analytics: Dict[str, Any], classification: Dict[str, Any], ask: str) -> str:
    """Provide normalized inputs so the model doesn't guess units."""
    t = analytics.get("tissue_pct") or {}
    payload = {
        "style_hint": ask or "epic_short",
        "template_hint": NOTE_STYLE_EPIC,
        "analytics": {
            "surface_area_cm2": _num(analytics.get("area_cm2")),
            "avg_depth_mm":     _num(analytics.get("avg_depth_mm")),
            "max_depth_mm":     _num(analytics.get("max_depth_mm")),
            "volume_cm3":       _num(analytics.get("volume_cm3")),
            "tissue_pct": {
                "granulation": _num(t.get("granulation")*100 if isinstance(t.get("granulation"), (int,float)) and t.get("granulation")<=1 else t.get("granulation")),
                "slough":      _num(t.get("slough")*100      if isinstance(t.get("slough"), (int,float))      and t.get("slough")<=1      else t.get("slough")),
                "eschar":      _num(t.get("eschar")*100      if isinstance(t.get("eschar"), (int,float))      and t.get("eschar")<=1      else t.get("eschar")),
                "epithelial":  _num(t.get("epithelial")*100  if isinstance(t.get("epithelial"), (int,float))  and t.get("epithelial")<=1  else t.get("epithelial")),
            }
        },
        "classification": classification or {}
    }
    return json.dumps(payload)

def extract_json(txt: str) -> Dict[str, Any]:
    """Claude sometimes wraps JSON in fencing; strip if needed and parse."""
    s = txt.strip()
    # Remove fences if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s)

# ------------------ Routes ------------------

@app.get("/health")
def health():
    return {
        "ok": True,
        "client": bool(client),
        "model": ANTHROPIC_MODEL,
        "stub": not bool(ANTHROPIC_API_KEY),
    }

@app.post("/api/draft-note")
def draft_note(payload: Dict[str, Any] = Body(...)):
    if not client:
        # graceful offline mode
        return {
            "note_md": "(Claude API not configured)\n\n- Install `anthropic` and set ANTHROPIC_API_KEY",
            "flowsheet": {}, "codes": {"icd10":[],"cpt":[]}, "orders": [], "flags": ["no_api_key"]
        }

    analytics = payload.get("analytics") or {}
    classification = payload.get("classification") or {}
    ask = payload.get("ask", "epic_short")

    user = build_payload(analytics, classification, ask)

    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            system=SYSTEM,
            max_tokens=800,
            temperature=0,   # deterministic, no waffle
            messages=[{"role":"user","content":user}],
        )
        out = extract_json(resp.content[0].text)
        # minimal validation
        if "note_md" not in out:
            raise ValueError("Missing note_md")
        return out
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Anthropic call failed: {e}")
