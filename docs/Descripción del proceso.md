# Descripción del Proceso — Rappi Competitive Intelligence System

Documento de análisis técnico paso a paso del código. Objetivo: identificar qué hace cada parte y detectar posibles ajustes necesarios para que el sistema funcione correctamente.

---

## Visión General

El sistema extrae datos de precios, costos de envío, tiempos de entrega y descuentos de tres plataformas de delivery (Rappi, Uber Eats, DiDi Food) en 25 zonas de CDMX, los almacena en una base de datos y genera un reporte HTML con gráficas e insights comparativos.

**Flujo de alto nivel:**
```
main.py
  └── Carga direcciones (config/addresses.json)
  └── Para cada plataforma:
        └── ScraperBase → scrape_address() por cada dirección
              └── Playwright abre browser (modo stealth)
              └── Navega y extrae datos
              └── Guarda CSV + JSON raw
  └── Consolida en DuckDB (storage/db.py)
  └── Genera reporte HTML (analysis/report.py)
```

---

## PASO 1 — Inicio del programa (`main.py`)

**Cómo ejecutar:**
```bash
python main.py                         # Corre todo: 3 plataformas, 25 zonas
python main.py --platform ubereats     # Solo una plataforma
python main.py --addresses 5           # Limitar a las primeras N zonas
python main.py --headless false        # Mostrar el browser (útil para debug)
python main.py --report-only           # Solo regenerar el reporte sin hacer scraping
```

**Lo que hace `main.py`:**
1. Parsea argumentos de línea de comando (plataforma, límite de direcciones, modo headless, credenciales)
2. Muestra banner de bienvenida
3. Carga las direcciones desde `config/addresses.json` (25 en total, o las primeras N si se pasa `--addresses`)
4. Determina qué plataformas correr (todas por defecto, o una sola con `--platform`)
5. Intenta cargar una URL de proxy desde el archivo `.env` (variable `PROXY_URL`)
6. Resuelve credenciales de usuario por plataforma (prioridad: credencial específica → credencial global → sin credenciales)
7. Para cada plataforma, llama a `run_scraper()` de forma secuencial (no paralela)
8. Si no se obtuvo ningún dato, termina con error
9. Consolida todos los registros en DuckDB
10. Imprime tabla de resumen en consola
11. Genera el reporte HTML
12. Muestra tiempo total transcurrido

**⚠️ Punto a revisar:** Los scrapers corren secuencialmente (un plataforma tras otra). Esto significa que si hay 3 plataformas × 25 zonas, el tiempo total puede ser considerable. No hay paralelismo entre plataformas.

---

## PASO 2 — Configuración de zonas (`config/addresses.json`)

Contiene 25 direcciones de CDMX y área metropolitana, organizadas en 5 tipos de zona:

| Tipo de zona           | Zonas incluidas                                              |
|------------------------|--------------------------------------------------------------|
| `alto_poder_adquisitivo` | Polanco (×2), Lomas, Santa Fe, Interlomas                  |
| `clase_media_alta`     | Roma Norte, Condesa, Narvarte, Del Valle, Coyoacán           |
| `centro_mixto`         | Centro Histórico, Doctores, Tepito, Tlatelolco, Peralvillo   |
| `periferia`            | Iztapalapa Centro, Iztapalapa Sur, Ecatepec, Chimalhuacán, Nezahualcóyotl |
| `sur`                  | Tlalpan, Xochimilco, Pedregal, Contreras, Tláhuac            |

Cada entrada tiene: `id`, `zone`, `zone_type`, `address`, `lat`, `lng`, `notes`.

---

## PASO 3 — Configuración de productos objetivo (`config/products.json`)

Define los productos que se buscarán en los menús:

- **Fast food:** Big Mac, Combo Mediano McDonald's, McNuggets 10 pzas, Whopper, Combo Whopper
- **Retail:** Coca-Cola 500ml, Agua 1L, Pañales Pampers
- **Restaurantes objetivo:** McDonald's, Burger King, OXXO, 7-Eleven

