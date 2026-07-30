import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import math

# ============================================================
# API 650 — REFERENCE TABLES
# ============================================================

# Table 5.2a (SI units) — Permissible plate materials and allowable stresses (MPa)
MATERIALS = {
    "ASTM A283 Grade C":     {"Sd": 137, "St": 154},
    "ASTM A285 Grade C":     {"Sd": 137, "St": 154},
    "ASTM A131 Grade A/B":   {"Sd": 157, "St": 171},
    "ASTM A36":               {"Sd": 160, "St": 171},
    "ASTM A573 Grade 400":   {"Sd": 147, "St": 165},
    "ASTM A573 Grade 450":   {"Sd": 160, "St": 180},
    "ASTM A516 Grade 380":   {"Sd": 137, "St": 154},
    "ASTM A516 Grade 415":   {"Sd": 147, "St": 165},
    "ASTM A516 Grade 450":   {"Sd": 160, "St": 180},
    "ASTM A516 Grade 485":   {"Sd": 173, "St": 195},
    "ASTM A662 Grade B":     {"Sd": 180, "St": 193},
}

# Typical specific gravity by product (indicative reference values —
# always confirm with the actual product datasheet before final design)
PRODUCTS = {
    "Water":                    1.000,
    "Sea water":                1.025,
    "Crude oil":                0.850,
    "Diesel":                   0.850,
    "Gasoline":                 0.740,
    "Kerosene / Jet fuel":      0.800,
    "Fuel oil (heavy)":         0.950,
    "Ethanol":                  0.790,
    "Methanol":                 0.790,
    "Sulfuric acid (98%)":      1.840,
    "Caustic soda / NaOH (50%)":1.530,
    "LPG (liquid phase)":       0.510,
}

STEEL_DENSITY = 7850  # kg/m3

# ============================================================
# API 650 — SHELL CALCULATION FUNCTIONS (validated against Annex K)
# ============================================================

def table_min(D):
    """Table 5.1a — minimum shell plate thickness (mm) based on diameter (m)"""
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
    """Bonus 1 — Annex F.2.1 — fixed roof internal pressure
    H must already be the "liquid" H (never the physical shell H)."""
    if P >= 1:
        return H + P / (9.8 * G)
    return H


def wind_pressure(V):
    """§5.9.6 — design wind pressure Pwd (kPa) from wind speed V (km/h)"""
    Pwv = 1.48 * (V / 190) ** 2
    Pwd = Pwv + 0.24
    return Pwd


def wind_girder_h1(D, t, V):
    """Bonus 2 — §5.9.6.1 — maximum unstiffened height"""
    Pwd = wind_pressure(V)
    return 9.47 * t * math.sqrt((t / D) ** 3 * (1.72 / Pwd))


def nombre_plaques(D, L_plaque_mm=6000):
    """Bonus 4 — number of plates per course"""
    return math.ceil((math.pi * D * 1000) / L_plaque_mm)


def h_local_liquide(H_liquide, cum_bottom_m):
    """Distance between the bottom of the course and the design liquid level."""
    return H_liquide - cum_bottom_m


def calculer_reservoir(D, H_shell, H_liquide, h_course_mm, G, CA, Sd, St,
                        method="AUTO", P=0, V=0, L_plaque_mm=6000):
    """Full shell thickness schedule calculation, bottom -> top."""

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
            "validity_msg": "ERROR: One-Foot Method is not allowed for D > 61 m (§5.6.3.1 API 650). Please select the VDP or AUTO method.",
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

    wind_result = None
    if V > 0:
        t_ref = min(c["Thickness (mm)"] for c in courses)
        H1 = wind_girder_h1(D, t_ref, V)
        H_transf = sum(c["Height (m)"] * 1000 * (t_ref / c["Thickness (mm)"]) ** 2.5 for c in courses) / 1000
        wind_result = {"H1": round(H1, 2), "H_transformed": round(H_transf, 2), "ok": H_transf <= H1}

    poids_total = sum(
        math.pi * D * c["Height (m)"] * (c["Thickness (mm)"] / 1000) * STEEL_DENSITY
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
        "t_first_course": courses[0]["Thickness (mm)"],
    }


