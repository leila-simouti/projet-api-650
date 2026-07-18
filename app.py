import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import math

# ============================================================
# API 650 — FONCTIONS DE CALCUL (validées contre Annexe K)
# ============================================================

def table_min(D):
    """Table 5.1a — épaisseur minimale (mm) selon diamètre (m)"""
    if D < 15:
        return 5
    elif D < 36:
        return 6
    elif D <= 60:
        return 8
    else:
        return 10


def round_commercial(t, step=0.5):
    """Arrondi commercial vers le haut, pas de 0.5 mm"""
    return math.ceil(t / step) * step


def one_foot_td(D, H, G, Sd, CA):
    """§5.6.3.2 — épaisseur de conception"""
    return (4.9 * D * (H - 0.3) * G) / Sd + CA


def one_foot_tt(D, H, St):
    """§5.6.3.2 — épaisseur d'essai hydrostatique"""
    return (4.9 * D * (H - 0.3)) / St


def vdp_course1(D, H, G, S, CA, is_design):
    """§5.6.4.4 — virole du bas, méthode VDP (avec plafond tp)"""
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
    """§5.6.4.6-8 — point critique x, boucle de convergence"""
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
    """§5.6.4.5 — ratio + interpolation pour la 2e virole"""
    ratio = h1 / math.sqrt(r * t1)
    if ratio <= 1.375:
        t2 = t1
    elif ratio >= 2.625:
        t2 = t2a
    else:
        t2 = t2a + (t1 - t2a) * (2.1 - h1 / (1.25 * math.sqrt(r * t1)))
    return t2


def heff_pressure(H, P, G):
    """Bonus 1 — Annexe F.2.1 — pression interne toit fixe
    H doit déjà être le H "liquide" (jamais le H physique de la robe)."""
    if P >= 1:
        return H + P / (9.8 * G)
    return H


def wind_girder_h1(D, t, V):
    """Bonus 2 — §5.9.6.1 — hauteur max non raidie"""
    Pwv = 1.48 * (V / 190) ** 2
    Pwd = Pwv + 0.24
    return 9.47 * t * math.sqrt((t / D) ** 3 * (1.72 / Pwd))


def nombre_plaques(D, L_plaque_mm=6000):
    """Bonus 4 — nombre de tôles par virole"""
    return math.ceil((math.pi * D * 1000) / L_plaque_mm)


def h_local_liquide(H_liquide, cum_bottom_m):
    """Distance entre le bas de la virole et le niveau de liquide de conception."""
    return H_liquide - cum_bottom_m


def calculer_reservoir(D, H_shell, H_liquide, h_course_mm, G, CA, Sd, St,
                        method="AUTO", P=0, V=0, L_plaque_mm=6000):
    """Calcul complet du programme d'épaisseurs, bas -> haut."""

    r = (D * 1000) / 2

    freeboard_msg = ""
    if H_liquide > H_shell:
        freeboard_msg = "ATTENTION : H_liquide > H_shell — plafonné à H_shell."
        H_liquide = H_shell
    elif H_liquide < H_shell:
        freeboard = H_shell - H_liquide
        freeboard_msg = f"Freeboard (marge de sécurité) = {freeboard:.2f} m"

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
                         else f"ATTENTION : hors domaine VDP (L/H={ratio_LH:.3f})")
    elif D > 61:
        validity_msg = "ATTENTION : D > 61 m, One-Foot Method non valide"

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
            "Virole": i + 1,
            "Hauteur (m)": round(heights[i] / 1000, 3),
            "H local liquide (m)": round(max(h_local, 0), 2),
            "td (mm)": round(td, 2),
            "tt (mm)": round(tt, 2),
            "t min (mm)": tmin,
            "t gouvernante (mm)": round(governing, 2),
            "Épaisseur (mm)": t_use,
            "Nb Plaques": nombre_plaques(D, L_plaque_mm),
        })

    wind_result = None
    if V > 0:
        t_ref = min(c["Épaisseur (mm)"] for c in courses)
        H1 = wind_girder_h1(D, t_ref, V)
        H_transf = sum(c["Hauteur (m)"] * 1000 * (t_ref / c["Épaisseur (mm)"]) ** 2.5 for c in courses) / 1000
        wind_result = {"H1": round(H1, 2), "H_transformee": round(H_transf, 2), "ok": H_transf <= H1}

    density = 7850
    poids_total = sum(
        math.pi * D * c["Hauteur (m)"] * (c["Épaisseur (mm)"] / 1000) * density
        for c in courses
    )

    return {
        "D": D, "H_shell": H_shell, "H_liquide": H_liquide,
        "method_used": method_used,
        "validity_msg": validity_msg,
        "freeboard_msg": freeboard_msg,
        "courses": courses,
        "wind": wind_result,
        "poids_total_kg": round(poids_total, 0),
    }


