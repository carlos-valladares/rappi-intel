"""
Generador de reporte HTML de Competitive Intelligence.
Lee desde DuckDB, genera graficas y reporte HTML ejecutivo.
Ejecutar: python analysis/report.py
"""
import logging
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from storage.db import query, summary

log = logging.getLogger("analysis.report")
DIRECTORIO_SALIDA = Path("data")
DIRECTORIO_SALIDA.mkdir(exist_ok=True)

COLORES_PLATAFORMA = {
    "rappi": "#FF441F",
    "ubereats": "#06C167",
    "didifood": "#FF6B00",
}


def cargar_datos() -> pd.DataFrame:
    try:
        df = query("SELECT * FROM datos_competencia WHERE estado_scraping = 'ok'")
        log.info(f"Cargados {len(df)} registros desde DuckDB")
        return df
    except Exception as e:
        log.warning(f"DuckDB no disponible, cargando desde CSVs: {e}")
        return _cargar_desde_csvs()


def _cargar_desde_csvs() -> pd.DataFrame:
    csvs = list(Path("data/raw").glob("*.csv"))
    if not csvs:
        log.error("No se encontraron archivos CSV en data/raw/")
        return pd.DataFrame()
    dfs = [pd.read_csv(f) for f in csvs]
    df = pd.concat(dfs, ignore_index=True)
    df = df[df["estado_scraping"] == "ok"] if "estado_scraping" in df.columns else df
    return df


# ── Graficas ──────────────────────────────────────────────────────────────────

def grafica_costo_envio(df: pd.DataFrame) -> go.Figure:
    """Barras: costo de envio promedio por plataforma."""
    promedio = (
        df.groupby("plataforma")["costo_envio"]
        .mean()
        .reset_index()
        .rename(columns={"costo_envio": "costo_envio_promedio"})
    )
    fig = px.bar(
        promedio,
        x="plataforma",
        y="costo_envio_promedio",
        color="plataforma",
        color_discrete_map=COLORES_PLATAFORMA,
        title="Costo de Envio Promedio por Plataforma (MXN)",
        labels={"costo_envio_promedio": "Costo Envio Promedio (MXN)", "plataforma": "Plataforma"},
        text_auto=".0f",
    )
    fig.update_layout(showlegend=False)
    return fig


def grafica_eta(df: pd.DataFrame) -> go.Figure:
    """Box plot: distribucion de tiempo de entrega por plataforma."""
    fig = px.box(
        df.dropna(subset=["tiempo_entrega_min"]),
        x="plataforma",
        y="tiempo_entrega_min",
        color="plataforma",
        color_discrete_map=COLORES_PLATAFORMA,
        title="Tiempo de Entrega por Plataforma (minutos)",
        labels={"tiempo_entrega_min": "Tiempo Estimado (min)", "plataforma": "Plataforma"},
    )
    fig.update_layout(showlegend=False)
    return fig


def grafica_envio_por_zona(df: pd.DataFrame) -> go.Figure:
    """Heatmap: costo de envio por zona y plataforma."""
    pivot = (
        df.groupby(["zona", "plataforma"])["costo_envio"]
        .mean()
        .unstack("plataforma")
        .round(1)
    )
    fig = px.imshow(
        pivot,
        title="Costo de Envio por Zona y Plataforma (MXN)",
        color_continuous_scale="RdYlGn_r",
        aspect="auto",
        labels={"color": "Costo Envio (MXN)"},
    )
    fig.update_xaxes(title="Plataforma")
    fig.update_yaxes(title="Zona")
    return fig


def grafica_tasa_descuentos(df: pd.DataFrame) -> go.Figure:
    """Barras: % de tiendas con descuentos activos por plataforma."""
    tasa = (
        df.groupby("plataforma")
        .apply(lambda x: (x["descuento_activo"].sum() / len(x)) * 100)
        .reset_index(name="tasa_descuento")
    )
    fig = px.bar(
        tasa,
        x="plataforma",
        y="tasa_descuento",
        color="plataforma",
        color_discrete_map=COLORES_PLATAFORMA,
        title="Tasa de Descuentos Activos por Plataforma (%)",
        labels={"tasa_descuento": "% Con Descuento", "plataforma": "Plataforma"},
        text_auto=".1f",
    )
    fig.update_layout(showlegend=False)
    return fig


