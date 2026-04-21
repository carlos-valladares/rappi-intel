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

    # Plataformas con datos reales de envio (excluye UberEats: $0 es promo nuevos usuarios, no precio real)
    plataformas_con_envio_real = ["rappi"]

    # 1. Variabilidad geografica del costo de envio de Rappi por tipo de zona
    # (unica plataforma con datos reales de envio en esta version)
    var_zona = (
        df[df["plataforma"] == "rappi"].groupby("tipo_zona")["costo_envio"].mean()
        if "rappi" in df["plataforma"].values
        else pd.Series()
    )
    var_zona = var_zona.dropna()
    if not var_zona.empty and len(var_zona) > 1:
        zona_max = var_zona.idxmax()
        zona_min = var_zona.idxmin()
        diff = var_zona.max() - var_zona.min()
        insights.append({
            "numero": 1,
            "icono": "💸",
            "hallazgo": f"El costo de envio de Rappi varia {diff:.0f} MXN entre zonas: '{zona_max}' es la mas cara y '{zona_min}' la mas barata",
            "impacto": "La variabilidad geografica de fees puede alejar usuarios en zonas de mayor costo. Dato exclusivo de Rappi: Uber Eats muestra $0 por promo de nuevos usuarios (no es el precio real) y DiDi Food no expone este dato en su sitio web.",
            "recomendacion": f"Verificar si la diferencia refleja mayor distancia de repartidores en '{zona_max}' o es una decision de pricing. Evaluar si un fee mas uniforme mejora la conversion en esa zona.",
        })
    elif "rappi" in df["plataforma"].values:
        fee_rappi = df[df["plataforma"] == "rappi"]["costo_envio"].mean()
        if pd.notna(fee_rappi):
            insights.append({
                "numero": 1,
                "icono": "💸",
                "hallazgo": f"El costo de envio promedio de Rappi en las zonas analizadas es MXN${fee_rappi:.0f}",
                "impacto": "Dato exclusivo de Rappi: Uber Eats muestra $0 por promo de nuevos usuarios y DiDi Food no expone fees en su sitio web. Se requieren credenciales de usuario para obtener el fee real de Uber Eats.",
                "recomendacion": "Ejecutar el scraper con cuenta de usuario normal (--ubereats-email) para comparar fees reales entre plataformas.",
            })

    # 2. Comparacion de ETA — solo Rappi vs Uber Eats (DiDi no tiene datos de ETA)
    df_con_eta = df[df["plataforma"].isin(["rappi", "ubereats"])]
    eta_avg = df_con_eta.groupby("plataforma")["tiempo_entrega_min"].mean().dropna()
    if not eta_avg.empty and "rappi" in eta_avg and "ubereats" in eta_avg:
        diff_min = eta_avg["rappi"] - eta_avg["ubereats"]
        insights.append({
            "numero": 2,
            "icono": "⏱️",
            "hallazgo": f"Rappi tiene ETAs {abs(diff_min):.0f} min {'mas lentos' if diff_min > 0 else 'mas rapidos'} que Uber Eats en promedio ({eta_avg['rappi']:.0f} vs {eta_avg['ubereats']:.0f} min)",
            "impacto": "El tiempo de entrega es el segundo factor de decision tras el precio. Diferencias mayores a 10 min reducen la conversion. DiDi Food no incluido: no expone tiempos de entrega en su sitio web.",
            "recomendacion": f"{'Priorizar densidad de repartidores en las zonas con mayor brecha de ETA vs Uber Eats.' if diff_min > 5 else 'ETAs competitivos — mantener la estrategia de asignacion de repartidores actual.'}",
        })
    elif "rappi" in eta_avg:
        insights.append({
            "numero": 2,
            "icono": "⏱️",
            "hallazgo": f"ETA promedio de Rappi: {eta_avg['rappi']:.0f} min. No se pudo comparar con Uber Eats en esta corrida.",
            "impacto": "Sin datos de ETA de Uber Eats no es posible establecer la brecha competitiva.",
            "recomendacion": "Revisar los logs para identificar por que Uber Eats no capturo datos de tiempo de entrega.",
        })

    # 3. Precios de producto — comparacion Rappi vs Uber Eats por producto
    # (los unicos con precios reales; DiDi no expone precios en web)
    df_precios = df[df["plataforma"].isin(["rappi", "ubereats"])].dropna(subset=["precio_producto", "nombre_producto"])
    if not df_precios.empty:
        productos_comunes = (
            df_precios.groupby("nombre_producto")["plataforma"]
            .nunique()
        )
        productos_comparables = productos_comunes[productos_comunes > 1].index.tolist()

        if productos_comparables:
            producto = productos_comparables[0]
            precios = df_precios[df_precios["nombre_producto"] == producto].groupby("plataforma")["precio_producto"].mean()
            if "rappi" in precios and "ubereats" in precios:
                diff_precio = precios["rappi"] - precios["ubereats"]
                insights.append({
                    "numero": 3,
                    "icono": "🏷️",
                    "hallazgo": f"{producto}: Rappi MXN${precios['rappi']:.0f} vs Uber Eats MXN${precios['ubereats']:.0f} — Rappi es {'MXN$' + str(abs(round(diff_precio))) + ' mas caro' if diff_precio > 0 else 'MXN$' + str(abs(round(diff_precio))) + ' mas barato'}",
                    "impacto": "El precio del producto es la metrica mas directa de competitividad. DiDi Food no incluido: no expone precios de menu en su sitio web.",
                    "recomendacion": f"{'Revisar la politica de precios de producto en Rappi para los items donde Uber Eats es mas barato.' if diff_precio > 5 else 'Precios competitivos — no se requiere ajuste inmediato.'}",
                })
        else:
            # No hay productos comparables entre plataformas — mostrar lo que tiene Rappi
            precio_rappi = df_precios[df_precios["plataforma"] == "rappi"].groupby("nombre_producto")["precio_producto"].mean()
            if not precio_rappi.empty:
                resumen_precios = ", ".join([f"{p}: MXN${v:.0f}" for p, v in precio_rappi.items()])
                insights.append({
                    "numero": 3,
                    "icono": "🏷️",
                    "hallazgo": f"Precios capturados en Rappi: {resumen_precios}",
                    "impacto": "No se encontraron productos comunes entre plataformas para comparar directamente. Uber Eats y Rappi ofrecen diferentes cadenas (McDonald's es exclusivo de Uber Eats; Carl's Jr solo en Rappi).",
                    "recomendacion": "Usar Whopper como producto de referencia comun entre Rappi y Uber Eats para futuras comparaciones.",
                })

    # 4. Agresividad de descuentos — solo Rappi vs Uber Eats
    # (DiDi Food no expone descuentos en su sitio web — excluido para no distorsionar)
    df_desc = df[df["plataforma"].isin(["rappi", "ubereats"])]
    tasa_desc = df_desc.groupby("plataforma")["descuento_activo"].mean() * 100
    if not tasa_desc.empty and "rappi" in tasa_desc and "ubereats" in tasa_desc:
        diff = tasa_desc["ubereats"] - tasa_desc["rappi"]
        insights.append({
            "numero": 4,
            "icono": "🎁",
            "hallazgo": f"Uber Eats tiene descuentos activos en el {tasa_desc['ubereats']:.0f}% de sus tiendas vs {tasa_desc['rappi']:.0f}% en Rappi",
            "impacto": "Las promociones son driver clave de primera compra y reactivacion. DiDi Food excluido de esta comparacion: su sitio web no expone informacion de descuentos activos.",
            "recomendacion": f"{'Uber Eats es mas agresivo en promociones — evaluar aumentar cobertura de descuentos en Rappi para las mismas zonas.' if diff > 10 else 'Rappi es competitivo en promociones respecto a Uber Eats — mantener estrategia actual.'}",
        })

    # 5. Zonas con mayor costo de envio en Rappi (heatmap)
    # Identifica las zonas especificas donde Rappi cobra mas caro — dato accionable por zona
    if "rappi" in df["plataforma"].values:
        envio_por_zona = (
            df[df["plataforma"] == "rappi"]
            .groupby("zona")["costo_envio"]
            .mean()
            .dropna()
            .sort_values(ascending=False)
        )
        if not envio_por_zona.empty:
            zona_mas_cara = envio_por_zona.index[0]
            zona_mas_barata = envio_por_zona.index[-1]
            fee_max = envio_por_zona.iloc[0]
            fee_min = envio_por_zona.iloc[-1]
            n_zonas_sin_dato = df[df["plataforma"] == "rappi"]["zona"].nunique() - len(envio_por_zona)
            insights.append({
                "numero": 5,
                "icono": "🗺️",
                "hallazgo": f"Por zona especifica, Rappi cobra mas caro en '{zona_mas_cara}' (MXN${fee_max:.0f}) y mas barato en '{zona_mas_barata}' (MXN${fee_min:.0f}). {f'Hay {n_zonas_sin_dato} zona(s) sin dato de envio capturado.' if n_zonas_sin_dato > 0 else ''}",
                "impacto": "El heatmap muestra donde Rappi concentra sus fees mas altos a nivel de zona individual. Estas zonas son las de mayor riesgo de perder usuarios frente a competidores con fee menor o gratuito.",
                "recomendacion": f"Investigar si el fee alto en '{zona_mas_cara}' responde a baja densidad de repartidores o es una decision de pricing. Las zonas sin dato en el heatmap requieren revision del scraper para esa ubicacion.",
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
  .aviso-datos {{ background: #fff8e1; border-left: 4px solid #f59e0b; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; font-size: 0.9rem; color: #78350f; }}
  .aviso-datos strong {{ display: block; margin-bottom: 8px; font-size: 1rem; color: #92400e; }}
  .aviso-datos ul {{ padding-left: 18px; line-height: 1.8; }}
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
  <div class="aviso-datos">
    <strong>Limitaciones de los datos en esta version</strong>
    <ul>
      <li><strong>Costo de envio — Uber Eats:</strong> muestra $0 por promo de nuevos usuarios, no el precio real para usuarios recurrentes. Requiere autenticacion con cuenta existente (--ubereats-email).</li>
      <li><strong>Costo de servicio:</strong> no disponible sin login en ninguna plataforma. Rappi retorna 0% y Uber Eats retorna nulo para sesiones sin autenticacion.</li>
      <li><strong>DiDi Food:</strong> su sitio web no expone costo de envio, tiempos de entrega, precios de producto ni descuentos. Solo se capturan nombre de restaurante y calificacion a nivel ciudad-CDMX (no por zona). Las graficas de DiDi reflejan unicamente estos dos datos.</li>
    </ul>
  </div>
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
