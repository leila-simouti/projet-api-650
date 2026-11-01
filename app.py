import matplotlib.colors as mcolors
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from calculations.api650 import MATERIALS, PRODUCTS, calculer_reservoir
from exports.reports import generer_rapport_excel, generer_rapport_pdf

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