# ============================================================
# NEW MODULE 1 — BOTTOM PLATE & ANNULAR PLATE (§5.4 / §5.5)
# ============================================================

def calculer_fond(D, t_first_course_mm, Sd, CA):
    """
    Bottom plate design per API 650 §5.4 and annular plate per §5.5.

    - Central bottom plate: nominal minimum thickness of 6 mm (§5.4.1),
      plus corrosion allowance.
    - Annular plate: full Table 5.1a is a two-way lookup (first course
      thickness vs. stress level) that requires the exact printed table.
      Here we apply the documented simplified rule of thumb instead, and
      flag when the exact Table 5.1a should be checked directly against
      the standard for the final engineering deliverable.
    """
    t_bottom_nominal = 6.0  # mm, §5.4.1 minimum
    t_bottom = t_bottom_nominal + CA

    annular_required = D >= 30 or Sd > 160  # simplified trigger (large tanks / high-stress materials)

    if t_first_course_mm <= 19:
        t_annular_base = 6.0
        note = "First shell course ≤ 19 mm: annular plate = same as bottom plate (rule of thumb)."
    elif t_first_course_mm <= 38:
        t_annular_base = 12.0
        note = "First shell course between 19 and 38 mm: annular plate approx. bottom + 6 mm (rule of thumb)."
    else:
        t_annular_base = 16.0
        note = ("First shell course > 38 mm: check the exact API 650 Table 5.1a "
                "(stress-dependent) — this value is a conservative estimate only.")

    t_annular = t_annular_base + CA

    # Minimum annular plate width, §5.5.2 (simplified)
    L_min_mm = 600  # 24 in, standard minimum radial width

    return {
        "t_bottom": round(t_bottom, 2),
        "t_annular": round(t_annular, 2),
        "annular_required": annular_required,
        "L_annular_min_mm": L_min_mm,
        "note": note,
    }


# ============================================================
# NEW MODULE 2 — SELF-SUPPORTING CONE ROOF (§5.10.5)
# ============================================================

def calculer_toit(D, theta_deg, CA):
    """
    Self-supporting cone roof per API 650 §5.10.5.1.
    Slope must be between 9.5° (2:12) and 37° (9:12).
    Classic thickness formula (SI units): t = D / (4.8 * sin(theta)),
    bounded between 5 mm and 13 mm (per §5.10.5.1). If the raw computed
    value exceeds 13 mm, a self-supporting cone roof is not adequate and
    a rafter-supported or dome/umbrella roof should be used instead.
    """
    theta_rad = math.radians(theta_deg)
    valid_slope = 9.5 <= theta_deg <= 37

    t_calc = D / (4.8 * math.sin(theta_rad)) if theta_deg > 0 else 0
    t_bounded = min(max(t_calc, 5.0), 13.0)
    over_limit = t_calc > 13.0

    t_roof = t_bounded + CA

    r = D / 2
    h_cone = r * math.tan(theta_rad)
    slant_length = r / math.cos(theta_rad) if theta_deg > 0 else r
    area = math.pi * r * slant_length  # lateral cone surface area, m^2

    poids_toit_kg = area * (t_bounded / 1000) * STEEL_DENSITY

    return {
        "valid_slope": valid_slope,
        "t_calc": round(t_calc, 2),
        "t_roof": round(t_roof, 2),
        "over_limit": over_limit,
        "h_cone": round(h_cone, 2),
        "slant_length": round(slant_length, 2),
        "area": round(area, 2),
        "poids_toit_kg": round(poids_toit_kg, 0),
    }


# ============================================================
# NEW MODULE 3 — OVERTURNING STABILITY / ANCHORAGE (simplified, Annex E spirit)
# ============================================================

