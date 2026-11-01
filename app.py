"""API 650 Shell Calculator - single-file version (app.py).
Sections: 1) calculation engine, 2) PDF/Excel reports, 3) Streamlit interface."""
import math
from datetime import date
from io import BytesIO

import matplotlib.colors as mcolors
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm as rl_cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ############################################################
# 1) CALCULATION ENGINE (API 650)
# ############################################################

# ============================================================
# REFERENCE TABLES
# ============================================================

# (name, Fy [MPa], Sd [MPa], St [MPa]) - API 650 Table 5-2 (SI)
_MATERIAL_ROWS = [
    ("ASTM A283 Grade C", 205, 137, 154),
    ("ASTM A285 Grade C", 205, 137, 154),
    ("ASTM A131 Grade A/B", 235, 157, 171),
    ("ASTM A36", 250, 160, 171),
    ("ASTM A131 Grade EH36", 360, 196, 210),
    ("ASTM A573 Grade 400", 220, 147, 165),
    ("ASTM A573 Grade 450", 240, 160, 180),
    ("ASTM A573 Grade 485", 290, 193, 208),
    ("ASTM A516 Grade 380", 205, 137, 154),
    ("ASTM A516 Grade 415", 220, 147, 165),
    ("ASTM A516 Grade 450", 240, 160, 180),
    ("ASTM A516 Grade 485", 260, 173, 195),
    ("ASTM A662 Grade B", 275, 180, 193),
    ("ASTM A662 Grade C", 295, 194, 208),
    ("ASTM A537 Class 1 (t<=65mm)", 345, 194, 208),
    ("ASTM A537 Class 1 (65<t<=100mm)", 310, 180, 193),
    ("ASTM A537 Class 2 (t<=65mm)", 415, 220, 236),
    ("ASTM A537 Class 2 (65<t<=100mm)", 380, 206, 221),
    ("ASTM A633 Grade C/D (t<=65mm)", 345, 194, 208),
    ("ASTM A633 Grade C/D (65<t<=100mm)", 315, 180, 193),
    ("ASTM A737 Grade B", 345, 194, 208),
    ("ASTM A841 Class 1 (Grade A/B)", 345, 194, 208),
    ("ASTM A841 Class 2 (Grade A/B)", 415, 220, 236),
    ("CSA G40.21 Grade 260W", 260, 164, 176),
    ("CSA G40.21 Grade 260WT", 260, 164, 176),
    ("CSA G40.21 Grade 300W", 300, 176, 189),
    ("CSA G40.21 Grade 300WT", 300, 176, 189),
    ("CSA G40.21 Grade 350W", 350, 180, 193),
    ("CSA G40.21 Grade 350WT (t<=65mm)", 350, 180, 193),
    ("CSA G40.21 Grade 350WT (65<t<=100mm)", 320, 180, 193),
    ("National Standard Grade 235", 235, 137, 154),
    ("National Standard Grade 250", 250, 157, 171),
    ("National Standard Grade 275", 275, 167, 184),
    ("ISO 630 S275C/D (t<=16mm)", 275, 164, 176),
    ("ISO 630 S275C/D (16<t<=40mm)", 265, 164, 176),
    ("ISO 630 S355C/D (t<=16mm)", 355, 188, 201),
    ("ISO 630 S355C/D (16<t<=40mm)", 345, 188, 201),
    ("ISO 630 S355C/D (40<t<=50mm)", 335, 188, 201),
    ("EN 10025 S275J0/J2 (t<=16mm)", 275, 164, 176),
    ("EN 10025 S275J0/J2 (16<t<=40mm)", 265, 164, 176),
    ("EN 10025 S355J0/J2/K2 (t<=16mm)", 355, 188, 201),
    ("EN 10025 S355J0/J2/K2 (16<t<=40mm)", 345, 188, 201),
    ("EN 10025 S355J0/J2/K2 (40<t<=50mm)", 335, 188, 201),
]
MATERIALS = {n: {"Fy": fy, "Sd": sd, "St": st} for n, fy, sd, st in _MATERIAL_ROWS}

# Typical (indicative) specific gravity of stored products
PRODUCTS = {
    "Water": 1.000,
    "Sea water": 1.025,
    "Crude oil": 0.850,
    "Diesel": 0.850,
    "Gasoline": 0.740,
    "Kerosene / Jet fuel": 0.800,
    "Fuel oil (heavy)": 0.950,
    "Ethanol": 0.790,
    "Methanol": 0.790,
    "Sulfuric acid (98%)": 1.840,
    "Caustic soda / NaOH (50%)": 1.530,
    "LPG (liquid phase)": 0.510,
}