**⚠️ Punto a revisar:** Este archivo existe y tiene datos bien estructurados, pero **el código en `scrapers/base.py` define su propio diccionario `PRODUCTOS_OBJETIVO`** de forma independiente (hardcodeado), sin leer este JSON. El archivo `config/products.json` **no está siendo utilizado por ningún scraper**. Hay duplicación de configuración desincronizada.

---

## PASO 4 — Clase base de scraping (`scrapers/base.py`)

Todos los scrapers heredan de `ScraperBase`. Esta clase provee:

### 4.1 — Construcción del browser (método `_construir_contexto`)
- Lanza Chromium en modo headless (o visible con `--headless false`)
- Aplica argumentos anti-detección: `--disable-blink-features=AutomationControlled`, `--no-sandbox`, etc.
- Configura proxy si se pasó `PROXY_URL`
- Selecciona un User-Agent aleatorio de 4 opciones (Windows, Mac, Linux, Firefox)
- Simula locale `es-MX`, timezone `America/Mexico_City`
- Aplica script de **stealth**: sobreescribe `navigator.webdriver`, `navigator.plugins`, `navigator.languages`, y agrega `window.chrome` para evitar detección de bot

### 4.2 — Geolocalización (`_establecer_geolocalizacion`)
- Establece latitud y longitud del browser para que las plataformas sirvan contenido de la zona correcta
- Otorga permiso de geolocalización al contexto

### 4.3 — Rate limiting y comportamiento humano
- `_espera_aleatoria()`: pausa entre 2 y 5 segundos entre requests
- `_scroll_humano()`: hace scroll aleatorio (300–700 px) varias veces para simular usuario real y activar lazy loading

### 4.4 — Intercepción de red (`_configurar_intercepcion`)
- Escucha todas las respuestas HTTP del browser
- Filtra por patrones de URL específicos de cada plataforma
- Captura el cuerpo JSON de respuestas de API interceptadas en `self._interceptadas`
- Esto permite obtener datos estructurados directamente de las APIs internas sin necesidad de parsear HTML

### 4.5 — Registro base (`_registro_base`)
Cada registro tiene estos campos estandarizados:
```
marca_tiempo, plataforma, id_direccion, zona, tipo_zona, direccion, lat, lng,
nombre_restaurante, vertical, nombre_producto, precio_producto,
costo_envio, costo_servicio, tiempo_entrega_min, tiempo_entrega_max,
descuento_activo, descripcion_descuento, restaurante_disponible,
calificacion, estado_scraping, mensaje_error
```

### 4.6 — Reintentos automáticos (`_scrape_con_reintento`)
- Hasta 3 intentos por dirección
- Espera exponencial entre intentos: mín 4s, máx 30s, multiplicador ×2
- Si falla después de 3 intentos, registra el error y continúa con la siguiente dirección

### 4.7 — Persistencia
- `save_csv()`: guarda resultados en `data/raw/{plataforma}_{timestamp}.csv`
- `save_intercepted()`: guarda las respuestas API capturadas en `data/raw/{plataforma}_raw_{timestamp}.json`

---

## PASO 5 — Scraper de Uber Eats (`scrapers/ubereats.py`)

**Restaurantes objetivo:** McDonald's, Burger King, OXXO, 7-Eleven

### 5.1 — Por cada dirección (`scrape_address`)
1. Limpia capturas anteriores
2. Abre nueva página
3. Establece geolocalización
4. Configura intercepción (filtra URLs de `ubereats.com` y `uber.com`)
5. Navega a `https://www.ubereats.com/mx`
6. Espera 6 segundos para que cargue el feed
7. Llama a `_raspar_con_direccion()`
8. Guarda JSON interceptado
9. Cierra la página

### 5.2 — Ingreso de dirección (`_raspar_con_direccion`)
- Busca el botón de dirección en la UI (varios selectores: `data-testid="address-display"`, botones con texto "¿A dónde", "Entrega", inputs)
- Si lo encuentra: hace click, llena el campo con la dirección (primeros 60 caracteres), espera 2.5s, selecciona la primera sugerencia, espera 4s
- Hace scroll humano (5 scrolls)
- Espera 5s adicionales