def grafica_envio_por_tipo_zona(df: pd.DataFrame) -> go.Figure:
    """Barras agrupadas: costo de envio por tipo de zona."""
    promedio = (
        df.groupby(["tipo_zona", "plataforma"])["costo_envio"]
        .mean()
        .reset_index()
        .rename(columns={"costo_envio": "costo_promedio"})
    )
    fig = px.bar(
        promedio,
        x="tipo_zona",
        y="costo_promedio",
        color="plataforma",
        barmode="group",
        color_discrete_map=COLORES_PLATAFORMA,
        title="Costo de Envio por Tipo de Zona (MXN)",
        labels={"costo_promedio": "Costo Promedio (MXN)", "tipo_zona": "Tipo de Zona"},
        text_auto=".0f",
    )
    return fig


def grafica_precios_producto(df: pd.DataFrame) -> go.Figure:
    """Barras: precio del producto objetivo por plataforma y restaurante."""
    df_prod = df.dropna(subset=["precio_producto", "nombre_producto"])
    if df_prod.empty:
        fig = go.Figure()
        fig.update_layout(title="Precio de Productos Objetivo (sin datos disponibles)")
        return fig
    promedio = (
        df_prod.groupby(["plataforma", "nombre_producto"])["precio_producto"]
        .mean()
        .reset_index()
        .rename(columns={"precio_producto": "precio_promedio"})
    )
    fig = px.bar(
        promedio,
        x="nombre_producto",
        y="precio_promedio",
        color="plataforma",
        barmode="group",
        color_discrete_map=COLORES_PLATAFORMA,
        title="Precio de Productos Objetivo por Plataforma (MXN)",
        labels={"precio_promedio": "Precio Promedio (MXN)", "nombre_producto": "Producto"},
        text_auto=".0f",
    )
    return fig


# ── Insights ──────────────────────────────────────────────────────────────────

