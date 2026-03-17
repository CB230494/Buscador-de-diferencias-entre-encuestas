# app.py — Pareto con gráfico 80/20 real + Portafolio + Unificado + Sheets DB (fixes)
# -----------------------------------------------------------------------------------
# Requisitos:
#   pip install streamlit pandas matplotlib xlsxwriter gspread google-auth
#   streamlit run app.py
# -----------------------------------------------------------------------------------

import io
from typing import List, Dict

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# ====== Google Sheets (DB) ======
import gspread
from google.oauth2.service_account import Credentials

# URL de tu hoja (DB)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1cf-avzRjtBXcqr69WfrrsTAegm0PMAe8LgjeLpfcS5g/edit?usp=sharing"
WS_PARETOS = "paretos"  # hoja donde se guardan los paretos (nombre, descriptor, frecuencia)

st.set_page_config(page_title="Pareto de Descriptores", layout="wide")

# ============================================================================
# 1) CATÁLOGO EMBEBIDO
# ============================================================================
CATALOGO: List[Dict[str, str]] = [
    {"categoria": "Delito", "descriptor": "Abandono de personas (menor de edad, adulto mayor o con capacidades diferentes)"},
    {"categoria": "Delito", "descriptor": "Abigeato (robo y destace de ganado)"},
    {"categoria": "Delito", "descriptor": "Aborto"},
    {"categoria": "Delito", "descriptor": "Abuso de autoridad"},
    {"categoria": "Riesgo social", "descriptor": "Accidentes de tránsito"},
    {"categoria": "Delito", "descriptor": "Accionamiento de arma de fuego (balaceras)"},
    {"categoria": "Riesgo social", "descriptor": "Acoso escolar (bullying)"},
    {"categoria": "Riesgo social", "descriptor": "Acoso laboral (mobbing)"},
    {"categoria": "Riesgo social", "descriptor": "Acoso sexual callejero"},
    {"categoria": "Riesgo social", "descriptor": "Actos obscenos en vía pública"},
    {"categoria": "Delito", "descriptor": "Administración fraudulenta, apropiaciones indebidas o enriquecimiento ilícito"},
    {"categoria": "Delito", "descriptor": "Agresión con armas"},
    {"categoria": "Riesgo social", "descriptor": "Agrupaciones delincuenciales no organizadas"},
    {"categoria": "Delito", "descriptor": "Alteración de datos y sabotaje informático"},
    {"categoria": "Otros factores", "descriptor": "Ambiente laboral inadecuado"},
    {"categoria": "Delito", "descriptor": "Amenazas"},
    {"categoria": "Riesgo social", "descriptor": "Analfabetismo"},
    {"categoria": "Riesgo social", "descriptor": "Bajos salarios"},
    {"categoria": "Riesgo social", "descriptor": "Barras de fútbol"},
    {"categoria": "Riesgo social", "descriptor": "Búnker (eje de expendio de drogas)"},
    {"categoria": "Delito", "descriptor": "Calumnia"},
    {"categoria": "Delito", "descriptor": "Caza ilegal"},
    {"categoria": "Delito", "descriptor": "Conducción temeraria"},
    {"categoria": "Riesgo social", "descriptor": "Consumo de alcohol en vía pública"},
    {"categoria": "Riesgo social", "descriptor": "Consumo de drogas"},
    {"categoria": "Riesgo social", "descriptor": "Contaminación sónica"},
    {"categoria": "Delito", "descriptor": "Contrabando"},
    {"categoria": "Delito", "descriptor": "Corrupción"},
    {"categoria": "Delito", "descriptor": "Corrupción policial"},
    {"categoria": "Delito", "descriptor": "Cultivo de droga (marihuana)"},
    {"categoria": "Delito", "descriptor": "Daño ambiental"},
    {"categoria": "Delito", "descriptor": "Daños/vandalismo"},
    {"categoria": "Riesgo social", "descriptor": "Deficiencia en la infraestructura vial"},
    {"categoria": "Otros factores", "descriptor": "Deficiencia en la línea 9-1-1"},
    {"categoria": "Riesgo social", "descriptor": "Deficiencias en el alumbrado público"},
    {"categoria": "Delito", "descriptor": "Delincuencia organizada"},
    {"categoria": "Delito", "descriptor": "Delitos contra el ámbito de intimidad (violación de secretos, correspondencia y comunicaciones electrónicas)"},
    {"categoria": "Delito", "descriptor": "Delitos sexuales"},
    {"categoria": "Riesgo social", "descriptor": "Desaparición de personas"},
    {"categoria": "Riesgo social", "descriptor": "Desarticulación interinstitucional"},
    {"categoria": "Riesgo social", "descriptor": "Desempleo"},
    {"categoria": "Riesgo social", "descriptor": "Desvinculación estudiantil"},
    {"categoria": "Delito", "descriptor": "Desobediencia"},
    {"categoria": "Delito", "descriptor": "Desórdenes en vía pública"},
    {"categoria": "Delito", "descriptor": "Disturbios (riñas)"},
    {"categoria": "Riesgo social", "descriptor": "Enfrentamientos estudiantiles"},
    {"categoria": "Delito", "descriptor": "Estafa o defraudación"},
    {"categoria": "Delito", "descriptor": "Estupro (delitos sexuales contra menor de edad)"},
    {"categoria": "Delito", "descriptor": "Evasión y quebrantamiento de pena"},
    {"categoria": "Delito", "descriptor": "Explosivos"},
    {"categoria": "Delito", "descriptor": "Extorsión"},
    {"categoria": "Delito", "descriptor": "Fabricación, producción o reproducción de pornografía"},
    {"categoria": "Riesgo social", "descriptor": "Facilismo económico"},
    {"categoria": "Delito", "descriptor": "Falsificación de moneda y otros valores"},
    {"categoria": "Riesgo social", "descriptor": "Falta de cámaras de seguridad"},
    {"categoria": "Otros factores", "descriptor": "Falta de capacitación policial"},
    {"categoria": "Riesgo social", "descriptor": "Falta de control a patentes"},
    {"categoria": "Riesgo social", "descriptor": "Falta de control fronterizo"},
    {"categoria": "Riesgo social", "descriptor": "Falta de corresponsabilidad en seguridad"},
    {"categoria": "Riesgo social", "descriptor": "Falta de cultura vial"},
    {"categoria": "Riesgo social", "descriptor": "Falta de cultura y compromiso ciudadano"},
    {"categoria": "Riesgo social", "descriptor": "Falta de educación familiar"},
    {"categoria": "Otros factores", "descriptor": "Falta de incentivos"},
    {"categoria": "Riesgo social", "descriptor": "Falta de inversión social"},
    {"categoria": "Riesgo social", "descriptor": "Falta de legislación de extinción de dominio"},
    {"categoria": "Otros factores", "descriptor": "Falta de personal administrativo"},
    {"categoria": "Otros factores", "descriptor": "Falta de personal policial"},
    {"categoria": "Otros factores", "descriptor": "Falta de policías de tránsito"},
    {"categoria": "Riesgo social", "descriptor": "Falta de políticas públicas en seguridad"},
    {"categoria": "Riesgo social", "descriptor": "Falta de presencia policial"},
    {"categoria": "Riesgo social", "descriptor": "Falta de salubridad pública"},
    {"categoria": "Riesgo social", "descriptor": "Familias disfuncionales"},
    {"categoria": "Delito", "descriptor": "Fraude informático"},
    {"categoria": "Delito", "descriptor": "Grooming"},
    {"categoria": "Riesgo social", "descriptor": "Hacinamiento carcelario"},
    {"categoria": "Riesgo social", "descriptor": "Hacinamiento policial"},
    {"categoria": "Delito", "descriptor": "Homicidio"},
    {"categoria": "Riesgo social", "descriptor": "Hospedajes ilegales (cuarterías)"},
    {"categoria": "Delito", "descriptor": "Hurto"},
    {"categoria": "Otros factores", "descriptor": "Inadecuado uso del recurso policial"},
    {"categoria": "Riesgo social", "descriptor": "Incumplimiento al plan regulador de la municipalidad"},
    {"categoria": "Delito", "descriptor": "Incumplimiento del deber alimentario"},
    {"categoria": "Riesgo social", "descriptor": "Indiferencia social"},
    {"categoria": "Otros factores", "descriptor": "Inefectividad en el servicio de policía"},
    {"categoria": "Riesgo social", "descriptor": "Ineficiencia en la administración de justicia"},
    {"categoria": "Otros factores", "descriptor": "Infraestructura inadecuada"},
    {"categoria": "Riesgo social", "descriptor": "Intolerancia social"},
    {"categoria": "Otros factores", "descriptor": "Irrespeto a la jefatura"},
    {"categoria": "Otros factores", "descriptor": "Irrespeto al subalterno"},
    {"categoria": "Otros factores", "descriptor": "Jornadas laborales extensas"},
    {"categoria": "Delito", "descriptor": "Lavado de activos"},
    {"categoria": "Delito", "descriptor": "Lesiones"},
    {"categoria": "Delito", "descriptor": "Ley de armas y explosivos N° 7530"},
    {"categoria": "Riesgo social", "descriptor": "Ley de control de tabaco (Ley 9028)"},
    {"categoria": "Riesgo social", "descriptor": "Lotes baldíos"},
    {"categoria": "Delito", "descriptor": "Maltrato animal"},
    {"categoria": "Delito", "descriptor": "Narcotráfico"},
    {"categoria": "Riesgo social", "descriptor": "Necesidades básicas insatisfechas"},
    {"categoria": "Riesgo social", "descriptor": "Percepción de inseguridad"},
    {"categoria": "Riesgo social", "descriptor": "Pérdida de espacios públicos"},
    {"categoria": "Riesgo social", "descriptor": "Personas con exceso de tiempo de ocio"},
    {"categoria": "Riesgo social", "descriptor": "Personas en estado migratorio irregular"},
    {"categoria": "Riesgo social", "descriptor": "Personas en situación de calle"},
    {"categoria": "Delito", "descriptor": "Menores en vulnerabilidad"},
    {"categoria": "Delito", "descriptor": "Pesca ilegal"},
    {"categoria": "Delito", "descriptor": "Portación ilegal de armas"},
    {"categoria": "Riesgo social", "descriptor": "Presencia multicultural"},
    {"categoria": "Otros factores", "descriptor": "Presión por resultados operativos"},
    {"categoria": "Delito", "descriptor": "Privación de libertad sin ánimo de lucro"},
    {"categoria": "Riesgo social", "descriptor": "Problemas vecinales"},
    {"categoria": "Delito", "descriptor": "Receptación"},
    {"categoria": "Delito", "descriptor": "Relaciones impropias"},
    {"categoria": "Delito", "descriptor": "Resistencia (irrespeto a la autoridad)"},
    {"categoria": "Delito", "descriptor": "Robo a comercio (intimidación)"},
    {"categoria": "Delito", "descriptor": "Robo a comercio (tacha)"},
    {"categoria": "Delito", "descriptor": "Robo a edificación (tacha)"},
    {"categoria": "Delito", "descriptor": "Robo a personas"},
    {"categoria": "Delito", "descriptor": "Robo a transporte comercial"},
    {"categoria": "Delito", "descriptor": "Robo a vehículos (tacha)"},
    {"categoria": "Delito", "descriptor": "Robo a vivienda (intimidación)"},
    {"categoria": "Delito", "descriptor": "Robo a vivienda (tacha)"},
    {"categoria": "Delito", "descriptor": "Robo de bicicleta"},
    {"categoria": "Delito", "descriptor": "Robo de cultivos"},
    {"categoria": "Delito", "descriptor": "Robo de motocicletas/vehículos (bajonazo)"},
    {"categoria": "Delito", "descriptor": "Robo de vehículos"},
    {"categoria": "Delito", "descriptor": "Secuestro"},
    {"categoria": "Delito", "descriptor": "Simulación de delito"},
    {"categoria": "Riesgo social", "descriptor": "Sistema jurídico desactualizado"},
    {"categoria": "Riesgo social", "descriptor": "Suicidio"},
    {"categoria": "Delito", "descriptor": "Sustracción de una persona menor de edad o incapaz"},
    {"categoria": "Delito", "descriptor": "Tala ilegal"},
    {"categoria": "Riesgo social", "descriptor": "Tendencia social hacia el delito (pautas de crianza violenta)"},
    {"categoria": "Riesgo social", "descriptor": "Tenencia de droga"},
    {"categoria": "Delito", "descriptor": "Tentativa de homicidio"},
    {"categoria": "Delito", "descriptor": "Terrorismo"},
    {"categoria": "Riesgo social", "descriptor": "Trabajo informal"},
    {"categoria": "Delito", "descriptor": "Tráfico de armas"},
    {"categoria": "Delito", "descriptor": "Tráfico de influencias"},
    {"categoria": "Riesgo social", "descriptor": "Transporte informal (Uber, porteadores, piratas)"},
    {"categoria": "Delito", "descriptor": "Trata de personas"},
    {"categoria": "Delito", "descriptor": "Turbación de actos religiosos y profanaciones"},
    {"categoria": "Delito", "descriptor": "Uso ilegal de uniformes, insignias o dispositivos policiales"},
    {"categoria": "Delito", "descriptor": "Usurpación de terrenos (precarios)"},
    {"categoria": "Delito", "descriptor": "Venta de drogas"},
    {"categoria": "Riesgo social", "descriptor": "Ventas informales (ambulantes)"},
    {"categoria": "Riesgo social", "descriptor": "Vigilancia informal"},
    {"categoria": "Delito", "descriptor": "Violación de domicilio"},
    {"categoria": "Delito", "descriptor": "Violación de la custodia de las cosas"},
    {"categoria": "Delito", "descriptor": "Violación de sellos"},
    {"categoria": "Delito", "descriptor": "Violencia de género"},
    {"categoria": "Delito", "descriptor": "Violencia intrafamiliar"},
    {"categoria": "Riesgo social", "descriptor": "Xenofobia"},
    {"categoria": "Riesgo social", "descriptor": "Zonas de prostitución"},
    {"categoria": "Riesgo social", "descriptor": "Zonas vulnerables"},
    {"categoria": "Delito", "descriptor": "Robo a transporte público con intimidación"},
    {"categoria": "Delito", "descriptor": "Robo de cable"},
    {"categoria": "Delito", "descriptor": "Explotación sexual infantil"},
    {"categoria": "Delito", "descriptor": "Explotación laboral infantil"},
    {"categoria": "Delito", "descriptor": "Tráfico ilegal de personas"},
    {"categoria": "Riesgo social", "descriptor": "Bares clandestinos"},
    {"categoria": "Delito", "descriptor": "Robo de combustible"},
    {"categoria": "Delito", "descriptor": "Femicidio"},
    {"categoria": "Delito", "descriptor": "Delitos contra la vida (homicidios, heridos)"},
    {"categoria": "Delito", "descriptor": "Venta y consumo de drogas en vía pública"},
    {"categoria": "Delito", "descriptor": "Asalto (a personas, comercio, vivienda, transporte público)"},
    {"categoria": "Delito", "descriptor": "Robo de ganado y agrícola"},
    {"categoria": "Delito", "descriptor": "Robo de equipo agrícola"},
]
# ============================================================================
# 2) UTILIDADES BASE
# ============================================================================
ORANGE = "#FF8C00"
SKY    = "#87CEEB"

