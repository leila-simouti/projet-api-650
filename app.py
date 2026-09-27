import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import math
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import cm as rl_cm

# ============================================================
# API 650 — REFERENCE TABLES
# ============================================================

# Table 5.2a (SI units) — Permissible plate materials and allowable stresses (MPa)
MATERIALS = {
    # --- ASTM Specifications ---
    "ASTM A283 Grade C":          { "Sd": 137, "St": 154 },
    "ASTM A285 Grade C":          { "Sd": 137, "St": 154 },
    "ASTM A131 Grade A/B":        { "Sd": 157, "St": 171 },
    "ASTM A36":                   { "Sd": 160, "St": 171 },
    "ASTM A131 Grade EH36":       { "Sd": 196, "St": 210 },
    "ASTM A573 Grade 400":        { "Sd": 147, "St": 165 },
    "ASTM A573 Grade 450":        { "Sd": 160, "St": 180 },
    "ASTM A573 Grade 485":        { "Sd": 193, "St": 208 },
    "ASTM A516 Grade 380":        { "Sd": 137, "St": 154 },
    "ASTM A516 Grade 415":        { "Sd": 147, "St": 165 },
    "ASTM A516 Grade 450":        { "Sd": 160, "St": 180 },
    "ASTM A516 Grade 485":        { "Sd": 173, "St": 195 },
    "ASTM A662 Grade B":          { "Sd": 180, "St": 193 },
    "ASTM A662 Grade C":          { "Sd": 194, "St": 208 },

    # A537M — thickness-dependent (two thickness ranges each)
    "ASTM A537 Class 1 (t<=65mm)":      { "Sd": 194, "St": 208 },
    "ASTM A537 Class 1 (65<t<=100mm)":  { "Sd": 180, "St": 193 },
    "ASTM A537 Class 2 (t<=65mm)":      { "Sd": 220, "St": 236 },
    "ASTM A537 Class 2 (65<t<=100mm)":  { "Sd": 206, "St": 221 },

    # A633M
    "ASTM A633 Grade C/D (t<=65mm)":     { "Sd": 194, "St": 208 },
    "ASTM A633 Grade C/D (65<t<=100mm)": { "Sd": 180, "St": 193 },

    "ASTM A737 Grade B":          { "Sd": 194, "St": 208 },

    # A841M
    "ASTM A841 Class 1 (Grade A/B)": { "Sd": 194, "St": 208 },
    "ASTM A841 Class 2 (Grade A/B)": { "Sd": 220, "St": 236 },

    # --- CSA Specifications ---
    "CSA G40.21 Grade 260W":            { "Sd": 164, "St": 176 },
    "CSA G40.21 Grade 260WT":           { "Sd": 164, "St": 176 },
    "CSA G40.21 Grade 300W":            { "Sd": 176, "St": 189 },
    "CSA G40.21 Grade 300WT":           { "Sd": 176, "St": 189 },
    "CSA G40.21 Grade 350W":            { "Sd": 180, "St": 193 },
    "CSA G40.21 Grade 350WT (t<=65mm)":      { "Sd": 180, "St": 193 },
    "CSA G40.21 Grade 350WT (65<t<=100mm)": { "Sd": 180, "St": 193 },

    # --- National Standards (generic grades, no spec name given in table) ---
    "National Standard Grade 235":  { "Sd": 137, "St": 154 },
    "National Standard Grade 250":  { "Sd": 157, "St": 171 },
    "National Standard Grade 275":  { "Sd": 167, "St": 184 },

    # --- ISO Specifications ---
    "ISO 630 S275C/D (t<=16mm)":        { "Sd": 164, "St": 176 },
    "ISO 630 S275C/D (16<t<=40mm)":     { "Sd": 164, "St": 176 },
    "ISO 630 S355C/D (t<=16mm)":        { "Sd": 188, "St": 201 },
    "ISO 630 S355C/D (16<t<=40mm)":     { "Sd": 188, "St": 201 },
    "ISO 630 S355C/D (40<t<=50mm)":     { "Sd": 188, "St": 201 },

    # --- EN Specifications ---
    "EN 10025 S275J0/J2 (t<=16mm)":      { "Sd": 164, "St": 176 },
    "EN 10025 S275J0/J2 (16<t<=40mm)":   { "Sd": 164, "St": 176 },
    "EN 10025 S355J0/J2/K2 (t<=16mm)":     { "Sd": 188, "St": 201 },
    "EN 10025 S355J0/J2/K2 (16<t<=40mm)":   { "Sd": 188, "St": 201 },
    "EN 10025 S355J0/J2/K2 (40<t<=50mm)":   { "Sd": 188, "St": 201 },
}

