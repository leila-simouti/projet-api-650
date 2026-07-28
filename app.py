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
from reportlab.lib.units import cm

# ============================================================
# API 650 — REFERENCE TABLES
# ============================================================

MATERIALS = {
  "ASTM A283 Grade C":         { "Sd": 137, "St": 154 },
  "ASTM A285 Grade C":         { "Sd": 137, "St": 154 },
  "ASTM A131 Grade A/B":       { "Sd": 157, "St": 171 },
  "ASTM A36":                  { "Sd": 160, "St": 171 },
  "ASTM A131 Grade EH36":      { "Sd": 196, "St": 210 },
  "ASTM A573 Grade 400":       { "Sd": 147, "St": 165 },
  "ASTM A573 Grade 450":       { "Sd": 160, "St": 180 },
  "ASTM A573 Grade 485":       { "Sd": 193, "St": 208 },
  "ASTM A516 Grade 380":       { "Sd": 137, "St": 154 },
  "ASTM A516 Grade 415":       { "Sd": 147, "St": 165 },
  "ASTM A516 Grade 450":       { "Sd": 160, "St": 180 },
  "ASTM A516 Grade 485":       { "Sd": 173, "St": 195 },
  "ASTM A662 Grade B":         { "Sd": 180, "St": 193 },
  "ASTM A662 Grade C":         { "Sd": 194, "St": 208 },
  "ASTM A537 Class 1 (t<=65mm)":     { "Sd": 194, "St": 208 },
  "ASTM A537 Class 1 (65<t<=100mm)":  { "Sd": 180, "St": 193 },
  "ASTM A537 Class 2 (t<=65mm)":     { "Sd": 220, "St": 236 },
  "ASTM A537 Class 2 (65<t<=100mm)":  { "Sd": 206, "St": 221 },
  "ASTM A633 Grade C/D (t<=65mm)":     { "Sd": 194, "St": 208 },
  "ASTM A633 Grade C/D (65<t<=100mm)": { "Sd": 180, "St": 193 },
  "ASTM A737 Grade B":         { "Sd": 194, "St": 208 },
  "ASTM A841 Class 1 (Grade A/B)": { "Sd": 194, "St": 208 },
  "ASTM A841 Class 2 (Grade A/B)": { "Sd": 220, "St": 236 },
  "CSA G40.21 Grade 260W":             { "Sd": 164, "St": 176 },
  "CSA G40.21 Grade 260WT":            { "Sd": 164, "St": 176 },
  "CSA G40.21 Grade 300W":             { "Sd": 176, "St": 189 },
  "CSA G40.21 Grade 300WT":            { "Sd": 176, "St": 189 },
  "CSA G40.21 Grade 350W":             { "Sd": 180, "St": 193 },
  "CSA G40.21 Grade 350WT (t<=65mm)":     { "Sd": 180, "St": 193 },
  "CSA G40.21 Grade 350WT (65<t<=100mm)": { "Sd": 180, "St": 193 },
  "National Standard Grade 235":  { "Sd": 137, "St": 154 },
  "National Standard Grade 250":  { "Sd": 157, "St": 171 },
  "National Standard Grade 275":  { "Sd": 167, "St": 184 },
  "ISO 630 S275C/D (t<=16mm)":        { "Sd": 164, "St": 176 },
  "ISO 630 S275C/D (16<t<=40mm)":     { "Sd": 164, "St": 176 },
  "ISO 630 S355C/D (t<=16mm)":        { "Sd": 188, "St": 201 },
  "ISO 630 S355C/D (16<t<=40mm)":     { "Sd": 188, "St": 201 },
  "ISO 630 S355C/D (40<t<=50mm)":     { "Sd": 188, "St": 201 },
  "EN 10025 S275J0/J2 (t<=16mm)":      { "Sd": 164, "St": 176 },
  "EN 10025 S275J0/J2 (16<t<=40mm)":   { "Sd": 164, "St": 176 },
  "EN 10025 S355J0/J2/K2 (t<=16mm)":      { "Sd": 188, "St": 201 },
  "EN 10025 S355J0/J2/K2 (16<t<=40mm)":   { "Sd": 188, "St": 201 },
  "EN 10025 S355J0/J2/K2 (40<t<=50mm)":   { "Sd": 188, "St": 201 },
}

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
    "Caustic soda / NaOH (50%)":1.530,
    "LPG (liquid phase)":         0.510,
}