# ============================================================
# SCHEMA VISUEL — coupe/élévation du réservoir
# ============================================================
def dessiner_schema_reservoir(resultat):
    """Dessine une coupe verticale du réservoir : chaque virole est un
    rectangle empilé, coloré selon son épaisseur (plus foncé = plus épais).
    Le niveau de liquide de conception est indiqué par une ligne pointillée."""

    courses = resultat["courses"]
    D = resultat["D"]
    H_liquide = resultat["H_liquide"]
    H_shell = resultat["H_shell"]

    epaisseurs = [c["Épaisseur (mm)"] for c in courses]
    tmin_c, tmax_c = min(epaisseurs), max(epaisseurs)
    norm = mcolors.Normalize(vmin=tmin_c, vmax=max(tmax_c, tmin_c + 0.1))
    cmap = plt.get_cmap("Blues")

    largeur_dessin = 4.0  # largeur fixe du schéma (représentation, pas à l'échelle du diamètre)

    fig, ax = plt.subplots(figsize=(4.5, 7))

    y_bas = 0.0
    for c in courses:
        h = c["Hauteur (m)"]
        t = c["Épaisseur (mm)"]
        couleur = cmap(norm(t))

        rect = patches.Rectangle((0, y_bas), largeur_dessin, h,
                                  facecolor=couleur, edgecolor="#333333", linewidth=1.1)
        ax.add_patch(rect)

        # Étiquette : numéro de virole + épaisseur, centrée dans le rectangle
        luminosite = 0.299 * couleur[0] + 0.587 * couleur[1] + 0.114 * couleur[2]
        couleur_texte = "white" if luminosite < 0.55 else "black"
        ax.text(largeur_dessin / 2, y_bas + h / 2,
                 f"V{c['Virole']} — {t:.1f} mm",
                 ha="center", va="center", fontsize=9, color=couleur_texte, weight="bold")

        y_bas += h

    # Ligne du niveau de liquide de conception
    ax.axhline(H_liquide, color="#1f77b4", linestyle="--", linewidth=1.8)
    ax.text(largeur_dessin + 0.15, H_liquide, f"Niveau liquide\nH = {H_liquide:.2f} m",
            va="center", fontsize=8.5, color="#1f77b4")

    # Sommet réel de la robe
    if H_shell > H_liquide:
        ax.text(largeur_dessin + 0.15, H_shell, f"Sommet robe\nH = {H_shell:.2f} m",
                va="center", fontsize=8.5, color="#555555")

    ax.set_xlim(-0.3, largeur_dessin + 2.3)
    ax.set_ylim(0, max(H_shell, y_bas) * 1.05)
    ax.set_xticks([])
    ax.set_ylabel("Hauteur (m)")
    ax.set_title(f"Coupe de la robe — D = {D:.1f} m", fontsize=11, weight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout()
    return fig


# ============================================================
# INTERFACE STREAMLIT
# ============================================================
st.set_page_config(page_title="Calculateur API 650", layout="wide")
st.title("🏗️ Calculateur API 650")

st.sidebar.header("Paramètres")

D = st.sidebar.number_input("Diamètre (m)", value=30.00, step=0.5)

st.sidebar.markdown("**Hauteurs (distinctes)**")
H_shell = st.sidebar.number_input(
    "Hauteur totale de la robe (m)", value=15.50, step=0.5,
    help="Hauteur physique réelle de la tôle, détermine le nombre de viroles."
)
H_liquide = st.sidebar.number_input(
    "Niveau de liquide de conception (m)", value=15.00, step=0.5,
    help="Niveau maximal de remplissage, utilisé dans TOUTES les formules "
         "de contrainte. Peut être < hauteur de la robe (freeboard)."
)

G = st.sidebar.number_input("Densité", value=1.00, step=0.05)
Sd = st.sidebar.number_input("Contrainte Design (Sd)", value=179.00, step=1.0)
St = st.sidebar.number_input("Contrainte Test (St)", value=190.00, step=1.0)
CA = st.sidebar.number_input("Corrosion Allowance (mm)", value=1.50, step=0.1)
h_course_mm = st.sidebar.number_input("Hauteur virole (mm)", value=2000, step=100)
method = st.sidebar.selectbox("Méthode", ["AUTO", "ONEFOOT", "VDP"])

st.sidebar.markdown("---")
st.sidebar.subheader("Options bonus")

use_pressure = st.sidebar.checkbox("Toit fixe — pression interne")
P = st.sidebar.number_input("Pression P (kPa)", value=0.0, step=0.5) if use_pressure else 0

use_wind = st.sidebar.checkbox("Vérifier ceinture de vent", value=True)
V = st.sidebar.number_input("Vitesse de vent (km/h)", value=150.0, step=5.0) if use_wind else 0

L_plaque_mm = st.sidebar.number_input("Longueur tôle standard (mm)", value=6000, step=100)

st.sidebar.markdown("---")

if st.sidebar.button("Lancer les calculs"):
    resultat = calculer_reservoir(
        D=D, H_shell=H_shell, H_liquide=H_liquide, h_course_mm=h_course_mm,
        G=G, CA=CA, Sd=Sd, St=St,
        method=method, P=P, V=V, L_plaque_mm=L_plaque_mm
    )
    st.session_state["resultat"] = resultat

if "resultat" in st.session_state:
    res = st.session_state["resultat"]

    if res["freeboard_msg"]:
        st.caption(f"ℹ️ {res['freeboard_msg']}")

    col_table, col_schema = st.columns([2, 1])

    with col_table:
        st.subheader("Résultats par virole")
        df = pd.DataFrame(res["courses"])
        st.dataframe(df, use_container_width=True)

        st.info(f"Méthode utilisée : **{res['method_used']}**")
        if res["validity_msg"]:
            st.warning(res["validity_msg"])

    with col_schema:
        st.subheader("Schéma de la robe")
        fig = dessiner_schema_reservoir(res)
        st.pyplot(fig)

    if res["wind"]:
        st.subheader("Bonus — Ceinture de vent")
        c1, c2, c3 = st.columns(3)
        c1.metric("H1 (m)", res["wind"]["H1"])
        c2.metric("H transformée (m)", res["wind"]["H_transformee"])
        c3.metric("Statut", "✅ OK" if res["wind"]["ok"] else "⚠️ Requise")

    st.subheader("Bonus — Fabrication")
    st.metric("Poids total de la robe (kg)", f"{res['poids_total_kg']:.0f}")

    st.success("Calculs terminés avec succès !")