def calcular_pareto(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df["frecuencia"] = pd.to_numeric(df["frecuencia"], errors="coerce").fillna(0).astype(int)
    df = df[df["frecuencia"] > 0]
    if df.empty:
        return df.assign(porcentaje=0.0, acumulado=0, pct_acum=0.0,
                         segmento_real="20%", segmento="80%")
    df = df.sort_values("frecuencia", ascending=False)
    total = int(df["frecuencia"].sum())
    df["porcentaje"] = (df["frecuencia"] / total * 100).round(2)
    df["acumulado"]  = df["frecuencia"].cumsum()
    df["pct_acum"]   = (df["acumulado"] / total * 100).round(2)
    df["segmento_real"] = np.where(df["pct_acum"] <= 80.00, "80%", "20%")
    df["segmento"] = "80%"
    return df.reset_index(drop=True)

def dibujar_pareto(df_par: pd.DataFrame, titulo: str):
    if df_par.empty:
        st.info("Ingresa frecuencias (>0) para ver el gráfico.")
        return
    x        = np.arange(len(df_par))
    freqs    = df_par["frecuencia"].to_numpy()
    pct_acum = df_par["pct_acum"].to_numpy()
    colors   = [ORANGE if seg == "80%" else SKY for seg in df_par["segmento_real"]]
    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax1.bar(x, freqs, color=colors)
    ax1.set_ylabel("Frecuencia")
    ax1.set_xticks(x)
    ax1.set_xticklabels(df_par["descriptor"].tolist(), rotation=75, ha="right")
    ax1.set_title(titulo if titulo.strip() else "Pareto — Frecuencia y % acumulado")
    ax2 = ax1.twinx()
    ax2.plot(x, pct_acum, marker="o")
    ax2.set_ylabel("% acumulado")
    ax2.set_ylim(0, 110)
    if (df_par["segmento_real"] == "80%").any():
        cut_idx = np.where(df_par["segmento_real"].to_numpy() == "80%")[0].max()
        ax1.axvline(cut_idx, linestyle=":", color="k")
    ax2.axhline(80, linestyle="--")
    st.pyplot(fig)

def exportar_excel_con_grafico(df_par: pd.DataFrame, titulo: str) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        hoja = "Pareto"
        df_x = df_par.copy()
        df_x["porcentaje"] = (df_x["porcentaje"] / 100.0).round(4)
        df_x["pct_acum"]   = (df_x["pct_acum"] / 100.0).round(4)
        df_x = df_x[["categoria", "descriptor", "frecuencia",
                     "porcentaje", "pct_acum", "acumulado", "segmento"]]
        df_x.to_excel(writer, sheet_name=hoja, index=False, startrow=0, startcol=0)
        wb = writer.book; ws = writer.sheets[hoja]
        pct_fmt = wb.add_format({"num_format": "0.00%"})
        total_fmt = wb.add_format({"bold": True})
        ws.set_column("A:A", 18); ws.set_column("B:B", 55); ws.set_column("C:C", 12)
        ws.set_column("D:D", 12, pct_fmt); ws.set_column("E:E", 18, pct_fmt)
        ws.set_column("F:F", 12); ws.set_column("G:G", 10)
        n = len(df_x)
        cats = f"=Pareto!$B$2:$B${n+1}"; vals = f"=Pareto!$C$2:$C${n+1}"; pcts = f"=Pareto!$E$2:$E${n+1}"
        total = int(df_par["frecuencia"].sum())
        ws.write(n + 2, 1, "TOTAL:", total_fmt); ws.write(n + 2, 2, total, total_fmt)
        try:
            idxs = np.where(df_par["segmento_real"].to_numpy() == "80%")[0]
            if len(idxs) > 0:
                last = int(idxs.max())
                orange_bg = wb.add_format({"bg_color": ORANGE, "font_color": "#000000"})
                ws.conditional_format(1, 0, 1 + last, 6, {"type": "no_blanks", "format": orange_bg})
        except Exception:
            pass
        chart = wb.add_chart({"type": "column"})
        points = [{"fill": {"color": (ORANGE if s == "80%" else SKY)}} for s in df_par["segmento_real"]]
        chart.add_series({"name": "Frecuencia", "categories": cats, "values": vals, "points": points})
        line = wb.add_chart({"type": "line"})
        line.add_series({"name": "% acumulado", "categories": cats, "values": pcts,
                         "y2_axis": True, "marker": {"type": "circle"}})
        chart.combine(line)
        chart.set_y_axis({"name": "Frecuencia"})
        chart.set_y2_axis({"name": "Porcentaje acumulado",
                           "min": 0, "max": 1.10, "major_unit": 0.10, "num_format": "0%"})
        chart.set_title({"name": titulo if titulo.strip() else "PARETO – Frecuencia y % acumulado"})
        chart.set_legend({"position": "bottom"}); chart.set_size({"width": 1180, "height": 420})
        ws.insert_chart("I2", chart)
    return output.getvalue()

# ============================================================================
# 3) UTILIDADES DE PORTAFOLIO
# ============================================================================
def _map_descriptor_a_categoria() -> Dict[str, str]:
    df = pd.DataFrame(CATALOGO); return dict(zip(df["descriptor"], df["categoria"]))
DESC2CAT = _map_descriptor_a_categoria()

def normalizar_freq_map(freq_map: Dict[str, int]) -> Dict[str, int]:
    out = {}
    for d, v in (freq_map or {}).items():
        try:
            vv = int(pd.to_numeric(v, errors="coerce"))
            if vv > 0: out[d] = vv
        except Exception:
            continue
    return out

def df_desde_freq_map(freq_map: Dict[str, int]) -> pd.DataFrame:
    items = []
    for d, f in normalizar_freq_map(freq_map).items():
        items.append({"descriptor": d, "categoria": DESC2CAT.get(d, "—"), "frecuencia": int(f)})
    df = pd.DataFrame(items)
    if df.empty: return pd.DataFrame(columns=["descriptor", "categoria", "frecuencia"])
    return df

def combinar_maps(maps: List[Dict[str, int]]) -> Dict[str, int]:
    total = {}
    for m in maps:
        for d, f in normalizar_freq_map(m).items():
            total[d] = total.get(d, 0) + int(f)
    return total

def info_pareto(freq_map: Dict[str, int]) -> Dict[str, int]:
    d = normalizar_freq_map(freq_map); return {"descriptores": len(d), "total": int(sum(d.values()))}

# ============================================================================
# 4) GOOGLE SHEETS HELPERS
# ============================================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]

def _gc():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

def _open_sheet():
    gc = _gc(); return gc.open_by_url(SPREADSHEET_URL)

def _ensure_ws(sh, title: str, header: List[str]):
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=10)
        ws.append_row(header); return ws
    values = ws.get_all_values()
    if not values:
        ws.append_row(header)
    else:
        first = values[0]
        if [c.strip().lower() for c in first] != [c.strip().lower() for c in header]:
            ws.clear(); ws.append_row(header)
    return ws