# Typical specific gravity by product
PRODUCTS = {
    "Water":                      1.000,
    "Sea water":                  1.025,
    "Crude oil":                  0.850,
    "Diesel":                     0.850,
    "Gasoline":                   0.740,
    "Kerosene / Jet fuel":        0.800,
    "Fuel oil (heavy)":           0.950,
    "Ethanol":                    0.790,
    "Methanol":                   0.790,
    "Sulfuric acid (98%)":        1.840,
    "Caustic soda / NaOH (50%)":  1.530,
    "LPG (liquid phase)":         0.510,
}

# ============================================================
# API 650 — CALCULATION FUNCTIONS
# ============================================================

def table_min(D):
    """Table 5.1a — minimum thickness (mm) based on diameter (m)"""
    if D < 15:
        return 5
    elif D < 36:
        return 6
    elif D <= 60:
        return 8
    else:
        return 10

def round_commercial(t, step=0.5):
    """Round up to the nearest commercial thickness, 0.5 mm step"""
    return math.ceil(t / step) * step

def one_foot_td(D, H, G, Sd, CA):
    """§5.6.3.2 — design thickness"""
    return (4.9 * D * (H - 0.3) * G) / Sd + CA

def one_foot_tt(D, H, St):
    """§5.6.3.2 — hydrostatic test thickness"""
    return (4.9 * D * (H - 0.3)) / St

def vdp_course1(D, H, G, S, CA, is_design):
    """§5.6.4.4 — bottom course, VDP method (capped by tp)"""
    if is_design:
        tp = (4.9 * D * (H - 0.3) * G) / S + CA
        factor = 1.06 - (0.0696 * D / H) * math.sqrt((H * G) / S)
        t1 = factor * (4.9 * H * D * G / S) + CA
    else:
        tp = (4.9 * D * (H - 0.3)) / S
        factor = 1.06 - (0.0696 * D / H) * math.sqrt(H / S)
        t1 = factor * (4.9 * H * D / S)
    return min(t1, tp)

def vdp_upper_course(tL, tu_init, D, H_local, r, S, G, CA, is_design, max_iter=8, tol=0.02):
    """§5.6.4.6-8 — critical point x, convergence loop"""
    tu = tu_init
    for _ in range(max_iter):
        K = tL / tu
        C = (math.sqrt(K) * (K - 1)) / (1 + K ** 1.5)
        x1 = 0.61 * math.sqrt(r * tu) + 320 * C * H_local
        x2 = 1000 * C * H_local
        x3 = 1.22 * math.sqrt(r * tu)
        x = min(x1, x2, x3)
        if is_design:
            tx = (4.9 * D * (H_local - x / 1000) * G) / S + CA
        else:
            tx = (4.9 * D * (H_local - x / 1000)) / S
        if abs(tx - tu) < tol:
            tu = tx
            break
        tu = tx
    return tu

def vdp_course2(h1, r, t1, t2a):
    """§5.6.4.5 — ratio + interpolation for the 2nd course"""
    ratio = h1 / math.sqrt(r * t1)
    if ratio <= 1.375:
        t2 = t1
    elif ratio >= 2.625:
        t2 = t2a
    else:
        t2 = t2a + (t1 - t2a) * (2.1 - h1 / (1.25 * math.sqrt(r * t1)))
    return t2