def calculer_stabilite(D, H_shell, poids_shell_kg, poids_toit_kg, poids_fond_kg, V, n_anchors=4):
    """
    Simplified overturning stability check, in the spirit of API 650
    Annex E (wind overturning only — seismic per Annex E is a separate,
    more elaborate analysis not covered here).

    Wind overturning moment:   Mw = Pwd * D * H^2 / 2      (kN.m)
    Stabilizing moment:        Mstab = W_empty * D / 2     (kN.m)
    Safety factor:             SF = Mstab / Mw

    This is a preliminary/educational check. The full Annex E method
    (Thompson approach, seismic combination, etc.) should be used for
    a final, certified design.
    """
    Pwd = wind_pressure(V)  # kPa
    Mw = Pwd * D * (H_shell ** 2) / 2  # kN.m

    W_empty_kg = poids_shell_kg + poids_toit_kg + poids_fond_kg
    W_empty_kN = W_empty_kg * 9.81 / 1000

    Mstab = W_empty_kN * D / 2  # kN.m

    SF = Mstab / Mw if Mw > 0 else float("inf")
    self_anchored = SF >= 1.5

    anchor_force_kN = 0.0
    if not self_anchored:
        # Simplified uplift force distributed over n_anchors
        M_net = (Mw * 1.5) - Mstab
        anchor_force_kN = max(M_net / (D * n_anchors), 0.0)

    return {
        "Pwd": round(Pwd, 3),
        "Mw": round(Mw, 1),
        "Mstab": round(Mstab, 1),
        "W_empty_kg": round(W_empty_kg, 0),
        "SF": round(SF, 2) if SF != float("inf") else None,
        "self_anchored": self_anchored,
        "n_anchors": n_anchors,
        "anchor_force_kN": round(anchor_force_kN, 1),
    }


# ============================================================
# VISUAL DIAGRAM — tank elevation / cross-section
# ============================================================
def dessiner_schema_reservoir(resultat):
    """Draws a vertical cross-section of the tank: each course is a
    stacked rectangle, colored by its thickness (darker = thicker).
    The design liquid level is shown with a dashed line."""

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
# STREAMLIT INTERFACE
# ============================================================
st.set_page_config(page_title="API 650 Calculator", page_icon="🏗️", layout="wide")

st.title("🏗️ API 650 Calculator")
st.caption("Your tool for calculation and design of a storage reservoir")

# ------------------------------------------------------------
# SIDEBAR — Parameters
# ------------------------------------------------------------
st.sidebar.header("Parameters")

D = st.sidebar.number_input("Diameter (m)", value=0.0, step=0.5)

st.sidebar.markdown("**Heights (distinct)**")
H_shell = st.sidebar.number_input(
    "Total shell height (m)", value=0.0, step=0.5,
    help="Actual physical height of the plating, determines the number of courses."
)
H_liquide = st.sidebar.number_input(
    "Design liquid level (m)", value=0.0, step=0.5,
    help="Maximum fill level, used in ALL stress formulas. "
         "Can be lower than the shell height (freeboard)."
)

st.sidebar.markdown("**Stored product**")
product = st.sidebar.selectbox("Product type", ["— Select —"] + list(PRODUCTS.keys()) + ["Custom / Other"])

if product == "— Select —":
    G = 0.0
elif product == "Custom / Other":
    G = st.sidebar.number_input("Specific gravity G", value=0.0, step=0.05)
else:
    G = PRODUCTS[product]
    st.sidebar.caption(f"Specific gravity G = **{G}** (typical value for {product} — confirm with actual product data)")

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
    st.sidebar.caption(f"Sd = **{Sd} MPa**, St = **{St} MPa** (API 650 Table 5.2a)")

CA = st.sidebar.number_input("Corrosion allowance (mm)", value=0.0, step=0.1)
h_course_mm = st.sidebar.number_input("Course height (mm)", value=0, step=100)
method = st.sidebar.selectbox("Shell method", ["AUTO", "ONEFOOT", "VDP"])

st.sidebar.markdown("---")
st.sidebar.subheader("Roof")
theta_deg = st.sidebar.number_input(
    "Roof slope (degrees)", value=0.0, min_value=0.0, max_value=45.0, step=0.5,
    help="Self-supporting cone roof: valid range is 9.5° to 37° (API 650 §5.10.5.1)."
)

st.sidebar.markdown("---")
st.sidebar.subheader("Bonus options")