# ============================================================
# API 650 — CALCULATION FUNCTIONS
# ============================================================

def table_min(D):
    if D < 15: return 5
    elif D < 36: return 6
    elif D <= 60: return 8
    else: return 10

def round_commercial(t, step=0.5):
    return math.ceil(t / step) * step

def one_foot_td(D, H, G, Sd, CA):
    return (4.9 * D * (H - 0.3) * G) / Sd + CA

def one_foot_tt(D, H, St):
    return (4.9 * D * (H - 0.3)) / St

def vdp_course1(D, H, G, S, CA, is_design):
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
    ratio = h1 / math.sqrt(r * t1)
    if ratio <= 1.375: return t1
    elif ratio >= 2.625: return t2a
    else: return t2a + (t1 - t2a) * (2.1 - h1 / (1.25 * math.sqrt(r * t1)))

def heff_pressure(H, P, G):
    if P >= 1: return H + P / (9.8 * G)
    return H

def wind_girder_h1(D, t, V):
    Pwv = 1.48 * (V / 190) ** 2
    Pwd = Pwv + 0.24
    return 9.47 * t * math.sqrt((t / D) ** 3 * (1.72 / Pwd))

def nombre_plaques(D, L_plaque_mm=6000):
    return math.ceil((math.pi * D * 1000) / L_plaque_mm)

def h_local_liquide(H_liquide, cum_bottom_m):
    return H_liquide - cum_bottom_m