def heff_pressure(H, P, G):
    """Annex F.2.1 — fixed roof internal pressure"""
    if P >= 1:
        return H + P / (9.8 * G)
    return H

def nombre_plaques(D, L_plaque_mm=6000):
    """Number of plates per course"""
    return math.ceil((math.pi * D * 1000) / L_plaque_mm)

def h_local_liquide(H_liquide, cum_bottom_m):
    """Distance between the bottom of the course and the design liquid level."""
    return H_liquide - cum_bottom_m

# ============================================================
# API 650 — WIND GIRDER MODULE (§5.9.5 / §5.9.6)
# ============================================================

def wind_pressure(V):
    """§5.9.6.1 NOTE 2 — design wind pressure from design wind speed V (km/h)
    Pwv = 1.48*(V/190)^2 [kPa] ; Pwd = Pwv + 0.24 [kPa]"""
    Pwv = 1.48 * (V / 190) ** 2
    Pwd = Pwv + 0.24
    return Pwv, Pwd

def h1_max_unstiffened(D, t, V):
    """§5.9.6.1 — Maximum height of unstiffened shell (m)
    H1 = 9.47*t*sqrt((t/D)^3 * (1.72/Pwd))   [t in mm, D in m]"""
    _, Pwd = wind_pressure(V)
    return 9.47 * t * math.sqrt((t / D) ** 3 * (1.72 / Pwd))

def transformed_shell_height(courses, t_uniform):
    """§5.9.6.2 — Transformed shell height (m)
    Wtr = W * (t_uniform / t_actual)^2.5   (sqrt of the 5th power)
    Returns total transformed height (m) + detail per course."""
    detail = []
    H_tr = 0.0
    for c in courses:
        W = c["Height (m)"] * 1000          # mm
        t_actual = c["Thickness (mm)"]
        Wtr = W * (t_uniform / t_actual) ** 2.5
        H_tr += Wtr
        detail.append({
            "Course": c["Course"],
            "W (mm)": round(W, 1),
            "t (mm)": t_actual,
            "Wtr (mm)": round(Wtr, 1),
        })
    return H_tr / 1000, detail            # back to m

def z_top_wind_girder(D, H2, Fy, V):
    """§5.9.5.3 — Required minimum section modulus of TOP wind girder (cm3)
    Z = 6*H2*D^2 * (Pwd/1.72) / (0.5*Fy)
    D capped at 61 m ; Fy capped at 210 MPa."""
    D_calc = min(D, 61)
    Fy_calc = min(Fy, 210)
    _, Pwd = wind_pressure(V)
    return 6 * H2 * D_calc ** 2 * (Pwd / 1.72) / (0.5 * Fy_calc)

def z_intermediate_wind_girder(D, h1, Fy, V):
    """§5.9.6.6 — Required minimum section modulus of INTERMEDIATE wind girder (cm3)
    Z = 6*h1*D^2 * (Pwd/1.72) / (0.5*Fy)
    Fy capped at 210 MPa. h1 = distance (m) between girder and top of shell."""
    Fy_calc = min(Fy, 210)
    _, Pwd = wind_pressure(V)
    return 6 * h1 * D ** 2 * (Pwd / 1.72) / (0.5 * Fy_calc)

def check_wind_girder(D, H_shell, courses, V, Fy=235):
    """Full §5.9.6 check: is an intermediate wind girder required, and if so
    how many, plus the required section moduli (top + intermediate)."""
    t_uniform = min(c["Thickness (mm)"] for c in courses)   # thinnest course
    H1 = h1_max_unstiffened(D, t_uniform, V)
    H_transformed, detail = transformed_shell_height(courses, t_uniform)

    if H_transformed <= H1:
        n_girders_required = 0
    elif H_transformed / 2 <= H1:
        n_girders_required = 1          # §5.9.6.3
    else:
        n_girders_required = 2          # §5.9.6.4 (half of transformed > H1)

    Z_top = z_top_wind_girder(D, H_shell, Fy, V)
    # h1 for intermediate girder: worst case, mid-height of transformed shell (§5.9.6.3.1)
    h1_mid = H_transformed / 2 if n_girders_required else None
    Z_intermediate = z_intermediate_wind_girder(D, h1_mid, Fy, V) if h1_mid else None

    return {
        "t_uniform_mm": t_uniform,
        "H1_m": round(H1, 3),
        "H_transformed_m": round(H_transformed, 3),
        "detail_per_course": detail,
        "n_intermediate_girders_required": n_girders_required,
        "Z_top_cm3": round(Z_top, 1),
        "Z_intermediate_cm3": round(Z_intermediate, 1) if Z_intermediate else None,
    }

