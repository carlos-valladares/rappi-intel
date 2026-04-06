# Flujo de Datos

## Flujo General

```
config/addresses.json (25 zonas)
        │
        ▼
  main.py --platform X --addresses N
        │
        ├── RappiScraper.run(direcciones)
        ├── UberEatsScraper.run(direcciones)
        └── DidiScraper.run(direcciones)
                │
                ▼
        Por cada dirección:
          scrape_address(direccion, contexto)
                │
                ▼
          Lista de registros estandarizados
          [_registro_base() × n_restaurantes]
                │
                ├── save_csv()   → data/raw/{plataforma}_{ts}.csv
                └── save_intercepted() → data/raw/{plataforma}_raw_{ts}.json
                │
                ▼
        ingest_dataframe(df)
          → DuckDB: datos_competencia
                │
                ▼
        generate_html_report(df)
          → data/report.html
```

## Flujo Detallado por Plataforma

### Rappi

```
1. Browser → rappi.com.mx
2. Intercepta POST /api/rocket/v2/guest → { access_token } (token guest)
3. Intercepta GET catalog-paged/home → { stores[] }
4. _parsear_interceptadas():
      Para cada store con brand_name en RESTAURANTES_OBJETIVO
      (Burger King, Carl's Jr, OXXO, 7-Eleven — NO McDonald's):
        → registro con delivery_price, eta, rating, descuentos, store_id
5. _extraer_token() → self._bearer_token
6. _enriquecer_precios_producto():
      Para cada registro:
        cache? → usar cache
        no cache → POST /store/id/{store_id}/
                     body: {lat, lng, store_type, is_prime}
                   → percentage_service_fee, corridors[].products[]
                   → min(precios que coinciden) = precio standalone
```

### Uber Eats

```
1. Browser → ubereats.com/mx
2. Configura dirección de entrega (input + sugerencia)
3. Scroll → activa getFeedV1
4. Intercepta getFeedV1 → { feedItems[].carousel.stores[] }
5. _parsear_feed():
      Para cada store con title.text en RESTAURANTES_OBJETIVO:
        → registro con ETA, rating, descuentos, actionUrl, storeUuid
6. _enriquecer_tiendas():
      Para cada registro:
        a) POST /_p/api/getStoreV1 {storeUuid}
           → fareInfo.serviceFeeCents → costo_servicio
           → catalogSectionsMap → precio en centavos / 100
        b) GET {actionUrl} (página tienda)
           → HTML: "MXN{N} delivery fee" → costo_envio
```

### DiDi Food

```
Primera dirección de la corrida (_cache_ciudad = None):
  1. Browser → web.didiglobal.com/mx/food/.../hamburguesas/
  2. Scroll para lazy-load
  3. inner_text(body) → líneas de texto SSR
  4. _parsear_lineas_restaurante():
        Para cada línea con keyword en RESTAURANTES_OBJETIVO:
          → nombre_restaurante, rating (siguiente número decimal)
  5. Guarda resultados en _cache_ciudad (nivel clase)
  6. _asignar_direccion() → registros de la primera dirección
     costo_envio/servicio/tiempo/precio = None (app only)

Direcciones posteriores (_cache_ciudad poblado):
  → return [] inmediato (datos ya capturados, no duplicar)

Resultado: 1 scraping por corrida — ~18 registros únicos (no 25 × 18).
```

## Esquema de la Base de Datos

```sql
CREATE TABLE datos_competencia (
    marca_tiempo         TIMESTAMP,
    plataforma           VARCHAR,      -- 'rappi' | 'ubereats' | 'didifood'
    id_direccion         INTEGER,
    zona                 VARCHAR,
    tipo_zona            VARCHAR,      -- 'premium' | 'residencial' | 'popular' | 'comercial'
    direccion            VARCHAR,
    lat                  DOUBLE,
    lng                  DOUBLE,
    nombre_restaurante   VARCHAR,
    vertical             VARCHAR,      -- 'fast_food' | 'retail'
    nombre_producto      VARCHAR,      -- 'Big Mac' | 'Whopper' | 'Coca-Cola'
    precio_producto      DOUBLE,       -- MXN, NULL si no disponible
    costo_envio          DOUBLE,       -- MXN, 0 = promo nuevos usuarios
    costo_servicio       DOUBLE,       -- MXN o %, NULL sin login
    tiempo_entrega_min   INTEGER,      -- minutos
    tiempo_entrega_max   INTEGER,
    descuento_activo     BOOLEAN,
    descripcion_descuento VARCHAR,
    restaurante_disponible BOOLEAN,
    calificacion         DOUBLE,       -- 0.0 - 5.0
    estado_scraping      VARCHAR,      -- 'ok' | 'error' | 'sin_datos' | 'fallido'
    mensaje_error        VARCHAR
);
```

## Archivos de Salida

| Archivo | Contenido | Cuándo se crea |
|---------|-----------|----------------|
| `data/raw/{plataforma}_{ts}.csv` | Registros normalizados | Por cada ejecución de plataforma |
| `data/raw/{plataforma}_raw_{ts}.json` | Respuestas API crudas interceptadas | Por cada ejecución |
| `data/competitive_intel.duckdb` | Tabla `datos_competencia` acumulada | Persiste entre ejecuciones |
| `data/report.html` | Dashboard HTML con gráficas Plotly | Al final de cada ejecución |
| `data/scraper.log` | Log detallado con timestamps | Modo append, persiste |