use_pressure = st.sidebar.checkbox("Fixed roof — internal pressure")
P = st.sidebar.number_input("Pressure P (kPa)", value=0.0, step=0.5) if use_pressure else 0

V = st.sidebar.number_input("Wind speed (km/h)", value=0.0, step=5.0,
                             help="Used for the wind girder check and the overturning stability check.")

n_anchors = st.sidebar.number_input("Number of anchor bolts (if required)", value=4, min_value=4, step=2)

L_plaque_mm = st.sidebar.number_input("Standard plate length (mm)", value=0, step=100)

st.sidebar.markdown("---")
run_clicked = st.sidebar.button("Run calculation", type="primary", use_container_width=True)

if run_clicked:
    missing = D == 0 or H_shell == 0 or H_liquide == 0 or G == 0 or Sd == 0 or St == 0 or h_course_mm == 0 or L_plaque_mm == 0 or theta_deg == 0
    if missing:
        st.error("Please fill in all required values (diameter, heights, product, material, course height, plate length, roof slope) before running the calculation.")
        st.stop()

    resultat_shell = calculer_reservoir(
        D=D, H_shell=H_shell, H_liquide=H_liquide, h_course_mm=h_course_mm,
        G=G, CA=CA, Sd=Sd, St=St,
        method=method, P=P, V=V, L_plaque_mm=L_plaque_mm
    )
    st.session_state["resultat_shell"] = resultat_shell

    if resultat_shell["valid"]:
        resultat_toit = calculer_toit(D, theta_deg, CA)
        resultat_fond = calculer_fond(D, resultat_shell["t_first_course"], Sd, CA)
        resultat_stabilite = calculer_stabilite(
            D, H_shell,
            resultat_shell["poids_total_kg"],
            resultat_toit["poids_toit_kg"],
            0,  # bottom plate weight added below once computed
            V, int(n_anchors)
        )
        # Recompute bottom weight and refine stability with it included
        poids_fond_kg = math.pi * (D / 2) ** 2 * (resultat_fond["t_bottom"] / 1000) * STEEL_DENSITY
        resultat_stabilite = calculer_stabilite(
            D, H_shell,
            resultat_shell["poids_total_kg"],
            resultat_toit["poids_toit_kg"],
            poids_fond_kg,
            V, int(n_anchors)
        )
        resultat_fond["poids_fond_kg"] = round(poids_fond_kg, 0)

        st.session_state["resultat_toit"] = resultat_toit
        st.session_state["resultat_fond"] = resultat_fond
        st.session_state["resultat_stabilite"] = resultat_stabilite

# ------------------------------------------------------------
# MAIN AREA
# ------------------------------------------------------------
if "resultat_shell" not in st.session_state:
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #8a6d1a 0%, #b8912b 100%);
            padding: 42px 40px;
            border-radius: 12px;
            color: white;
            margin-bottom: 28px;
        ">
            <h2 style="margin:0 0 8px 0; color:white;">Tank design, done right.</h2>
            <p style="margin:0; font-size: 16px; opacity: 0.92; max-width: 640px;">
                Enter your tank geometry, product and material in the sidebar to get a
                full API 650 design: shell thickness schedule, bottom and annular plates,
                self-supporting roof, wind girder check, and overturning stability.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown("#### 📐 Shell")
        st.caption("One-Foot Method and VDP, course by course.")
    with c2:
        st.markdown("#### 🧱 Bottom")
        st.caption("Central plate and annular plate thickness.")
    with c3:
        st.markdown("#### 🔺 Roof")
        st.caption("Self-supporting cone roof thickness and weight.")
    with c4:
        st.markdown("#### 💨 Wind girder")
        st.caption("Maximum unstiffened height check.")
    with c5:
        st.markdown("#### ⚓ Stability")
        st.caption("Overturning check and anchor bolt sizing.")

    st.info("👈 Fill in the parameters in the sidebar, then click **Run calculation**.")