def generar_insights(df: pd.DataFrame) -> list[dict]:
    """Calcular top 5 insights estrategicos desde los datos."""
    insights = []

    # 1. Comparacion de costo de envio
    fee_avg = df.groupby("plataforma")["costo_envio"].mean()
    if not fee_avg.empty and "rappi" in fee_avg and len(fee_avg) > 1:
        competidores = {k: v for k, v in fee_avg.items() if k != "rappi"}
        mejor_comp = min(competidores, key=competidores.get)
        diff = ((fee_avg["rappi"] - competidores[mejor_comp]) / competidores[mejor_comp]) * 100
        insights.append({
            "numero": 1,
            "icono": "💸",
            "hallazgo": f"El costo de envio de Rappi es {abs(diff):.0f}% {'mas caro' if diff > 0 else 'mas barato'} que {mejor_comp.title()} en promedio",
            "impacto": "El costo de envio es la metrica mas visible al elegir plataforma. Diferencias >20% afectan la conversion.",
            "recomendacion": f"{'Revisar estructura de fees en zonas de alta competencia.' if diff > 15 else 'Mantener pricing actual — ventaja competitiva en fees.'}",
        })

    # 2. Comparacion de ETA
    eta_avg = df.groupby("plataforma")["tiempo_entrega_min"].mean()
    if not eta_avg.empty and "rappi" in eta_avg and len(eta_avg) > 1:
        comp_eta = {k: v for k, v in eta_avg.items() if k != "rappi"}
        mejor_eta = min(comp_eta, key=comp_eta.get)
        diff_min = eta_avg["rappi"] - comp_eta[mejor_eta]
        insights.append({
            "numero": 2,
            "icono": "⏱️",
            "hallazgo": f"Rappi tiene ETAs {abs(diff_min):.0f} min {'mas lentos' if diff_min > 0 else 'mas rapidos'} que {mejor_eta.title()}",
            "impacto": "El tiempo de entrega es el segundo factor de decision. Diferencias >10 min reducen conversion.",
            "recomendacion": "Revisar densidad de repartidores en zonas con mayor desventaja de tiempo.",
        })

    # 3. Variabilidad geografica
    var_zona = (
        df[df["plataforma"] == "rappi"].groupby("tipo_zona")["costo_envio"].mean()
        if "rappi" in df["plataforma"].values
        else pd.Series()
    )
    if not var_zona.empty and len(var_zona) > 1:
        zona_max = var_zona.idxmax()
        zona_min = var_zona.idxmin()
        diff = var_zona.max() - var_zona.min()
        insights.append({
            "numero": 3,
            "icono": "🗺️",
            "hallazgo": f"Rappi cobra {diff:.0f} MXN mas de envio en '{zona_max}' vs '{zona_min}'",
            "impacto": "Alta variabilidad geografica puede alejar usuarios en zonas perifericas.",
            "recomendacion": f"Investigar densidad de repartidores en '{zona_max}'. Evaluar ajuste de precios por zona.",
        })

    # 4. Agresividad de descuentos
    tasa_desc = df.groupby("plataforma")["descuento_activo"].mean() * 100
    if not tasa_desc.empty and "rappi" in tasa_desc and len(tasa_desc) > 1:
        comp_max_desc = tasa_desc.drop("rappi").idxmax()
        diff = tasa_desc[comp_max_desc] - tasa_desc["rappi"]
        insights.append({
            "numero": 4,
            "icono": "🎁",
            "hallazgo": f"{comp_max_desc.title()} tiene {abs(diff):.0f}% {'mas' if diff > 0 else 'menos'} descuentos activos que Rappi",
            "impacto": "Las promociones son driver clave de primera compra y reactivacion.",
            "recomendacion": f"{'Aumentar cobertura de promociones donde el competidor es mas agresivo.' if diff > 10 else 'Rappi lidera en promociones — mantener estrategia.'}",
        })

    # 5. Disponibilidad
    disponibilidad = df.groupby("plataforma")["restaurante_disponible"].mean() * 100
    if not disponibilidad.empty and "rappi" in disponibilidad and len(disponibilidad) > 1:
        comp_disp = {k: v for k, v in disponibilidad.items() if k != "rappi"}
        insights.append({
            "numero": 5,
            "icono": "🏪",
            "hallazgo": f"Disponibilidad Rappi: {disponibilidad.get('rappi', 0):.0f}% vs competencia promedio: {sum(comp_disp.values())/len(comp_disp):.0f}%",
            "impacto": "Mas restaurantes disponibles = mayor probabilidad de conversion en cualquier horario.",
            "recomendacion": "Priorizar acuerdos con restaurantes en zonas donde la cobertura es inferior a competencia.",
        })

    if not insights:
        insights = [{
            "numero": 1,
            "icono": "⚠️",
            "hallazgo": "Datos insuficientes para generar insights automaticos",
            "impacto": "Se requieren mas datos scrapeados",
            "recomendacion": "Ejecutar el scraper con mas direcciones o revisar los logs de errores",
        }]

    return insights


# ── Reporte HTML ──────────────────────────────────────────────────────────────