def calculer_reservoir(D, H_shell, H_liquide, h_course_mm, G, CA, Sd, St,
                         method="AUTO", P=0, V=0, L_plaque_mm=6000):
    r = (D * 1000) / 2
    freeboard_msg = ""
    if H_liquide > H_shell:
        freeboard_msg = "WARNING: Liquid level > shell height — capped to shell height."
        H_liquide = H_shell
    elif H_liquide < H_shell:
        freeboard = H_shell - H_liquide
        freeboard_msg = f"Freeboard (safety margin) = {freeboard:.2f} m"

    method_used = "ONEFOOT" if (method == "AUTO" and D <= 61) else ("VDP" if method == "AUTO" else method)

    if method_used == "ONEFOOT" and D > 61:
        return {
            "valid": False,
            "validity_msg": "ERROR: One-Foot Method is not allowed for D > 61 m (§5.6.3.1 API 650).",
            "courses": [], "wind": None, "poids_total_kg": 0,
        }

    validity_msg = ""
    if method_used == "VDP":
        t_estim = table_min(D)
        L = math.sqrt(500 * D * t_estim)
        ratio_LH = L / H_liquide
        validity_msg = f"VDP applicable (L/H={ratio_LH:.3f})" if ratio_LH <= 1000 / 6 else f"WARNING: outside VDP domain (L/H={ratio_LH:.3f})"

    n_full = int((H_shell * 1000) // h_course_mm)
    remainder = (H_shell * 1000) - n_full * h_course_mm
    heights = [h_course_mm] * n_full
    if remainder > 1: heights.append(remainder)
    n = len(heights)

    cum_bottom, cum = [], 0.0
    for h in heights:
        cum_bottom.append(cum / 1000)
        cum += h

    courses, t_use_prev = [], None
    for i in range(n):
        h_local = h_local_liquide(H_liquide, cum_bottom[i])
        if h_local <= 0.30:
            td, tt = 0.0, 0.0
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
            "Course": i + 1, "Height (m)": round(heights[i] / 1000, 3),
            "Local liquid head (m)": round(max(h_local, 0), 2),
            "td (mm)": round(td, 2), "tt (mm)": round(tt, 2),
            "t min (mm)": tmin, "Governing t (mm)": round(governing, 2),
            "Thickness (mm)": t_use, "Nb Plates": nombre_plaques(D, L_plaque_mm),
        })

    wind_result = None
    if V > 0:
        t_ref = min(c["Thickness (mm)"] for c in courses)
        H1 = wind_girder_h1(D, t_ref, V)
        H_transf = sum(c["Height (m)"] * 1000 * (t_ref / c["Thickness (mm)"]) ** 2.5 for c in courses) / 1000
        wind_result = {"H1": round(H1, 2), "H_transformed": round(H_transf, 2), "ok": H_transf <= H1}

    poids_total = sum(math.pi * D * c["Height (m)"] * (c["Thickness (mm)"] / 1000) * 7850 for c in courses)

    return {
        "D": D, "H_shell": H_shell, "H_liquide": H_liquide,
        "method_used": method_used, "valid": True,
        "validity_msg": validity_msg, "freeboard_msg": freeboard_msg,
        "courses": courses, "wind": wind_result, "poids_total_kg": round(poids_total, 0),
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
    norm = mcolors.Normalize(vmin=min(epaisseurs), vmax=max(max(epaisseurs), min(epaisseurs) + 0.1))
    cmap = plt.get_cmap("Blues")
    largeur_dessin = 4.0

    fig, ax = plt.subplots(figsize=(4.5, 7))
    y_bas = 0.0
    for c in courses:
        h, t = c["Height (m)"], c["Thickness (mm)"]
        couleur = cmap(norm(t))
        ax.add_patch(patches.Rectangle((0, y_bas), largeur_dessin, h, facecolor=couleur, edgecolor="#333333", linewidth=1.1))
        lum = 0.299 * couleur[0] + 0.587 * couleur[1] + 0.114 * couleur[2]
        ax.text(largeur_dessin / 2, y_bas + h / 2, f"C{c['Course']} — {t:.1f} mm",
                ha="center", va="center", fontsize=9, color="white" if lum < 0.55 else "black", weight="bold")
        y_bas += h

    ax.axhline(H_liquide, color="#1f77b4", linestyle="--", linewidth=1.8)
    ax.text(largeur_dessin + 0.15, H_liquide, f"Liquid level\nH = {H_liquide:.2f} m", va="center", fontsize=8.5, color="#1f77b4")
    if H_shell > H_liquide:
        ax.text(largeur_dessin + 0.15, H_shell, f"Shell top\nH = {H_shell:.2f} m", va="center", fontsize=8.5, color="#555555")

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
# EXPORT PDF
# ============================================================
def generer_rapport_pdf(res, material, product, titre_personnalise):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(titre_personnalise, styles["Title"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("API 650 — Shell Design Calculation Report", styles["Heading3"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("1. Input Parameters", styles["Heading2"]))
    infos = [
        ["Report title", titre_personnalise],
        ["Diameter (m)", f"{res['D']:.2f}"],
        ["Total shell height (m)", f"{res['H_shell']:.2f}"],
        ["Design liquid level (m)", f"{res['H_liquide']:.2f}"],
        ["Product", product],
        ["Material", material],
        ["Method used", res["method_used"]],
    ]
    t_info = Table(infos, colWidths=[7 * cm, 7 * cm])
    t_info.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 16))

    story.append(Paragraph("2. Results by Course", styles["Heading2"]))
    headers = ["Course", "Height (m)", "Local head (m)", "td (mm)", "tt (mm)", "t min (mm)", "Governing t (mm)", "Thickness (mm)", "Nb Plates"]
    data = [headers]
    for c in res["courses"]:
        data.append([c["Course"], c["Height (m)"], c["Local liquid head (m)"], c["td (mm)"], c["tt (mm)"], c["t min (mm)"], c["Governing t (mm)"], c["Thickness (mm)"], c["Nb Plates"]])
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

    story.append(Paragraph("3. Fabrication Summary", styles["Heading2"]))
    story.append(Paragraph(f"Total shell weight: <b>{res['poids_total_kg']:.0f} kg</b>", styles["Normal"]))

    if res["wind"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("4. Wind Girder Check", styles["Heading2"]))
        story.append(Paragraph(f"H1 = {res['wind']['H1']} m, Transformed H = {res['wind']['H_transformed']} m, Status: {'OK' if res['wind']['ok'] else 'Girder Required'}", styles["Normal"]))

    doc.build(story)
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
H_shell = st.sidebar.number_input("Total shell height (m)", value=0.0, step=0.5)
H_liquide = st.sidebar.number_input("Design liquid level (m)", value=0.0, step=0.5)

st.sidebar.markdown("**Stored product**")
product = st.sidebar.selectbox("Product type", ["— Select —"] + list(PRODUCTS.keys()) + ["Custom / Other"])
G = 0.0 if product == "— Select —" else (st.sidebar.number_input("Specific gravity G", value=0.0, step=0.05) if product == "Custom / Other" else PRODUCTS[product])

st.sidebar.markdown("**Shell material**")
material = st.sidebar.selectbox("ASTM grade (API 650 Table 5.2a)", ["— Select —"] + list(MATERIALS.keys()) + ["Custom / Other"])
if material == "— Select —":
    Sd, St = 0.0, 0.0
elif material == "Custom / Other":
    Sd = st.sidebar.number_input("Design stress (Sd) — MPa", value=0.0, step=1.0)
    St = st.sidebar.number_input("Test stress (St) — MPa", value=0.0, step=1.0)
else:
    Sd, St = MATERIALS[material]["Sd"], MATERIALS[material]["St"]

CA = st.sidebar.number_input("Corrosion allowance (mm)", value=0.0, step=0.1)
h_course_mm = st.sidebar.number_input("Course height (mm)", value=0, step=100)
method = st.sidebar.selectbox("Method", ["AUTO", "ONEFOOT", "VDP"])

st.sidebar.markdown("---")
st.sidebar.subheader("Bonus options")
use_pressure = st.sidebar.checkbox("Fixed roof — internal pressure")
P = st.sidebar.number_input("Pressure P (kPa)", value=0.0, step=0.5) if use_pressure else 0
use_wind = st.sidebar.checkbox("Check wind girder", value=False)
V = st.sidebar.number_input("Wind speed (km/h)", value=0.0, step=5.0) if use_wind else 0
L_plaque_mm = st.sidebar.number_input("Standard plate length (mm)", value=0, step=100)

st.sidebar.markdown("---")
run_clicked = st.sidebar.button("Run calculation", type="primary", use_container_width=True)

if run_clicked:
    if D == 0 or H_shell == 0 or H_liquide == 0 or G == 0 or Sd == 0 or St == 0 or h_course_mm == 0 or L_plaque_mm == 0:
        st.error("Please fill in all required values before running the calculation.")
        st.stop()
    st.session_state["resultat"] = calculer_reservoir(
        D=D, H_shell=H_shell, H_liquide=H_liquide, h_course_mm=h_course_mm,
        G=G, CA=CA, Sd=Sd, St=St, method=method, P=P, V=V, L_plaque_mm=L_plaque_mm
    )

if "resultat" not in st.session_state:
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #8a6d1a 0%, #b8912b 100%); padding: 42px 40px; border-radius: 12px; color: white; margin-bottom: 28px;">
            <h2 style="margin:0 0 8px 0; color:white;">Tank shell design, done right.</h2>
            <p style="margin:0; font-size: 16px; opacity: 0.92; max-width: 640px;">
                Enter your tank geometry, product and material in the sidebar to get a full API 650 shell thickness schedule.
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
        st.dataframe(pd.DataFrame(res["courses"]), use_container_width=True)
        st.info(f"Method used: **{res['method_used']}**")
        if res["validity_msg"]:
            st.warning(res["validity_msg"])

    with col_schema:
        st.subheader("Shell diagram")
        st.pyplot(dessiner_schema_reservoir(res))

    if res["wind"]:
        st.subheader("Bonus — Wind girder")
        c1, c2, c3 = st.columns(3)
        c1.metric("H1 (m)", res["wind"]["H1"])
        c2.metric("Transformed H (m)", res["wind"]["H_transformed"])
        c3.metric("Status", "✅ OK" if res["wind"]["ok"] else "⚠️ Required")

    st.subheader("Bonus — Fabrication")
    st.metric("Total shell weight (kg)", f"{res['poids_total_kg']:.0f}")

    # --- EXPORT SECTION AVEC NOM DU RAPPORT ---
    st.subheader("Bonus — Export")
    
    # Champ de saisie pour personnaliser le nom/titre du rapport
    nom_rapport = st.text_input("Name your calculation report / project title", value="API 650 Calculation Report")
    
    # Nettoyage du nom pour en faire un nom de fichier valide sans caractères spéciaux risqués
    nom_fichier_securise = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in nom_rapport).strip().replace(" ", "_")
    if not nom_fichier_securise:
        nom_fichier_securise = "api650_report"

    pdf_buffer = generer_rapport_pdf(res, material, product, nom_rapport)
    
    st.download_button(
        label="📄 Download PDF report",
        data=pdf_buffer,
        file_name=f"{nom_fichier_securise}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    st.success("Calculation completed successfully!")