else:
    res = st.session_state["resultat_shell"]

    if not res["valid"]:
        st.error(res["validity_msg"])
        st.stop()

    if res["freeboard_msg"]:
        st.caption(f"ℹ️ {res['freeboard_msg']}")

    tab_shell, tab_bottom, tab_roof, tab_stability = st.tabs(
        ["📐 Shell & Wind Girder", "🧱 Bottom Plate", "🔺 Roof", "⚓ Stability / Anchorage"]
    )

    # ---------------- SHELL TAB ----------------
    with tab_shell:
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
            st.subheader("Wind girder")
            c1, c2, c3 = st.columns(3)
            c1.metric("H1 (m)", res["wind"]["H1"])
            c2.metric("Transformed H (m)", res["wind"]["H_transformed"])
            c3.metric("Status", "✅ OK" if res["wind"]["ok"] else "⚠️ Required")

        st.subheader("Shell weight")
        st.metric("Total shell weight (kg)", f"{res['poids_total_kg']:.0f}")

    # ---------------- BOTTOM TAB ----------------
    with tab_bottom:
        if "resultat_fond" in st.session_state:
            fond = st.session_state["resultat_fond"]
            st.subheader("Bottom & annular plate (§5.4 / §5.5)")

            c1, c2, c3 = st.columns(3)
            c1.metric("Central bottom plate (mm)", f"{fond['t_bottom']}")
            c2.metric("Annular plate (mm)", f"{fond['t_annular']}")
            c3.metric("Bottom plate weight (kg)", f"{fond.get('poids_fond_kg', 0):.0f}")

            st.caption(f"Minimum annular plate radial width: {fond['L_annular_min_mm']} mm (§5.5.2).")
            st.info(fond["note"])

            if fond["annular_required"]:
                st.warning("Butt-welded annular bottom plates are required for this tank (large diameter and/or high-stress material group — §5.5.1).")
            else:
                st.success("Lap-welded bottom plates may be acceptable (verify against §5.5.1 criteria for the final design).")

    # ---------------- ROOF TAB ----------------
    with tab_roof:
        if "resultat_toit" in st.session_state:
            toit = st.session_state["resultat_toit"]
            st.subheader("Self-supporting cone roof (§5.10.5.1)")

            if not toit["valid_slope"]:
                st.error("Roof slope is outside the valid range for a self-supporting cone roof (9.5° to 37°). Consider a rafter-supported or dome/umbrella roof instead.")
            elif toit["over_limit"]:
                st.error(f"Calculated raw thickness ({toit['t_calc']} mm) exceeds the 13 mm cap for self-supporting cone roofs. A rafter-supported or dome/umbrella roof is required instead.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Roof thickness (mm)", f"{toit['t_roof']}")
                c2.metric("Cone height (m)", f"{toit['h_cone']}")
                c3.metric("Roof weight (kg)", f"{toit['poids_toit_kg']:.0f}")
                st.caption(f"Slant length: {toit['slant_length']} m — Roof surface area: {toit['area']} m²")

    # ---------------- STABILITY TAB ----------------
    with tab_stability:
        if "resultat_stabilite" in st.session_state:
            stab = st.session_state["resultat_stabilite"]
            st.subheader("Overturning stability check (simplified, Annex E spirit — wind only)")
            st.caption("⚠️ Educational/preliminary check. A full Annex E analysis (Thompson method, seismic combination) is required for a certified design.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Wind overturning moment Mw (kN·m)", f"{stab['Mw']:.1f}")
            c2.metric("Stabilizing moment Mstab (kN·m)", f"{stab['Mstab']:.1f}")
            c3.metric("Safety factor", f"{stab['SF']}" if stab["SF"] is not None else "n/a")

            if stab["self_anchored"]:
                st.success("Tank is self-anchored — no anchor bolts required (SF ≥ 1.5).")
            else:
                st.warning(f"Tank requires anchor bolts (SF < 1.5). Estimated tensile force per anchor: {stab['anchor_force_kN']} kN, with {stab['n_anchors']} anchors.")
                st.caption("Select the anchor bolt diameter and grade per the applicable structural steel code (e.g. AISC or Eurocode 3) based on this tensile demand.")

            st.metric("Empty tank weight (kg)", f"{stab['W_empty_kg']:.0f}")