### 5.3 — Extracción de datos del feed
**Estrategia primaria — API interceptada (`_parsear_feed`):**
- Busca capturas que contengan `getFeedV1` en la URL
- Navega por `data.feedItems[].carousel.stores[]`
- Por cada tienda que coincida con un restaurante objetivo:
  - Extrae nombre, ETA (min/max desde `accessibilityText`), descuentos activos, calificación
  - Guarda temporalmente `_action_url` y `_store_uuid`

**Estrategia fallback — HTML (`_parsear_html_feed`):**
- Si no hay capturas API, busca tarjetas de tienda en el DOM con selectores como `[data-testid="store-card"]`
- Extrae nombre, ETA desde el HTML

### 5.4 — Enriquecimiento de datos por tienda (`_enriquecer_tiendas`)
Para cada tienda encontrada:

**Sub-paso A — API `getStoreV1`:**
- Llama a `POST https://www.ubereats.com/_p/api/getStoreV1?localeCode=mx` con el `storeUuid`
- Extrae `fareInfo.serviceFeeCents` → `costo_servicio` (requiere login; es `null` sin autenticación)
- Extrae precio del producto objetivo desde `catalogSectionsMap` (en centavos, divide entre 100)
- Usa caché en memoria por nombre de restaurante para no llamar la API dos veces al mismo restaurante

**Sub-paso B — Página de tienda:**
- Navega a la URL de la tienda
- Espera 5s + scroll + 3s
- Busca `costo_envio` en APIs interceptadas durante la carga de la página (`fareInfo`)
- Fallback HTML: regex `MXN\s*(\d+) delivery fee` o patrones en español

**Limitaciones conocidas documentadas:**
- Costo de envío = $0 para nuevos usuarios (promo de onboarding, no el precio real)
- `costo_servicio` es `null` sin autenticación

**⚠️ Punto a revisar:** El código tiene comentado el bloque de login (`_login_ubereats`). Sin credenciales, `costo_servicio` siempre será `null` y `costo_envio` puede ser $0 por la promo de nuevos usuarios.

---

## PASO 6 — Scraper de DiDi Food (`scrapers/didifood.py`)

**Restaurantes objetivo:** McDonald's, Burger King, OXXO, 7-Eleven

### 6.1 — Estrategia especial: una sola ejecución por corrida
DiDi Food no tiene datos por zona en su web. El catálogo es a nivel ciudad (CDMX). Por esto:
- La primera dirección ejecuta el scraping completo
- Las 24 direcciones restantes retornan lista vacía (los datos ya están)
- Esto evita 24 scrapes duplicados del mismo catálogo

### 6.2 — Flujo de scraping
1. Si ya se ejecutó en esta corrida (`_cache_ciudad` no es `None`): retorna `[]`
2. Si hay credenciales: registra que el login automático aún no está implementado
3. Navega a 2 URLs de categoría:
   - `https://web.didiglobal.com/mx/food/ciudad-de-mexico-cdmx/categoria/hamburguesas/`
   - `https://web.didiglobal.com/mx/food/ciudad-de-mexico-cdmx/categoria/abarrotes/`
4. Por cada URL: espera carga, hace scroll (8×700px), lee el texto del body completo
5. Parsea las líneas del SSR buscando nombres de restaurantes objetivo y el rating (número entre líneas)
6. Deduplica por nombre de restaurante
7. Asigna los datos a la primera dirección procesada

### 6.3 — Limitaciones conocidas
- **No hay datos de costo de envío** → requiere API de la app móvil (usa `wsgsig`)
- **No hay tiempos de entrega** → ídem
- **No hay precios de productos** → la web no tiene páginas individuales de menú
- **No hay datos por zona** → el catálogo es ciudad-CDMX únicamente
- Los links de restaurante en la web abren la app móvil, no una página web con menú

**⚠️ Punto a revisar:** Los datos de DiDi serán mayoritariamente `null` excepto nombre y rating. Esto limita mucho la utilidad comparativa de DiDi en el reporte.

---

## PASO 7 — Scraper de Rappi (`scrapers/rappi.py`)

**Restaurantes objetivo:** Burger King, Carl's Jr, OXXO, 7-Eleven