STEEL_DENSITY = 7850      # kg/m3
MAX_PLATE_MM = 45         # shell plate thickness limit to check (API 650 s.4.2)

# ============================================================
# ONE-FOOT METHOD (s.5.6.3)
# ============================================================

def table_min(D):
    """Minimum nominal shell thickness (mm) from tank diameter (m) - s.5.6.1.1."""
    if D < 15:
        return 5
    if D < 36:
        return 6
    if D <= 60:
        return 8
    return 10


def round_commercial(t, step=0.5):
    """Round a thickness up to the next commercial step (mm)."""
    return math.ceil(round(t / step, 9)) * step


def heff_pressure(h, P, G):
    """Equivalent liquid head with internal pressure P (kPa): h + P/(9.81 G).
    Used for DESIGN conditions only (eq. 3.13 of the report)."""
    if P <= 0:
        return h
    return h + P / (9.81 * G)


def one_foot_td(D, H, G, Sd, CA):
    """Design thickness (mm): 4.9 D (H-0.3) G / Sd + CA."""
    return (4.9 * D * (H - 0.3) * G) / Sd + CA


def one_foot_tt(D, H, St):
    """Hydrostatic test thickness (mm): 4.9 D (H-0.3) / St."""
    return (4.9 * D * (H - 0.3)) / St

# ============================================================
# VARIABLE DESIGN POINT METHOD (s.5.6.4)
# ============================================================

def vdp_course1(D, H, G, S, CA, is_design):
    """Bottom course, VDP method, capped by the one-foot value."""
    if is_design:
        tp = (4.9 * D * (H - 0.3) * G) / S + CA
        factor = 1.06 - (0.0696 * D / H) * math.sqrt((H * G) / S)
        t1 = factor * (4.9 * H * D * G / S) + CA
    else:
        tp = (4.9 * D * (H - 0.3)) / S
        factor = 1.06 - (0.0696 * D / H) * math.sqrt(H / S)
        t1 = factor * (4.9 * H * D / S)
    return min(t1, tp)


def vdp_upper_course(tL, tu_init, D, H, r, S, G, max_iter=30, tol=1e-3):
    """Upper course: variable design point x and iteration on tu.
    tL, tu_init and the result are CORRODED thicknesses (without CA)."""
    tu = max(tu_init, 0.1)
    tL = max(tL, 0.1)
    for _ in range(max_iter):
        K = tL / tu
        C = (math.sqrt(K) * (K - 1)) / (1 + K ** 1.5)
        x1 = 0.61 * math.sqrt(r * tu) + 320 * C * H
        x2 = 1000 * C * H
        x3 = 1.22 * math.sqrt(r * tu)
        x = min(x1, x2, x3)
        tx = 4.9 * D * max(H - x / 1000, 0) * G / S
        if abs(tx - tu) < tol:
            return max(tx, 0.1)
        tu = max(tx, 0.1)
    return tu


def vdp_course2(h1, r, t1, t2a):
    """Second course: ratio h1/sqrt(r t1) and interpolation (eq. 3.6-3.7)."""
    t1 = max(t1, 0.1)
    ratio = h1 / math.sqrt(r * t1)
    if ratio <= 1.375:
        return t1
    if ratio >= 2.625:
        return t2a
    return t2a + (t1 - t2a) * (2.1 - h1 / (1.25 * math.sqrt(r * t1)))

# ============================================================
# WIND GIRDER (s.5.9)
# ============================================================

def wind_pressure(V):
    """Design wind pressure from wind speed V (km/h): Pwv, Pwd (kPa)."""
    Pwv = 1.48 * (V / 190) ** 2
    return Pwv, Pwv + 0.24


def h1_max_unstiffened(D, t, V):
    """Maximum height of unstiffened shell H1 (m); t in mm, D in m."""
    _, Pwd = wind_pressure(V)
    return 9.47 * t * math.sqrt((t / D) ** 3 * (1.72 / Pwd))


def transformed_shell_height(courses, t_uniform):
    """Transposed (transformed) shell height (m) and per-course detail."""
    detail, total = [], 0.0
    for c in courses:
        W = c["Height (m)"] * 1000
        t_act = c["Thickness (mm)"]
        Wtr = W * (t_uniform / t_act) ** 2.5
        total += Wtr
        detail.append({"Course": c["Course"], "W (mm)": round(W, 1),
                       "t (mm)": t_act, "Wtr (mm)": round(Wtr, 1)})
    return total / 1000, detail