def sheets_cargar_portafolio() -> Dict[str, Dict[str, int]]:
    try:
        sh = _open_sheet(); ws = _ensure_ws(sh, WS_PARETOS, ["nombre","descriptor","frecuencia"])
        rows = ws.get_all_records()
        port: Dict[str, Dict[str, int]] = {}
        for r in rows:
            nom = str(r.get("nombre","")).strip()
            desc = str(r.get("descriptor","")).strip()
            freq = int(pd.to_numeric(r.get("frecuencia",0), errors="coerce") or 0)
            if not nom or not desc or freq <= 0: continue
            bucket = port.setdefault(nom, {}); bucket[desc] = bucket.get(desc, 0) + freq
        return port
    except Exception:
        return {}

def sheets_guardar_pareto(nombre: str, freq_map: Dict[str, int], sobrescribir: bool = True):
    sh = _open_sheet()
    ws = _ensure_ws(sh, WS_PARETOS, ["nombre","descriptor","frecuencia"])
    if sobrescribir:
        vals = ws.get_all_values()
        header = vals[0] if vals else ["nombre","descriptor","frecuencia"]
        others = [r for r in vals[1:] if (len(r)>0 and r[0].strip().lower()!=nombre.strip().lower())]
        ws.clear(); ws.update("A1", [header])
        if others: ws.append_rows(others, value_input_option="RAW")
    rows_new = [[nombre, d, int(f)] for d, f in normalizar_freq_map(freq_map).items()]
    if rows_new: ws.append_rows(rows_new, value_input_option="RAW")