### 7.1 — Por cada dirección (`scrape_address`)
1. Limpia capturas e historial de cookies del contexto
2. Establece geolocalización
3. Configura intercepción (filtra `catalog-paged`, `restaurant-bus/stores`, `mxgrability.rappi.com`)
4. Si hay credenciales: ejecuta `_login_rappi()` (login por API antes de cargar la web)
5. Navega a `https://www.rappi.com.mx`
6. Espera 8 segundos

### 7.2 — Login por API (`_login_rappi`)
- `POST https://services.mxgrability.rappi.com/api/rocket/v2/login`
- Body: `{"email": ..., "password": ..., "type": "email"}`
- Extrae `access_token` de la respuesta
- El token autenticado sobreescribe el token guest para que `percentage_service_fee` retorne el valor real (en lugar de 0)

### 7.3 — Ingreso de dirección
- Busca campo de input de dirección con varios selectores
- Llena con la dirección, espera sugerencias, selecciona la primera

### 7.4 — Extracción desde API interceptada (`_parsear_interceptadas`)
- Busca capturas que contengan datos de tiendas
- Extrae por tienda: nombre (`brand_name`/`name`), disponibilidad (`status == "OPEN"`), `delivery_price` → `costo_envio`, ETA desde `etas[0].{min,max}`, calificación, descuentos desde `global_offers.tags`
- Guarda temporalmente `_store_id` y `_store_slug` para el enriquecimiento

### 7.5 — Extracción del token guest
- Busca en las capturas interceptadas un campo `access_token` para llamadas API subsecuentes

### 7.6 — Enriquecimiento de precios (`_enriquecer_precios_producto`)
- `POST https://services.mxgrability.rappi.com/api/web-gateway/web/restaurants-bus/store/id/{store_id}/`
- Requiere el bearer token (guest o autenticado)
- Body: `{"lat": ..., "lng": ..., "store_type": "restaurant", ...}`
- Extrae `percentage_service_fee` del top-level (es 0 sin login, valor real con login)
- Busca el precio del producto objetivo en `corridors[].products[]`, retorna el precio más bajo
- Usa caché en memoria `{store_id}:{producto}` para no llamar dos veces al mismo store+producto

**⚠️ Punto a revisar:** El `costo_servicio` de Rappi se almacena como **porcentaje** (ej. 10.0 = 10%), mientras que el de Uber Eats se almacena como **monto en MXN**. Esto hace que los valores de `costo_servicio` sean incomparables directamente entre plataformas en el reporte.

---

## PASO 8 — Almacenamiento en DuckDB (`storage/db.py`)

1. `ingest_dataframe(df)`:
   - Abre (o crea) `data/raw/competitive_intel.duckdb`
   - **Elimina** la tabla `datos_competencia` si existe (no acumula — reemplaza en cada corrida)
   - Crea nueva tabla con todos los registros del DataFrame

2. `summary()`: consulta SQL que retorna por plataforma: total registros, zonas, restaurantes únicos, promedio de costo de envío, ETA promedio, registros con descuento, registros con precio de producto, precio promedio.

**⚠️ Punto a revisar:** `DROP TABLE IF EXISTS` antes de insertar significa que **cada corrida borra los datos históricos**. No hay acumulación de datos en el tiempo. Si se quiere análisis histórico (comparar semana a semana), esto necesita cambiar.

---

## PASO 9 — Generación del reporte HTML (`analysis/report.py`)

### 9.1 — Carga de datos
- Intenta cargar desde DuckDB (`SELECT * FROM datos_competencia WHERE estado_scraping = 'ok'`)
- Fallback: si DuckDB no está disponible, carga y concatena todos los `.csv` de `data/raw/`

### 9.2 — Gráficas generadas (con Plotly)
1. **Costo de envío promedio por plataforma** — barras
2. **Tiempo de entrega por plataforma** — box plot (distribución)
3. **Costo de envío por zona y plataforma** — heatmap
4. **Tasa de descuentos activos por plataforma** — barras (% de tiendas con promo)
5. **Costo de envío por tipo de zona** — barras agrupadas
6. **Precio de productos objetivo por plataforma** — barras agrupadas