def _section_modulus(D, h, Fy, V):
    """Z (cm3) = 6 h D^2 (Pwd/1.72) / (0.5 Fy), D <= 61 m, Fy <= 210 MPa."""
    _, Pwd = wind_pressure(V)
    return 6 * h * min(D, 61) ** 2 * (Pwd / 1.72) / (0.5 * min(Fy, 210))


def z_top_wind_girder(D, H2, Fy, V):
    return _section_modulus(D, H2, Fy, V)


def z_intermediate_wind_girder(D, h1, Fy, V):
    return _section_modulus(D, h1, Fy, V)


def _real_height_from_transformed(courses, t_uniform, s_tr):
    """Real distance (m) from the shell top for a point located at the
    transformed distance s_tr (m) from the top. Courses are walked top-down."""
    remaining = s_tr * 1000
    real = 0.0
    for c in reversed(courses):
        W = c["Height (m)"] * 1000
        f = (t_uniform / c["Thickness (mm)"]) ** 2.5
        if remaining <= W * f:
            return (real + remaining / f) / 1000
        remaining -= W * f
        real += W
    return real / 1000


def check_wind_girder(D, H_shell, courses, V, Fy=250.0):
    """Complete wind girder check: H1, transformed height, number and
    position of intermediate girders, Z top and Z intermediate."""
    t_uniform = min(c["Thickness (mm)"] for c in courses)
    H1 = h1_max_unstiffened(D, t_uniform, V)
    H_tr, detail = transformed_shell_height(courses, t_uniform)
    Pwv, Pwd = wind_pressure(V)

    n = 0 if H_tr <= H1 else math.ceil(round(H_tr / H1, 9)) - 1

    positions, h1_list = [], []
    if n:
        seg = H_tr / (n + 1)
        prev = 0.0
        for k in range(1, n + 1):
            real = _real_height_from_transformed(courses, t_uniform, k * seg)
            positions.append(round(H_shell - real, 2))   # height above the bottom
            h1_list.append(real - prev)
            prev = real
    h1_real = max(h1_list) if h1_list else None

    Z_top = z_top_wind_girder(D, H_shell, Fy, V)
    Z_int = z_intermediate_wind_girder(D, h1_real, Fy, V) if h1_real else None
    return {
        "V_kmh": V, "Pwv_kPa": round(Pwv, 3), "Pwd_kPa": round(Pwd, 3),
        "t_uniform_mm": t_uniform,
        "H1_m": round(H1, 3),
        "H_transformed_m": round(H_tr, 3),
        "detail_per_course": detail,
        "n_intermediate_girders_required": n,
        "intermediate_positions_m": positions,
        "h1_real_m": round(h1_real, 3) if h1_real else None,
        "Z_top_cm3": round(Z_top, 1),
        "Z_intermediate_cm3": round(Z_int, 1) if Z_int else None,
        "Fy_used_MPa": min(Fy, 210),
    }

# ============================================================
# MAIN CALCULATION
# ============================================================

def nombre_plaques(D, L_plaque_mm=6000):
    return math.ceil((math.pi * D * 1000) / L_plaque_mm)