# ============================================================================
# 5) ESTADO DE SESIÓN (con flag de reseteo)
# ============================================================================
st.session_state.setdefault("freq_map", {})
st.session_state.setdefault("portafolio", {})
st.session_state.setdefault("msel", [])
st.session_state.setdefault("reset_after_save", False)

# Cargar portafolio desde Sheets una vez si está vacío
if not st.session_state["portafolio"]:
    loaded = sheets_cargar_portafolio()
    if loaded: st.session_state["portafolio"].update(loaded)

# ---- APLICAR RESET ANTES DE DIBUJAR WIDGETS ----
if st.session_state.get("reset_after_save", False):
    st.session_state["freq_map"] = {}
    st.session_state["msel"] = []
    st.session_state.pop("editor_freq", None)
    st.session_state["reset_after_save"] = False

# ============================================================================
# 6) UI PRINCIPAL
# ============================================================================
st.title("Pareto de Descriptores")

c_t1, c_t2, c_t3 = st.columns([2,1,1])
with c_t1:
    titulo = st.text_input("Título del Pareto (opcional)", value="Pareto Comunidad")
with c_t2:
    nombre_para_guardar = st.text_input("Nombre para guardar este Pareto", value="Comunidad")
with c_t3:
    if st.button("🔄 Recargar portafolio desde Sheets"):
        st.session_state["portafolio"] = sheets_cargar_portafolio()
        st.success("Portafolio recargado desde Google Sheets.")
        st.rerun()

