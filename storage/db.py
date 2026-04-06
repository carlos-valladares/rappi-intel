"""
Capa de almacenamiento DuckDB.
Consolida los CSVs de todos los scrapers en una base de datos analitica unica.
"""
import logging
from pathlib import Path

import duckdb
import pandas as pd

RUTA_DB = Path("data/raw/competitive_intel.duckdb")
RUTA_DB.parent.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("storage.db")


def obtener_conexion() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(RUTA_DB))


def ingestar_csv(ruta_csv: Path) -> int:
    """Cargar un CSV de scraper en DuckDB. Retorna filas insertadas."""
    con = obtener_conexion()
    try:
        df = pd.read_csv(ruta_csv)
        con.execute("""
            CREATE TABLE IF NOT EXISTS datos_competencia AS
            SELECT * FROM df WHERE 1=0
        """)
        con.execute("INSERT INTO datos_competencia SELECT * FROM df")
        filas = len(df)
        log.info(f"Ingestados {filas} registros de {ruta_csv.name}")
        return filas
    finally:
        con.close()


def ingest_dataframe(df: pd.DataFrame) -> int:
    """Cargar un DataFrame directamente en DuckDB (reemplaza tabla existente)."""
    con = obtener_conexion()
    try:
        con.execute("DROP TABLE IF EXISTS datos_competencia")
        con.execute("CREATE TABLE datos_competencia AS SELECT * FROM df")
        log.info(f"Tabla datos_competencia actualizada: {len(df)} registros")
        return len(df)
    finally:
        con.close()


def consultar(sql: str) -> pd.DataFrame:
    """Ejecutar una consulta SQL y retornar DataFrame."""
    con = obtener_conexion()
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def resumen() -> pd.DataFrame:
    """Vista rapida de los datos ingestados."""
    return consultar("""
        SELECT
            plataforma,
            COUNT(*) as total_registros,
            COUNT(DISTINCT zona) as zonas,
            COUNT(DISTINCT nombre_restaurante) as restaurantes,
            AVG(costo_envio) as costo_envio_promedio,
            AVG(tiempo_entrega_min) as eta_promedio_min,
            SUM(CASE WHEN descuento_activo THEN 1 ELSE 0 END) as con_descuentos,
            COUNT(precio_producto) as con_precio_producto,
            AVG(precio_producto) as precio_producto_promedio
        FROM datos_competencia
        WHERE estado_scraping = 'ok'
        GROUP BY plataforma
        ORDER BY plataforma
    """)


# Alias para compatibilidad con main.py y report.py
def get_connection():
    return obtener_conexion()


def ingest_csv(csv_path: Path) -> int:
    return ingestar_csv(csv_path)


def query(sql: str) -> pd.DataFrame:
    return consultar(sql)


def summary() -> pd.DataFrame:
    return resumen()