### 9.3 — Insights automáticos (`generar_insights`)
Genera hasta 5 insights estratégicos comparando Rappi vs competencia:
1. Diferencia de costo de envío (Rappi vs competidor más barato)
2. Diferencia de ETA (Rappi vs competidor más rápido)
3. Variabilidad geográfica de precios de envío en Rappi
4. Agresividad de descuentos (Rappi vs competidor con más promos)
5. Disponibilidad de restaurantes (% de abiertos)

Cada insight tiene: hallazgo, impacto en el negocio, y recomendación.

### 9.4 — Reporte HTML auto-contenido
- Se genera en `data/report.html`
- Incluye la librería Plotly desde CDN (requiere internet para visualizarse correctamente)
- Diseño con colores de marca Rappi (rojo `#FF441F`)
- Secciones: resumen ejecutivo (tabla), análisis comparativo (gráficas), insights accionables

---

## Resumen de Datos Capturados por Plataforma

| Campo                  | Rappi (guest) | Rappi (login) | Uber Eats (guest) | Uber Eats (login) | DiDi Food |
|------------------------|:-------------:|:-------------:|:-----------------:|:-----------------:|:---------:|
| nombre_restaurante     | ✅            | ✅            | ✅                | ✅                | ✅        |
| costo_envio            | ✅            | ✅            | ⚠️ $0 (promo)    | ✅                | ❌        |
| costo_servicio         | ⚠️ 0%        | ✅ (%)        | ❌ null           | ✅ (MXN)          | ❌        |
| tiempo_entrega_min/max | ✅            | ✅            | ✅                | ✅                | ❌        |
| precio_producto        | ✅            | ✅            | ✅                | ✅                | ❌        |
| descuento_activo       | ✅            | ✅            | ✅                | ✅                | ❌        |
| calificacion           | ✅            | ✅            | ✅                | ✅                | ✅        |
| disponibilidad_zona    | ✅            | ✅            | ✅                | ✅                | ❌        |

---

## Resumen de Puntos a Revisar / Posibles Ajustes

| # | Archivo | Descripción del problema | Severidad |
|---|---------|--------------------------|-----------|
| 1 | `config/products.json` | El archivo existe y está bien configurado, pero **no lo usa ningún scraper**. Los scrapers usan un dict hardcodeado en `base.py` (`PRODUCTOS_OBJETIVO`). Si se actualiza uno, el otro no se actualiza. | Media |
| 2 | `scrapers/ubereats.py` | Sin credenciales, `costo_servicio` es siempre `null` y `costo_envio` puede ser $0 por promo de nuevos usuarios. El login está comentado como "futuro — Opción B". | Alta |
| 3 | `scrapers/didifood.py` | DiDi Food web no tiene datos por zona ni la mayoría de métricas. Solo aporta nombre y rating. El login tampoco está implementado. Su valor comparativo es muy limitado. | Alta |
| 4 | `scrapers/rappi.py` | Sin credenciales, `costo_servicio` siempre es 0%. Con credenciales es un %, mientras que en Uber Eats es en MXN. Las unidades son incompatibles entre plataformas. | Alta |
| 5 | `storage/db.py` | Cada corrida borra los datos históricos (`DROP TABLE IF EXISTS`). No hay acumulación temporal. | Media |
| 6 | `main.py` | Los scrapers corren secuencialmente. Con 3 plataformas × 25 zonas y pausa de 2–5s entre zonas, más el tiempo de navegación, una corrida completa puede tomar 30–60+ minutos. | Baja |
| 7 | `analysis/report.py` | La gráfica de heatmap por zona requiere que Rappi, Uber Eats y DiDi tengan datos de `costo_envio` en las mismas zonas. Con DiDi sin datos y Uber Eats con $0 promo, el heatmap puede quedar casi vacío o distorsionado. | Media |
| 8 | `scrapers/ubereats.py` | La intercepción de `getFeedV1` depende de que la API de Uber Eats responda. Si Uber Eats cambia su estructura de API (algo común en estas plataformas), el scraper puede dejar de capturar datos sin error explícito, cayendo silenciosamente al fallback HTML. | Media |

---

*Generado el 2026-04-20 — Para uso interno del equipo de Strategy & Pricing.*