cat_df = pd.DataFrame(CATALOGO).sort_values(["categoria","descriptor"]).reset_index(drop=True)
opciones = cat_df["descriptor"].tolist()
seleccion = st.multiselect("1) Escoge uno o varios descriptores", options=opciones,
                           default=st.session_state["msel"], key="msel")

st.subheader("2) Asigna la frecuencia")
if seleccion:
    base = cat_df[cat_df["descriptor"].isin(seleccion)].copy()
    base["frecuencia"] = [st.session_state["freq_map"].get(d, 0) for d in base["descriptor"]]

    edit = st.data_editor(
        base, key="editor_freq", num_rows="fixed", use_container_width=True,
        column_config={
            "descriptor": st.column_config.TextColumn("DESCRIPTOR", width="large"),
            "categoria": st.column_config.TextColumn("CATEGORÍA", width="small"),
            "frecuencia": st.column_config.NumberColumn("Frecuencia", min_value=0, step=1),
        },
    )
    for _, row in edit.iterrows():
        st.session_state["freq_map"][row["descriptor"]] = int(row["frecuencia"])

    df_in = edit[["descriptor","categoria"]].copy()
    df_in["frecuencia"] = df_in["descriptor"].map(st.session_state["freq_map"]).fillna(0).astype(int)

    st.subheader("3) Pareto (en edición)")
    tabla = calcular_pareto(df_in)

    mostrar = tabla.copy()[["categoria","descriptor","frecuencia","porcentaje","pct_acum","acumulado","segmento"]]
    mostrar = mostrar.rename(columns={"pct_acum": "porcentaje acumulado"})
    mostrar["porcentaje"] = mostrar["porcentaje"].map(lambda x: f"{x:.2f}%")
    mostrar["porcentaje acumulado"] = mostrar["porcentaje acumulado"].map(lambda x: f"{x:.2f}%")

    c1, c2 = st.columns([1,1], gap="large")
    with c1:
        st.markdown("**Tabla de Pareto**")
        if not tabla.empty:
            st.dataframe(mostrar, use_container_width=True, hide_index=True)
        else:
            st.info("Ingresa frecuencias (>0) para ver la tabla.")
    with c2:
        st.markdown("**Gráfico de Pareto**"); dibujar_pareto(tabla, titulo)

    st.subheader("4) Guardar / Descargar")
    col_g1, col_g2, _ = st.columns([1,1,2])
    with col_g1:
        sobrescribir = st.checkbox("Sobrescribir si existe", value=True)
        if st.button("💾 Guardar este Pareto"):
            nombre = nombre_para_guardar.strip()
            if not nombre:
                st.warning("Indica un nombre para guardar el Pareto.")
            else:
                st.session_state["portafolio"][nombre] = normalizar_freq_map(st.session_state["freq_map"])
                try:
                    sheets_guardar_pareto(nombre, st.session_state["freq_map"], sobrescribir=sobrescribir)
                    st.success(f"Pareto '{nombre}' guardado en Google Sheets y en la sesión.")
                except Exception as e:
                    st.warning(f"Se guardó en la sesión, pero hubo un problema con Sheets: {e}")
                # Activar flag de reseteo y re-ejecutar
                st.session_state["reset_after_save"] = True
                st.rerun()
    with col_g2:
        if not tabla.empty:
            st.download_button(
                "⬇️ Excel del Pareto (edición)",
                data=exportar_excel_con_grafico(tabla, titulo),
                file_name=f"pareto_{(nombre_para_guardar or 'edicion').lower().replace(' ','_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
else:
    st.info("Selecciona al menos un descriptor para continuar. Tus frecuencias se conservarán si luego agregas más descriptores.")
# ============================================================================
# 7) PORTAFOLIO, UNIFICADO Y DESCARGAS
# ============================================================================
st.markdown("---")
st.header("📁 Portafolio de Paretos (guardados)")

if not st.session_state["portafolio"]:
    st.info("Aún no hay paretos guardados. Guarda el primero desde la sección anterior.")
else:
    st.subheader("Selecciona paretos para Unificar")
    nombres = sorted(st.session_state["portafolio"].keys())
    sel_unif = st.multiselect("Elige 2 o más paretos para combinar (o usa el botón de 'Unificar todos')",
                              options=nombres, default=[], key="sel_unif")

    c_unif1, c_unif2 = st.columns([1,1])
    with c_unif1: unificar_todos = st.button("🔗 Unificar TODOS los paretos guardados")
    with c_unif2: st.caption(f"Total de paretos guardados: **{len(nombres)}**")

    st.markdown("### Paretos guardados")
    for nom in nombres:
        freq_map = st.session_state["portafolio"][nom]
        meta = info_pareto(freq_map)
        with st.expander(f"🔹 {nom} — {meta['descriptores']} descriptores | Total: {meta['total']}"):
            df_base = df_desde_freq_map(freq_map)
            tabla_g = calcular_pareto(df_base)

            mostrar_g = tabla_g.copy()[["categoria","descriptor","frecuencia","porcentaje","pct_acum","acumulado","segmento"]]
            mostrar_g = mostrar_g.rename(columns={"pct_acum":"porcentaje acumulado"})
            if not mostrar_g.empty:
                mostrar_g["porcentaje"] = mostrar_g["porcentaje"].map(lambda x: f"{x:.2f}%")
                mostrar_g["porcentaje acumulado"] = mostrar_g["porcentaje acumulado"].map(lambda x: f"{x:.2f}%")


            cc1, cc2, cc3 = st.columns([1,1,1])
            with cc1:
                if not mostrar_g.empty:
                    st.dataframe(mostrar_g, use_container_width=True, hide_index=True)
                else:
                    st.info("Este pareto no tiene frecuencias > 0.")
            with cc2:
                st.markdown("**Gráfico**"); dibujar_pareto(tabla_g, f"Pareto — {nom}")
            with cc3:
                st.markdown("**Acciones**")
                if not tabla_g.empty:
                    st.download_button(
                        "⬇️ Excel de este Pareto",
                        data=exportar_excel_con_grafico(tabla_g, f"Pareto — {nom}"),
                        file_name=f"pareto_{nom.lower().replace(' ','_')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{nom}",
                    )
                if st.button("📥 Cargar este Pareto al editor", key=f"load_{nom}"):
                    st.session_state["freq_map"] = dict(freq_map)
                    st.session_state["msel"] = list(freq_map.keys())
                    st.success(f"Pareto '{nom}' cargado al editor (arriba). Desplázate para editar.")
                if st.button("🗑️ Eliminar de la sesión", key=f"del_{nom}"):
                    try:
                        del st.session_state["portafolio"][nom]
                        st.warning(f"Pareto '{nom}' eliminado del portafolio de la sesión.")
                        st.rerun()
                    except Exception:
                        st.error("No se pudo eliminar. Intenta de nuevo.")

    st.markdown("---"); st.header("🔗 Pareto Unificado (por filtro o general)")
    maps_a_unir = []; titulo_unif = ""
    if unificar_todos and nombres:
        maps_a_unir = [st.session_state["portafolio"][n] for n in nombres]
        titulo_unif = "Pareto General (todos los paretos)"
    elif len(st.session_state.get("sel_unif", [])) >= 2:
        maps_a_unir = [st.session_state["portafolio"][n] for n in st.session_state["sel_unif"]]
        titulo_unif = f"Unificado: {', '.join(st.session_state['sel_unif'])}"
    if maps_a_unir:
        combinado = combinar_maps(maps_a_unir)
        df_unif = df_desde_freq_map(combinado)
        tabla_unif = calcular_pareto(df_unif)
        mostrar_u = tabla_unif.copy()[["categoria","descriptor","frecuencia","porcentaje","pct_acum","acumulado","segmento"]]
        mostrar_u = mostrar_u.rename(columns={"pct_acum":"porcentaje acumulado"})
        if not mostrar_u.empty:
            mostrar_u["porcentaje"] = mostrar_u["porcentaje"].map(lambda x: f"{x:.2f}%")
            mostrar_u["porcentaje acumulado"] = mostrar_u["porcentaje acumulado"].map(lambda x: f"{x:.2f}%")
        cu1, cu2 = st.columns([1,1], gap="large")
        with cu1:
            st.markdown("**Tabla Unificada**")
            if not mostrar_u.empty:
                st.dataframe(mostrar_u, use_container_width=True, hide_index=True)
            else:
                st.info("Sin datos > 0 en la combinación seleccionada.")
        with cu2:
            st.markdown("**Gráfico Unificado**"); dibujar_pareto(tabla_unif, titulo_unif or "Pareto Unificado")
        if not tabla_unif.empty:
            st.download_button(
                "⬇️ Descargar Excel del Pareto Unificado",
                data=exportar_excel_con_grafico(tabla_unif, titulo_unif or "Pareto Unificado"),
                file_name="pareto_unificado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_unificado",
            )
    else:
        st.info("Selecciona 2+ paretos en el multiselect o usa el botón 'Unificar TODOS'.")