def generate_html_report(df: pd.DataFrame) -> Path:
    """Genera un reporte HTML ejecutivo auto-contenido."""

    graficas_html = ""
    funciones_graficas = [
        grafica_costo_envio,
        grafica_eta,
        grafica_envio_por_zona,
        grafica_tasa_descuentos,
        grafica_envio_por_tipo_zona,
        grafica_precios_producto,
    ]
    for fn in funciones_graficas:
        try:
            fig = fn(df)
            graficas_html += fig.to_html(full_html=False, include_plotlyjs=False)
        except Exception as e:
            log.warning(f"Graficas {fn.__name__} fallo: {e}")

    insights = generar_insights(df)
    insights_html = ""
    for ins in insights:
        insights_html += f"""
        <div class="insight-card">
            <div class="insight-numero">{ins['icono']} Insight {ins['numero']}</div>
            <div class="insight-hallazgo"><strong>Hallazgo:</strong> {ins['hallazgo']}</div>
            <div class="insight-impacto"><strong>Impacto:</strong> {ins['impacto']}</div>
            <div class="insight-rec"><strong>Recomendacion:</strong> {ins['recomendacion']}</div>
        </div>
        """

    try:
        stats = summary()
        stats_html = stats.to_html(classes="tabla-resumen", index=False, float_format=lambda x: f"{x:.1f}")
    except Exception:
        stats_html = "<p>Resumen no disponible</p>"

    from datetime import datetime
    fecha_reporte = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    n_registros = len(df)
    n_zonas = df["zona"].nunique() if "zona" in df.columns else 0
    plataformas = ", ".join(df["plataforma"].unique().tolist()) if "plataforma" in df.columns else "N/A"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappi Competitive Intelligence Report</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8f9fa; color: #212529; }}
  .header {{ background: linear-gradient(135deg, #FF441F 0%, #ff6b4a 100%); color: white; padding: 40px 60px; }}
  .header h1 {{ font-size: 2rem; font-weight: 700; }}
  .header p {{ opacity: 0.85; margin-top: 8px; }}
  .meta {{ display: flex; gap: 40px; margin-top: 20px; }}
  .meta-item {{ font-size: 0.9rem; opacity: 0.9; }}
  .meta-item strong {{ display: block; font-size: 1.4rem; }}
  .seccion {{ padding: 40px 60px; }}
  .seccion h2 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 24px; color: #343a40; border-left: 4px solid #FF441F; padding-left: 12px; }}
  .grid-graficas {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .tarjeta-grafica {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .tarjeta-grafica.ancho-completo {{ grid-column: 1 / -1; }}
  .grid-insights {{ display: grid; gap: 16px; }}
  .insight-card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-left: 4px solid #FF441F; }}
  .insight-numero {{ font-size: 1.1rem; font-weight: 700; color: #FF441F; margin-bottom: 12px; }}
  .insight-hallazgo {{ margin-bottom: 8px; }}
  .insight-impacto {{ margin-bottom: 8px; color: #495057; }}
  .insight-rec {{ background: #fff3f0; padding: 10px 14px; border-radius: 8px; color: #c0392b; font-size: 0.95rem; }}
  .tabla-resumen {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .tabla-resumen th {{ background: #FF441F; color: white; padding: 12px 16px; text-align: left; }}
  .tabla-resumen td {{ padding: 10px 16px; border-bottom: 1px solid #e9ecef; }}
  .footer {{ background: #343a40; color: #adb5bd; padding: 24px 60px; font-size: 0.85rem; }}
</style>
</head>
<body>

<div class="header">
  <h1>Rappi Competitive Intelligence</h1>
  <p>Analisis comparativo: Rappi vs Uber Eats vs DiDi Food — CDMX</p>
  <div class="meta">
    <div class="meta-item"><strong>{n_registros}</strong>registros recolectados</div>
    <div class="meta-item"><strong>{n_zonas}</strong>zonas cubiertas</div>
    <div class="meta-item"><strong>{plataformas}</strong>plataformas</div>
    <div class="meta-item"><strong>{fecha_reporte}</strong>fecha de generacion</div>
  </div>
</div>

<div class="seccion">
  <h2>Resumen Ejecutivo</h2>
  {stats_html}
</div>

<div class="seccion">
  <h2>Analisis Comparativo</h2>
  <div class="grid-graficas">
    {graficas_html}
  </div>
</div>

<div class="seccion">
  <h2>Top {len(insights)} Insights Accionables</h2>
  <div class="grid-insights">
    {insights_html}
  </div>
</div>

<div class="footer">
  <p>Rappi Competitive Intelligence System — Generado automaticamente. Para uso interno del equipo de Strategy & Pricing.</p>
</div>

</body>
</html>"""

    ruta_salida = DIRECTORIO_SALIDA / "report.html"
    ruta_salida.write_text(html, encoding="utf-8")
    log.info(f"Reporte guardado -> {ruta_salida}")
    return ruta_salida


# Alias para compatibilidad con main.py
def load_data() -> pd.DataFrame:
    return cargar_datos()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    df = cargar_datos()
    if df.empty:
        print("Sin datos. Ejecutar primero: python main.py")
    else:
        ruta = generate_html_report(df)
        print(f"Reporte generado: {ruta}")