def calculer_reservoir(D, H_shell, H_liquide, h_course_mm, G, CA, Sd, St,
                       method="AUTO", P=0.0, V=0.0, L_plaque_mm=6000,
                       Fy=250.0, step=0.5):
    r = D * 1000 / 2
    msgs = []

    if H_liquide > H_shell:
        msgs.append("Liquid level > shell height: capped to shell height.")
        H_liquide = H_shell
    elif H_liquide < H_shell:
        msgs.append(f"Freeboard = {H_shell - H_liquide:.2f} m")

    method_used = ("ONEFOOT" if D <= 61 else "VDP") if method == "AUTO" else method
    if method_used == "ONEFOOT" and D > 61:
        return {"valid": False, "method_used": method_used, "courses": [],
                "wind": None, "poids_total_kg": 0, "messages": msgs,
                "error": "One-Foot Method is not allowed for D > 61 m (s.5.6.3.1)."}

    n_full = int((H_shell * 1000) // h_course_mm)
    remainder = H_shell * 1000 - n_full * h_course_mm
    heights = [h_course_mm] * n_full + ([remainder] if remainder > 1 else [])
    cum_bottom, cum = [], 0.0
    for h in heights:
        cum_bottom.append(cum / 1000)
        cum += h

    courses, trace = [], []
    t_prev = None
    tmin = table_min(D)

    for i, h_mm in enumerate(heights):
        h_loc = H_liquide - cum_bottom[i]
        td = tt = 0.0
        note = ""
        if h_loc > 0.30:
            h_d = heff_pressure(h_loc, P, G)   # design: with pressure
            h_t = h_loc                         # test: real head only
            if method_used == "ONEFOOT":
                td = one_foot_td(D, h_d, G, Sd, CA)
                tt = one_foot_tt(D, h_t, St)
                note = (f"td = 4.9 x {D:g} x ({h_d:.2f} - 0.3) x {G:g} / {Sd:g} + {CA:g} = {td:.2f} mm | "
                        f"tt = 4.9 x {D:g} x ({h_t:.2f} - 0.3) / {St:g} = {tt:.2f} mm")
            elif i == 0:
                td = vdp_course1(D, h_d, G, Sd, CA, True)
                tt = vdp_course1(D, h_t, 1.0, St, 0, False)
                note = "VDP bottom course (eq. 3.4 / 3.5), capped by one-foot value"
            else:
                tL_d, tL_t = max(t_prev - CA, 0.1), t_prev
                tu_d = one_foot_td(D, h_d, G, Sd, 0)
                tu_t = one_foot_tt(D, h_t, St)
                t_d = vdp_upper_course(tL_d, tu_d, D, h_d, r, Sd, G)
                t_t = vdp_upper_course(tL_t, tu_t, D, h_t, r, St, 1.0)
                if i == 1:
                    t_d = vdp_course2(heights[0], r, tL_d, t_d)
                    t_t = vdp_course2(heights[0], r, tL_t, t_t)
                td, tt = t_d + CA, t_t
                note = "VDP upper course (eq. 3.8 to 3.12)"
        else:
            note = "Course above the one-foot design point: minimum thickness governs"

        governing = max(td, tt, tmin)
        t_use = round_commercial(governing, step)
        t_prev = t_use
        courses.append({
            "Course": i + 1,
            "Height (m)": round(h_mm / 1000, 3),
            "Local liquid head (m)": round(max(h_loc, 0), 2),
            "td (mm)": round(td, 2),
            "tt (mm)": round(tt, 2),
            "t min (mm)": tmin,
            "Governing t (mm)": round(governing, 2),
            "Thickness (mm)": t_use,
            "Nb Plates": nombre_plaques(D, L_plaque_mm),
        })
        trace.append({"Course": i + 1, "Detail": note})

    validity_msg = ""
    if method_used == "VDP":
        t1_corr = max(courses[0]["Thickness (mm)"] - CA, 0.1)
        L = math.sqrt(500 * D * t1_corr)
        ratio = L / H_liquide
        validity_msg = (f"VDP applicable: L/H = {ratio:.2f} <= 1000/6" if ratio <= 1000 / 6
                        else f"WARNING: outside the VDP domain (L/H = {ratio:.2f} > 1000/6)")

    warnings = []
    if P > 0:
        msgs.append(f"Internal pressure {P:g} kPa included in DESIGN thickness only.")
    if any(c["Thickness (mm)"] > MAX_PLATE_MM for c in courses):
        warnings.append(f"A course exceeds {MAX_PLATE_MM} mm: check the plate thickness limit of API 650 s.4.2.")

    wind = check_wind_girder(D, H_shell, courses, V, Fy) if V > 0 else None

    weight = sum(math.pi * D * c["Height (m)"] * c["Thickness (mm)"] / 1000 * STEEL_DENSITY
                 for c in courses)

    return {
        "valid": True, "D": D, "H_shell": H_shell, "H_liquide": H_liquide,
        "method_used": method_used, "validity_msg": validity_msg,
        "messages": msgs, "warnings": warnings,
        "courses": courses, "trace": trace, "wind": wind,
        "poids_total_kg": round(weight, 0),
        "inputs": {"D": D, "H_shell": H_shell, "H_liquide": H_liquide, "G": G,
                   "CA": CA, "Sd": Sd, "St": St, "Fy": Fy, "P": P, "V": V,
                   "h_course_mm": h_course_mm, "L_plaque_mm": L_plaque_mm},
    }

# ############################################################
# 2) PDF AND EXCEL REPORTS
# ############################################################


HEADER_COLOR = colors.HexColor("#1f3a5f")


def _table(data, col_widths=None, header=False, font=9):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
             ("FONTSIZE", (0, 0), (-1, -1), font)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
                  ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("ALIGN", (0, 0), (-1, -1), "CENTER")]
    else:
        style += [("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke)]
    t.setStyle(TableStyle(style))
    return t


def _input_rows(res, material, product):
    i = res["inputs"]
    rows = [
        ["Diameter D (m)", f"{i['D']:.2f}"],
        ["Total shell height (m)", f"{i['H_shell']:.2f}"],
        ["Design liquid level H (m)", f"{res['H_liquide']:.2f}"],
        ["Course height (mm)", f"{i['h_course_mm']:.0f}"],
        ["Product / specific gravity G", f"{product} / {i['G']:g}"],
        ["Material", material],
        ["Sd / St (MPa)", f"{i['Sd']:g} / {i['St']:g}"],
        ["Corrosion allowance CA (mm)", f"{i['CA']:g}"],
        ["Internal pressure P (kPa)", f"{i['P']:g}"],
        ["Method used", res["method_used"]],
    ]
    if i["V"] > 0:
        rows.append(["Design wind speed V (km/h)", f"{i['V']:g}"])
    return rows


def generer_rapport_pdf(res, material, product,
                        titre="API 650 - Shell Design Calculation Report"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * rl_cm, bottomMargin=1.5 * rl_cm)
    st = getSampleStyleSheet()
    story = [Paragraph(titre, st["Title"]),
             Paragraph(f"Date: {date.today():%d/%m/%Y}", st["Normal"]), Spacer(1, 12)]

    story += [Paragraph("1. Input parameters", st["Heading2"]),
              _table(_input_rows(res, material, product), [7 * rl_cm, 8 * rl_cm]),
              Spacer(1, 14)]

    story.append(Paragraph("2. Shell thickness schedule", st["Heading2"]))
    headers = ["Course", "Height (m)", "Local head (m)", "td (mm)", "tt (mm)",
               "t min (mm)", "Governing (mm)", "Selected (mm)", "Plates"]
    data = [headers] + [[c["Course"], c["Height (m)"], c["Local liquid head (m)"], c["td (mm)"],
                         c["tt (mm)"], c["t min (mm)"], c["Governing t (mm)"],
                         c["Thickness (mm)"], c["Nb Plates"]] for c in res["courses"]]
    story += [_table(data, header=True, font=7.5), Spacer(1, 6),
              Paragraph("Governing thickness = max(td, tt, t min); selected thickness = governing "
                        "thickness rounded up to the commercial step.", st["Italic"]),
              Spacer(1, 14)]

    story.append(Paragraph("3. Calculation trace", st["Heading2"]))
    for t in res["trace"]:
        story.append(Paragraph(f"<b>Course {t['Course']}:</b> {t['Detail']}", st["Normal"]))
    story.append(Spacer(1, 14))

    story += [Paragraph("4. Shell weight estimate", st["Heading2"]),
              Paragraph(f"Total shell weight: <b>{res['poids_total_kg']:.0f} kg</b> "
                        "(steel 7850 kg/m3; welds, cutting waste and accessories not included).",
                        st["Normal"])]

    if res["wind"]:
        w = res["wind"]
        story += [Spacer(1, 14), Paragraph("5. Wind girder verification (API 650 s.5.9)", st["Heading2"])]
        rows = [
            ["Design wind pressure Pwd (kPa)", f"{w['Pwd_kPa']}"],
            ["Reference thickness t (mm)", f"{w['t_uniform_mm']}"],
            ["H1 - max unstiffened height (m)", f"{w['H1_m']}"],
            ["Transformed shell height (m)", f"{w['H_transformed_m']}"],
            ["Intermediate girders required", f"{w['n_intermediate_girders_required']}"],
            ["Z top girder required (cm3)", f"{w['Z_top_cm3']}"],
            ["Z intermediate girder required (cm3)", f"{w['Z_intermediate_cm3'] or 'N/A'}"],
        ]
        if w["intermediate_positions_m"]:
            rows.insert(5, ["Intermediate girder heights above bottom (m)",
                            ", ".join(f"{p:.2f}" for p in w["intermediate_positions_m"])])
        story.append(_table(rows, [9 * rl_cm, 6 * rl_cm]))
        verdict = ("No intermediate wind girder required."
                   if w["n_intermediate_girders_required"] == 0
                   else f"{w['n_intermediate_girders_required']} intermediate wind girder(s) required.")
        story += [Spacer(1, 8),
                  Paragraph(f"<b>Verdict:</b> {verdict} A top wind girder (Z >= {w['Z_top_cm3']} cm3) "
                            "is mandatory.", st["Normal"])]

    doc.build(story)
    buffer.seek(0)
    return buffer


def generer_rapport_excel(res, material, product):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(_input_rows(res, material, product), columns=["Parameter", "Value"]) \
            .to_excel(writer, sheet_name="Inputs", index=False)
        pd.DataFrame(res["courses"]).to_excel(writer, sheet_name="Thickness schedule", index=False)
        pd.DataFrame(res["trace"]).to_excel(writer, sheet_name="Calculation trace", index=False)

        summary = [["Total shell weight (kg)", res["poids_total_kg"]]]
        if res["wind"]:
            w = res["wind"]
            summary += [["Design wind pressure Pwd (kPa)", w["Pwd_kPa"]],
                        ["H1 (m)", w["H1_m"]],
                        ["Transformed shell height (m)", w["H_transformed_m"]],
                        ["Intermediate girders required", w["n_intermediate_girders_required"]],
                        ["Z top girder (cm3)", w["Z_top_cm3"]],
                        ["Z intermediate girder (cm3)", w["Z_intermediate_cm3"] or "N/A"]]
        pd.DataFrame(summary, columns=["Metric", "Value"]).to_excel(
            writer, sheet_name="Summary", index=False)
        if res["wind"]:
            pd.DataFrame(res["wind"]["detail_per_course"]).to_excel(
                writer, sheet_name="Wind transformed width", index=False)
    buffer.seek(0)
    return buffer

# ############################################################
# 3) STREAMLIT INTERFACE
# ############################################################


st.set_page_config(page_title="API 650 Shell Calculator", page_icon="🏗️", layout="wide")

# ============================================================
# DEFAULT VALUES AND VALIDATION EXAMPLE
# ============================================================
SELECT = "— Select —"
CUSTOM = "Custom / Other"

DEFAULTS = dict(D=0.0, H_shell=0.0, H_liq=0.0, h_course=0.0, L_plate=0.0,
                product=SELECT, material=SELECT, G_custom=0.0,
                Sd_custom=0.0, St_custom=0.0, Fy_custom=0.0,
                CA=0.0, method="AUTO", use_p=False, P=0.0, use_w=False, V=0.0)

EXAMPLE = dict(D=30.0, H_shell=14.4, H_liq=14.0, h_course=2400.0, L_plate=6000.0,
               product="Sulfuric acid (98%)", material="ASTM A36",
               CA=3.0, method="AUTO", use_p=False, P=0.0, use_w=True, V=140.0)

for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def load_example():
    st.session_state.update(EXAMPLE)
    st.session_state.pop("resultat", None)


def reset_form():
    st.session_state.update(DEFAULTS)
    st.session_state.pop("resultat", None)


# ============================================================
# SHELL DIAGRAM
# ============================================================
def dessiner_schema_reservoir(res):
    courses, D = res["courses"], res["D"]
    H_liquide, H_shell = res["H_liquide"], res["H_shell"]

    ts = [c["Thickness (mm)"] for c in courses]
    norm = mcolors.Normalize(vmin=min(ts), vmax=max(max(ts), min(ts) + 0.1))
    cmap = plt.get_cmap("Blues")
    width = 4.0

    fig, ax = plt.subplots(figsize=(4.5, 7))
    y = 0.0
    for c in courses:
        h, t = c["Height (m)"], c["Thickness (mm)"]
        col = cmap(0.15 + 0.85 * norm(t))
        ax.add_patch(patches.Rectangle((0, y), width, h, facecolor=col,
                                       edgecolor="#333333", linewidth=1.1))
        lum = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
        ax.text(width / 2, y + h / 2, f"C{c['Course']} — {t:.1f} mm", ha="center",
                va="center", fontsize=9, weight="bold",
                color="white" if lum < 0.55 else "black")
        y += h

    ax.axhline(H_liquide, color="#1f77b4", linestyle="--", linewidth=1.8)
    ax.text(width + 0.15, H_liquide, f"Liquid level\nH = {H_liquide:.2f} m",
            va="center", fontsize=8.5, color="#1f77b4")
    if H_shell > H_liquide:
        ax.text(width + 0.15, H_shell, f"Shell top\n{H_shell:.2f} m",
                va="center", fontsize=8.5, color="#555555")
    if res["wind"]:
        for p in res["wind"]["intermediate_positions_m"]:
            ax.plot([-0.2, width + 0.2], [p, p], color="#c0392b", linewidth=3)
            ax.text(-0.3, p, "wind girder", ha="right", va="center", fontsize=8, color="#c0392b")

    ax.set_xlim(-1.6, width + 2.3)
    ax.set_ylim(0, max(H_shell, y) * 1.05)
    ax.set_xticks([])
    ax.set_ylabel("Height (m)")
    ax.set_title(f"Shell cross-section — D = {D:.1f} m", fontsize=11, weight="bold")
    for s in ("top", "right", "bottom"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    return fig


# ============================================================
# SIDEBAR - INPUTS
# ============================================================
st.sidebar.title("Inputs")
c_ex, c_rs = st.sidebar.columns(2)
c_ex.button("Load example", on_click=load_example, use_container_width=True,
            help="Fills the form with the validation case (D = 30 m, sulfuric acid, ASTM A36, wind 140 km/h).")
c_rs.button("Reset", on_click=reset_form, use_container_width=True)

with st.sidebar.expander("1. Tank geometry", expanded=True):
    st.number_input("Diameter D (m)", min_value=0.0, step=0.5, key="D")
    st.number_input("Total shell height (m)", min_value=0.0, step=0.5, key="H_shell",
                    help="Physical height of the plating; determines the number of courses.")
    st.number_input("Design liquid level H (m)", min_value=0.0, step=0.5, key="H_liq",
                    help="Maximum fill level, used in all stress formulas.")
    st.number_input("Course height (mm)", min_value=0.0, step=100.0, key="h_course")
    st.number_input("Standard plate length (mm)", min_value=0.0, step=100.0, key="L_plate",
                    help="Used to count the plates per course.")

with st.sidebar.expander("2. Product and material", expanded=True):
    st.selectbox("Stored product", [SELECT] + list(PRODUCTS) + [CUSTOM], key="product")
    if st.session_state.product == SELECT:
        G = 0.0
    elif st.session_state.product == CUSTOM:
        G = st.number_input("Specific gravity G", min_value=0.0, step=0.05, key="G_custom")
    else:
        G = PRODUCTS[st.session_state.product]
        st.caption(f"Specific gravity G = **{G}**")

    st.selectbox("Shell material (API 650 Table 5-2)", [SELECT] + list(MATERIALS) + [CUSTOM],
                 key="material")
    if st.session_state.material == SELECT:
        Sd = St = Fy = 0.0
    elif st.session_state.material == CUSTOM:
        Sd = st.number_input("Design stress Sd (MPa)", min_value=0.0, step=1.0, key="Sd_custom")
        St = st.number_input("Test stress St (MPa)", min_value=0.0, step=1.0, key="St_custom")
        Fy = st.number_input("Yield strength Fy (MPa)", min_value=0.0, step=5.0, key="Fy_custom")
    else:
        m = MATERIALS[st.session_state.material]
        Sd, St, Fy = m["Sd"], m["St"], m["Fy"]
        st.caption(f"Sd = **{Sd} MPa** · St = **{St} MPa** · Fy = **{Fy} MPa**")

with st.sidebar.expander("3. Design options", expanded=True):
    st.number_input("Corrosion allowance CA (mm)", min_value=0.0, step=0.5, key="CA")
    st.selectbox("Calculation method", ["AUTO", "ONEFOOT", "VDP"], key="method",
                 help="AUTO: one-foot up to 61 m, variable design point above.")
    st.checkbox("Fixed roof with internal pressure", key="use_p")
    P = st.number_input("Design pressure P (kPa)", min_value=0.0, step=0.5, key="P") \
        if st.session_state.use_p else 0.0
    st.checkbox("Wind girder verification", key="use_w")
    V = st.number_input("Design wind speed V (km/h)", min_value=0.0, step=5.0, key="V") \
        if st.session_state.use_w else 0.0

run_clicked = st.sidebar.button("Run calculation", type="primary", use_container_width=True)

# ============================================================
# RUN
# ============================================================
if run_clicked:
    ss = st.session_state
    required = {"Diameter": ss.D, "Total shell height": ss.H_shell, "Design liquid level": ss.H_liq,
                "Course height": ss.h_course, "Plate length": ss.L_plate,
                "Stored product": G, "Material (Sd, St)": Sd and St}
    missing = [k for k, v in required.items() if not v]
    if st.session_state.use_w and not V:
        missing.append("Wind speed")
    if st.session_state.use_w and not Fy:
        missing.append("Yield strength Fy")
    if missing:
        st.error("Please fill in: " + ", ".join(missing) + ".")
        st.stop()
    result = calculer_reservoir(
        D=ss.D, H_shell=ss.H_shell, H_liquide=ss.H_liq, h_course_mm=ss.h_course,
        G=G, CA=ss.CA, Sd=Sd, St=St, method=ss.method, P=P, V=V,
        L_plaque_mm=ss.L_plate, Fy=Fy)
    result["material"] = ss.material
    result["product"] = ss.product
    ss["resultat"] = result

# ============================================================
# MAIN AREA
# ============================================================
st.title("🏗️ API 650 Shell Calculator")
st.caption("Design of the shell of welded atmospheric storage tanks — API 650, 13th edition")

if "resultat" not in st.session_state:
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1f3a5f 0%, #2f6190 100%);
                    padding: 38px 40px; border-radius: 12px; color: white; margin-bottom: 24px;">
            <h2 style="margin:0 0 8px 0; color:white;">Tank shell design, traceable and compliant.</h2>
            <p style="margin:0; font-size: 16px; opacity: 0.92; max-width: 680px;">
                Enter the tank geometry, product and material in the sidebar to obtain the complete
                shell thickness schedule, the wind girder verification, the shell weight estimate
                and a calculation report.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("👈 Fill in the sidebar and click **Run calculation**, or click **Load example** "
            "to try the validation case.")
    st.stop()

res = st.session_state["resultat"]
if not res["valid"]:
    st.error(res["error"])
    st.stop()

for msg in res["messages"]:
    st.caption(f"ℹ️ {msg}")
if res["validity_msg"]:
    (st.warning if res["validity_msg"].startswith("WARNING") else st.success)(res["validity_msg"])
for w_msg in res["warnings"]:
    st.warning(w_msg)

# --- Key figures ---
k1, k2, k3, k4 = st.columns(4)
k1.metric("Method", res["method_used"])
k2.metric("Number of courses", len(res["courses"]))
k3.metric("Maximum thickness (mm)", max(c["Thickness (mm)"] for c in res["courses"]))
k4.metric("Shell weight (kg)", f"{res['poids_total_kg']:,.0f}")

tab_res, tab_wind, tab_trace, tab_export = st.tabs(
    ["Thickness schedule", "Wind girder", "Calculation trace", "Reports"])

with tab_res:
    col_t, col_s = st.columns([2, 1])
    with col_t:
        st.subheader("Shell thickness schedule")
        st.dataframe(pd.DataFrame(res["courses"]), hide_index=True, use_container_width=True)
        st.caption("Governing thickness = max(td, tt, t min). Selected thickness = governing "
                   "thickness rounded up to the next 0.5 mm.")
        st.subheader("Shell weight estimate")
        st.metric("Total shell weight (kg)", f"{res['poids_total_kg']:,.0f}")
        st.caption("Steel density 7850 kg/m³, selected thicknesses. Welds, cutting waste, "
                   "stiffeners, nozzles, bottom and roof are not included.")
    with col_s:
        st.subheader("Shell diagram")
        st.pyplot(dessiner_schema_reservoir(res))

with tab_wind:
    w = res["wind"]
    if not w:
        st.info("Wind girder verification is disabled. Tick **Wind girder verification** "
                "in the sidebar and enter the design wind speed.")
    else:
        st.subheader("Wind girder verification (API 650 §5.9)")
        c1, c2, c3 = st.columns(3)
        c1.metric("H1 — max unstiffened height (m)", w["H1_m"])
        c2.metric("Transformed shell height (m)", w["H_transformed_m"])
        c3.metric("Intermediate girders required", w["n_intermediate_girders_required"])
        if w["n_intermediate_girders_required"] == 0:
            st.success("No intermediate wind girder required (transformed height ≤ H1).")
        else:
            pos = ", ".join(f"{p:.2f} m" for p in w["intermediate_positions_m"])
            st.warning(f"{w['n_intermediate_girders_required']} intermediate wind girder(s) required, "
                       f"at about {pos} above the tank bottom.")
        c4, c5, c6 = st.columns(3)
        c4.metric("Design wind pressure Pwd (kPa)", w["Pwd_kPa"])
        c5.metric("Z top girder required (cm³)", w["Z_top_cm3"])
        if w["Z_intermediate_cm3"]:
            c6.metric("Z intermediate girder required (cm³)", w["Z_intermediate_cm3"])
        st.caption(f"Fy used in the section modulus formulas: {w['Fy_used_MPa']:g} MPa "
                   "(limited to 210 MPa). A top wind girder is always required on an open-top tank.")
        with st.expander("Transformed width per course"):
            st.dataframe(pd.DataFrame(w["detail_per_course"]), hide_index=True,
                         use_container_width=True)

with tab_trace:
    st.subheader("Calculation trace")
    st.caption("Each line shows the formula with the numerical values, so that every result "
               "can be re-calculated by hand.")
    for t in res["trace"]:
        st.markdown(f"**Course {t['Course']}** — {t['Detail']}")

with tab_export:
    st.subheader("Download the calculation report")
    c_pdf, c_xls = st.columns(2)
    c_pdf.download_button("📄 PDF report", data=generer_rapport_pdf(res, res["material"], res["product"]),
                          file_name="api650_calculation_report.pdf", mime="application/pdf",
                          use_container_width=True)
    c_xls.download_button("📊 Excel report", data=generer_rapport_excel(res, res["material"], res["product"]),
                          file_name="api650_calculation_report.xlsx",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          use_container_width=True)

st.caption("Results must be checked by a qualified engineer before use in a design.")