# ============================================================
# MAIN CALCULATION
# ============================================================

def calculer_reservoir(D, H_shell, H_liquide, h_course_mm, G, CA, Sd, St,
                       method="AUTO", P=0, V=0, L_plaque_mm=6000, Fy=235):
    r = (D * 1000) / 2

    freeboard_msg = ""
    if H_liquide > H_shell:
        freeboard_msg = "WARNING: Liquid level > shell height — capped to shell height."
        H_liquide = H_shell
    elif H_liquide < H_shell:
        freeboard = H_shell - H_liquide
        freeboard_msg = f"Freeboard (safety margin) = {freeboard:.2f} m"

    if method == "AUTO":
        method_used = "ONEFOOT" if D <= 61 else "VDP"
    else:
        method_used = method

    validity_msg = ""
    if method_used == "VDP":
        t_estim = table_min(D)
        L = math.sqrt(500 * D * t_estim)
        ratio_LH = L / H_liquide
        validity_msg = (f"VDP applicable (L/H={ratio_LH:.3f})"
                       if ratio_LH <= 1000 / 6
                       else f"WARNING: outside VDP domain (L/H={ratio_LH:.3f})")
    elif method_used == "ONEFOOT" and D > 61:
        return {
            "D": D, "H_shell": H_shell, "H_liquide": H_liquide,
            "method_used": method_used,
            "valid": False,
            "validity_msg": "ERROR: One-Foot Method is not allowed for D > 61 m (§5.6.3.1 API 650).",
            "freeboard_msg": freeboard_msg,
            "courses": [],
            "wind": None,
            "poids_total_kg": 0,
        }

    n_full = int((H_shell * 1000) // h_course_mm)
    remainder = (H_shell * 1000) - n_full * h_course_mm
    heights = [h_course_mm] * n_full
    if remainder > 1:
        heights.append(remainder)
    n = len(heights)

    cum_bottom = []
    cum = 0.0
    for h in heights:
        cum_bottom.append(cum / 1000)
        cum += h

    courses = []
    t_use_prev = None

    for i in range(n):
        h_local = h_local_liquide(H_liquide, cum_bottom[i])

        if h_local <= 0.30:
            td = 0.0
            tt = 0.0
        else:
            h_eff_d = heff_pressure(h_local, P, G)
            h_eff_t = heff_pressure(h_local, P, 1)

            if method_used == "ONEFOOT":
                td = one_foot_td(D, h_eff_d, G, Sd, CA)
                tt = one_foot_tt(D, h_eff_t, St)
            else:
                if i == 0:
                    td = vdp_course1(D, h_eff_d, G, Sd, CA, True)
                    tt = vdp_course1(D, h_eff_t, 1, St, 0, False)
                elif i == 1:
                    tu_init_d = one_foot_td(D, h_eff_d, G, Sd, CA)
                    t2a_d = vdp_upper_course(t_use_prev, tu_init_d, D, h_eff_d, r, Sd, G, CA, True)
                    td = vdp_course2(heights[0], r, t_use_prev, t2a_d)

                    tu_init_t = one_foot_tt(D, h_eff_t, St)
                    t2a_t = vdp_upper_course(t_use_prev, tu_init_t, D, h_eff_t, r, St, 1, 0, False)
                    tt = vdp_course2(heights[0], r, t_use_prev, t2a_t)
                else:
                    tu_init_d = one_foot_td(D, h_eff_d, G, Sd, CA)
                    td = vdp_upper_course(t_use_prev, tu_init_d, D, h_eff_d, r, Sd, G, CA, True)

                    tu_init_t = one_foot_tt(D, h_eff_t, St)
                    tt = vdp_upper_course(t_use_prev, tu_init_t, D, h_eff_t, r, St, 1, 0, False)

        tmin = table_min(D)
        governing = max(td, tt, tmin)
        t_use = round_commercial(governing)
        t_use_prev = t_use

        courses.append({
            "Course": i + 1,
            "Height (m)": round(heights[i] / 1000, 3),
            "Local liquid head (m)": round(max(h_local, 0), 2),
            "td (mm)": round(td, 2),
            "tt (mm)": round(tt, 2),
            "t min (mm)": tmin,
            "Governing t (mm)": round(governing, 2),
            "Thickness (mm)": t_use,
            "Nb Plates": nombre_plaques(D, L_plaque_mm),
        })

    # --- Wind girder check (§5.9.5 / §5.9.6) ---
    wind_result = None
    if V > 0:
        wind_result = check_wind_girder(D, H_shell, courses, V, Fy=Fy)

    density = 7850
    poids_total = sum(
        math.pi * D * c["Height (m)"] * (c["Thickness (mm)"] / 1000) * density
        for c in courses
    )

    return {
        "D": D, "H_shell": H_shell, "H_liquide": H_liquide,
        "method_used": method_used,
        "valid": True,
        "validity_msg": validity_msg,
        "freeboard_msg": freeboard_msg,
        "courses": courses,
        "wind": wind_result,
        "poids_total_kg": round(poids_total, 0),
    }

# ============================================================
# VISUAL DIAGRAM
# ============================================================
def dessiner_schema_reservoir(resultat):
    courses = resultat["courses"]
    D = resultat["D"]
    H_liquide = resultat["H_liquide"]
    H_shell = resultat["H_shell"]

    epaisseurs = [c["Thickness (mm)"] for c in courses]
    tmin_c, tmax_c = min(epaisseurs), max(epaisseurs)
    norm = mcolors.Normalize(vmin=tmin_c, vmax=max(tmax_c, tmin_c + 0.1))
    cmap = plt.get_cmap("Blues")

    largeur_dessin = 4.0

    fig, ax = plt.subplots(figsize=(4.5, 7))

    y_bas = 0.0
    for c in courses:
        h = c["Height (m)"]
        t = c["Thickness (mm)"]
        couleur = cmap(norm(t))

        rect = patches.Rectangle((0, y_bas), largeur_dessin, h,
                                 facecolor=couleur, edgecolor="#333333", linewidth=1.1)
        ax.add_patch(rect)

        luminosite = 0.299 * couleur[0] + 0.587 * couleur[1] + 0.114 * couleur[2]
        couleur_texte = "white" if luminosite < 0.55 else "black"
        ax.text(largeur_dessin / 2, y_bas + h / 2,
                f"C{c['Course']} — {t:.1f} mm",
                ha="center", va="center", fontsize=9, color=couleur_texte, weight="bold")

        y_bas += h

    ax.axhline(H_liquide, color="#1f77b4", linestyle="--", linewidth=1.8)
    ax.text(largeur_dessin + 0.15, H_liquide, f"Liquid level\nH = {H_liquide:.2f} m",
            va="center", fontsize=8.5, color="#1f77b4")

    if H_shell > H_liquide:
        ax.text(largeur_dessin + 0.15, H_shell, f"Shell top\nH = {H_shell:.2f} m",
                va="center", fontsize=8.5, color="#555555")

    ax.set_xlim(-0.3, largeur_dessin + 2.3)
    ax.set_ylim(0, max(H_shell, y_bas) * 1.05)
    ax.set_xticks([])
    ax.set_ylabel("Height (m)")
    ax.set_title(f"Shell cross-section — D = {D:.1f} m", fontsize=11, weight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout()
    return fig

# ============================================================
# EXPORT — PDF and Excel calculation report
# ============================================================

def generer_rapport_pdf(res, material, product, titre_personnalise="API 650 — Shell Design Calculation Report"):
    """Builds a PDF calculation report (reportlab) and returns it as bytes.
    Includes the wind girder section with Z_top / Z_intermediate (§5.9.5/§5.9.6)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                             topMargin=1.5 * rl_cm, bottomMargin=1.5 * rl_cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(titre_personnalise, styles["Title"]))
    story.append(Spacer(1, 12))

    # --- Input summary ---
    story.append(Paragraph("1. Input Parameters", styles["Heading2"]))
    infos = [
        ["Diameter (m)", f"{res['D']:.2f}"],
        ["Total shell height (m)", f"{res['H_shell']:.2f}"],
        ["Design liquid level (m)", f"{res['H_liquide']:.2f}"],
        ["Product", product],
        ["Material", material],
        ["Method used", res["method_used"]],
    ]
    t_info = Table(infos, colWidths=[7 * rl_cm, 7 * rl_cm])
    t_info.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 16))

    # --- Results table ---
    story.append(Paragraph("2. Results by Course", styles["Heading2"]))
    headers = ["Course", "Height (m)", "Local head (m)", "td (mm)",
               "tt (mm)", "t min (mm)", "Governing t (mm)", "Thickness (mm)", "Nb Plates"]
    data = [headers]
    for c in res["courses"]:
        data.append([
            c["Course"], c["Height (m)"], c["Local liquid head (m)"],
            c["td (mm)"], c["tt (mm)"], c["t min (mm)"],
            c["Governing t (mm)"], c["Thickness (mm)"], c["Nb Plates"],
        ])
    t_results = Table(data, repeatRows=1)
    t_results.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8a6d1a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_results)
    story.append(Spacer(1, 16))

    # --- Fabrication summary ---
    story.append(Paragraph("3. Fabrication Summary", styles["Heading2"]))
    story.append(Paragraph(f"Total shell weight: <b>{res['poids_total_kg']:.0f} kg</b>", styles["Normal"]))

    # --- Wind girder section (§5.9.5 / §5.9.6) ---
    if res["wind"]:
        w = res["wind"]
        story.append(Spacer(1, 16))
        story.append(Paragraph("4. Wind Girder Check (§5.9.5 / §5.9.6)", styles["Heading2"]))

        wind_infos = [
            ["Thinnest course thickness t_uniform (mm)", f"{w['t_uniform_mm']}"],
            ["H1 — max unstiffened height (m)", f"{w['H1_m']}"],
            ["Transformed shell height (m)", f"{w['H_transformed_m']}"],
            ["Intermediate girders required", f"{w['n_intermediate_girders_required']}"],
            ["Z top wind girder required (cm³)", f"{w['Z_top_cm3']}"],
            ["Z intermediate wind girder required (cm³)",
             f"{w['Z_intermediate_cm3']}" if w["Z_intermediate_cm3"] else "N/A"],
        ]
        t_wind = Table(wind_infos, colWidths=[9 * rl_cm, 5 * rl_cm])
        t_wind.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t_wind)

        verdict = ("No intermediate wind girder required."
                   if w["n_intermediate_girders_required"] == 0
                   else f"{w['n_intermediate_girders_required']} intermediate wind girder(s) required.")
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>Verdict:</b> {verdict} A top wind girder "
                                f"(Z ≥ {w['Z_top_cm3']} cm³) is mandatory regardless.", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generer_rapport_excel(res, material, product):
    """Builds an Excel calculation report (pandas + openpyxl) and returns it as bytes."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # Sheet 1 — inputs
        infos_df = pd.DataFrame({
            "Parameter": ["Diameter (m)", "Total shell height (m)", "Design liquid level (m)",
                          "Product", "Material", "Method used"],
            "Value": [res["D"], res["H_shell"], res["H_liquide"],
                      product, material, res["method_used"]],
        })
        infos_df.to_excel(writer, sheet_name="Inputs", index=False)

        # Sheet 2 — course-by-course results
        df = pd.DataFrame(res["courses"])
        df.to_excel(writer, sheet_name="Results by course", index=False)

        # Sheet 3 — summary + wind girder
        summary_df = pd.DataFrame({
            "Metric": ["Total shell weight (kg)"],
            "Value": [res["poids_total_kg"]],
        })
        if res["wind"]:
            w = res["wind"]
            summary_df = pd.concat([summary_df, pd.DataFrame({
                "Metric": ["Wind H1 (m)", "Wind Transformed H (m)",
                           "Intermediate girders required",
                           "Z top wind girder (cm3)", "Z intermediate wind girder (cm3)"],
                "Value": [w["H1_m"], w["H_transformed_m"],
                          w["n_intermediate_girders_required"],
                          w["Z_top_cm3"], w["Z_intermediate_cm3"] or "N/A"],
            })], ignore_index=True)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    buffer.seek(0)
    return buffer

# ============================================================
# STREAMLIT INTERFACE
# ============================================================
st.set_page_config(page_title="API 650 Calculator", page_icon="🏗️", layout="wide")

st.title("🏗️ API 650 Calculator")
st.caption("Your tool for calculation and design of a storage reservoir")

st.sidebar.header("Parameters")

D = st.sidebar.number_input("Diameter (m)", value=0.0, step=0.5)

st.sidebar.markdown("**Heights (distinct)**")
H_shell = st.sidebar.number_input(
    "Total shell height (m)", value=0.0, step=0.5,
    help="Actual physical height of the plating, determines the number of courses."
)
H_liquide = st.sidebar.number_input(
    "Design liquid level (m)", value=0.0, step=0.5,
    help="Maximum fill level, used in ALL stress formulas."
)

st.sidebar.markdown("**Stored product**")
product = st.sidebar.selectbox("Product type", ["— Select —"] + list(PRODUCTS.keys()) + ["Custom / Other"])

if product == "— Select —":
    G = 0.0
elif product == "Custom / Other":
    G = st.sidebar.number_input("Specific gravity G", value=0.0, step=0.05)
else:
    G = PRODUCTS[product]
    st.sidebar.caption(f"Specific gravity G = **{G}**")

st.sidebar.markdown("**Shell material**")
material = st.sidebar.selectbox("ASTM grade (API 650 Table 5.2a)", ["— Select —"] + list(MATERIALS.keys()) + ["Custom / Other"])

if material == "— Select —":
    Sd, St = 0.0, 0.0
elif material == "Custom / Other":
    Sd = st.sidebar.number_input("Design stress (Sd) — MPa", value=0.0, step=1.0)
    St = st.sidebar.number_input("Test stress (St) — MPa", value=0.0, step=1.0)
else:
    Sd = MATERIALS[material]["Sd"]
    St = MATERIALS[material]["St"]
    st.sidebar.caption(f"Sd = **{Sd} MPa**, St = **{St} MPa**")

CA = st.sidebar.number_input("Corrosion allowance (mm)", value=0.0, step=0.1)
h_course_mm = st.sidebar.number_input("Course height (mm)", value=0, step=100)
method = st.sidebar.selectbox("Method", ["AUTO", "ONEFOOT", "VDP"])

st.sidebar.markdown("---")
st.sidebar.subheader("Bonus options")

use_pressure = st.sidebar.checkbox("Fixed roof — internal pressure")
P = st.sidebar.number_input("Pressure P (kPa)", value=0.0, step=0.5) if use_pressure else 0

use_wind = st.sidebar.checkbox("Check wind girder", value=False)
if use_wind:
    V = st.sidebar.number_input("Wind speed (km/h)", value=0.0, step=5.0)
    Fy = st.sidebar.number_input(
        "Yield strength Fy (MPa)", value=235.0, step=5.0,
        help="Capped at 210 MPa in the §5.9.5.3 / §5.9.6.6 formulas regardless of the value entered."
    )
else:
    V = 0
    Fy = 235.0

L_plaque_mm = st.sidebar.number_input("Standard plate length (mm)", value=0, step=100)

st.sidebar.markdown("---")
run_clicked = st.sidebar.button("Run calculation", type="primary", use_container_width=True)

if run_clicked:
    if D == 0 or H_shell == 0 or H_liquide == 0 or G == 0 or Sd == 0 or St == 0 or h_course_mm == 0 or L_plaque_mm == 0:
        st.error("Please fill in all required values before running the calculation.")
        st.stop()
    resultat = calculer_reservoir(
        D=D, H_shell=H_shell, H_liquide=H_liquide, h_course_mm=h_course_mm,
        G=G, CA=CA, Sd=Sd, St=St,
        method=method, P=P, V=V, L_plaque_mm=L_plaque_mm, Fy=Fy
    )
    st.session_state["resultat"] = resultat

if "resultat" not in st.session_state:
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #8a6d1a 0%, #b8912b 100%);
            padding: 42px 40px;
            border-radius: 12px;
            color: white;
            margin-bottom: 28px;
        ">
            <h2 style="margin:0 0 8px 0; color:white;">Tank shell design, done right.</h2>
            <p style="margin:0; font-size: 16px; opacity: 0.92; max-width: 640px;">
                Enter your tank geometry, product and material in the sidebar to get a
                full API 650 shell thickness schedule.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("👈 Fill in the parameters in the sidebar, then click **Run calculation**.")
else:
    res = st.session_state["resultat"]

    if not res["valid"]:
        st.error(res["validity_msg"])
        st.stop()

    if res["freeboard_msg"]:
        st.caption(f"ℹ️ {res['freeboard_msg']}")

    col_table, col_schema = st.columns([2, 1])

    with col_table:
        st.subheader("Results by course")
        df = pd.DataFrame(res["courses"])
        st.dataframe(df, use_container_width=True)

        st.info(f"Method used: **{res['method_used']}**")
        if res["validity_msg"]:
            st.warning(res["validity_msg"])

    with col_schema:
        st.subheader("Shell diagram")
        fig = dessiner_schema_reservoir(res)
        st.pyplot(fig)

    if res["wind"]:
        w = res["wind"]
        st.subheader("Bonus — Wind girder (§5.9.5 / §5.9.6)")

        c1, c2, c3 = st.columns(3)
        c1.metric("H1 — max unstiffened height (m)", w["H1_m"])
        c2.metric("Transformed shell height (m)", w["H_transformed_m"])
        c3.metric(
            "Intermediate girders required",
            w["n_intermediate_girders_required"],
        )
        if w["H_transformed_m"] <= w["H1_m"]:
            st.success("✅ No intermediate wind girder required (transformed height ≤ H1).")
        else:
            st.warning(f"⚠️ Intermediate wind girder(s) required: {w['n_intermediate_girders_required']}")

        c4, c5 = st.columns(2)
        c4.metric("Z top wind girder required (cm³)", w["Z_top_cm3"])
        if w["Z_intermediate_cm3"]:
            c5.metric("Z intermediate wind girder required (cm³)", w["Z_intermediate_cm3"])

        with st.expander("Transposed width detail per course (§5.9.6.2)"):
            st.dataframe(pd.DataFrame(w["detail_per_course"]), use_container_width=True)

    st.subheader("Bonus — Fabrication")
    st.metric("Total shell weight (kg)", f"{res['poids_total_kg']:.0f}")

    st.subheader("Bonus — Export")
    col_pdf, col_excel = st.columns(2)

    with col_pdf:
        pdf_buffer = generer_rapport_pdf(res, material, product)
        st.download_button(
            label="📄 Download PDF report",
            data=pdf_buffer,
            file_name="api650_calculation_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with col_excel:
        excel_buffer = generer_rapport_excel(res, material, product)
        st.download_button(
            label="📊 Download Excel report",
            data=excel_buffer,
            file_name="api650_calculation_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.success("Calculation completed successfully!")
