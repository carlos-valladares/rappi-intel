# Arquitectura del Sistema — Rappi Competitive Intelligence

## Visión General

Sistema de scraping asíncrono que recopila datos de precios, tiempos de entrega, costos de envío y promociones de tres plataformas de delivery en CDMX: **Rappi** (baseline propio), **Uber Eats** y **DiDi Food**.

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                          │
│   CLI: --platform, --addresses, --*-email/password      │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
    ┌──────────┐  ┌──────────────┐  ┌──────────────┐
    │  Rappi   │  │  Uber Eats   │  │  DiDi Food   │
    │ Scraper  │  │   Scraper    │  │   Scraper    │
    └────┬─────┘  └──────┬───────┘  └──────┬───────┘
         │               │                 │
         └───────────────┴─────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   ScraperBase (ABC)  │
              │  - Playwright browser│
              │  - Stealth / Geoloc  │
              │  - Rate limiting     │
              │  - Retry + backoff   │
              │  - Network intercept │
              └──────────┬───────────┘
                         │
           ┌─────────────┴─────────────┐
           ▼                           ▼
  ┌─────────────────┐       ┌──────────────────────┐
  │  storage/db.py  │       │  analysis/report.py  │
  │  DuckDB         │       │  HTML Report         │
  │  datos_competencia│     │  Plotly Charts       │
  └─────────────────┘       └──────────────────────┘
```

## Componentes

### `main.py` — Orquestador
- Parsea argumentos CLI (plataforma, direcciones, credenciales)
- Resuelve credenciales con prioridad: plataforma-específica > global > None
- Ejecuta scrapers secuencialmente por plataforma
- Consolida resultados en DuckDB y genera reporte HTML

### `scrapers/base.py` — Clase Base Abstracta
Funcionalidades compartidas por todos los scrapers:

| Método | Descripción |
|--------|-------------|
| `_construir_contexto()` | Browser Chromium con stealth anti-detección |
| `_establecer_geolocalizacion()` | Simula GPS en coordenadas de la dirección |
| `_configurar_intercepcion()` | Captura respuestas JSON de las APIs |
| `_scroll_humano()` | Simula comportamiento humano para evitar bot-detection |
| `_espera_aleatoria()` | Rate limiting con jitter aleatorio |
| `_registro_base()` | Plantilla estándar de registro con todos los campos |
| `_scrape_con_reintento()` | Wrapper con tenacity: 3 intentos + backoff exponencial |
| `run()` | Loop principal sobre todas las direcciones |

### `scrapers/rappi.py` — Rappi (API directa)
**Estrategia: 100% API, sin parsing HTML.**

```
Browser abre rappi.com.mx
    → Intercepta POST /api/rocket/v2/guest → access_token (guest)
    → Intercepta GET catalog-paged/home → lista de tiendas
    → Para cada tienda objetivo (Burger King, Carl's Jr, OXXO, 7-Eleven):
        POST /api/web-gateway/web/restaurants-bus/store/id/{store_id}/
        Body: {lat, lng, store_type, is_prime}
        → percentage_service_fee (= 0 sin login), delivery_price, corridors[].products[]

Mejora futura: POST /api/rocket/v2/login {email, password} → token autenticado
    → desbloquea percentage_service_fee con valor real.

Nota: McDonald's no opera en Rappi México (exclusivo de Uber Eats).
```

### `scrapers/ubereats.py` — Uber Eats (API + HTML)
**Estrategia: API getFeedV1 + API getStoreV1 + fallback HTML**

```
Browser abre ubereats.com/mx
    → Configura dirección de entrega
    → Intercepta getFeedV1 → tiendas + storeUuid + actionUrl
    → Para cada tienda objetivo:
        POST /_p/api/getStoreV1 → fareInfo.serviceFeeCents, catalogSectionsMap
        GET actionUrl (página tienda) → costo_envio desde HTML
```

### `scrapers/didifood.py` — DiDi Food (HTML SSR)
**Estrategia: HTML SSR de páginas de categoría — 1 scraping/corrida (datos ciudad-CDMX)**

```
Primera dirección de la corrida:
    Browser navega a categorias (hamburguesas, abarrotes)
    → Parsea HTML SSR → nombre_restaurante, rating
    → Guarda en _cache_ciudad (lista de restaurantes CDMX)
    → Genera registros asignados a la primera dirección

Direcciones posteriores:
    → Cache ya poblado → retorna lista vacía (sin duplicar datos)
    → Los datos son ciudad-CDMX, no por zona geográfica

Datos de fees/ETAs/precios: NO DISPONIBLES en web pública.
Requieren API móvil (wsgsig), fuera del alcance actual.
```

### `storage/db.py` — Persistencia DuckDB
- Tabla: `datos_competencia`
- Ingesta con deduplicación por `(marca_tiempo, plataforma, id_direccion, nombre_restaurante)`
- Función `summary()` para estadísticas rápidas

### `analysis/report.py` — Reporte HTML
- Gráficas con Plotly: distribución de precios, costos de envío, disponibilidad por zona
- Exportado como HTML auto-contenido en `data/report.html`

## Configuración de Direcciones

`config/addresses.json` — 25 zonas de CDMX cubiertas:

| Tipo de Zona | Ejemplos |
|---|---|
| `premium` | Polanco, Lomas de Chapultepec, Santa Fe |
| `residencial` | Coyoacán, Del Valle, Narvarte |
| `popular` | Iztapalapa, Ecatepec, Xochimilco |
| `comercial` | Centro Histórico, Insurgentes, Pedregal |

## Modelo de Datos

Campos estándar por registro (`_registro_base`):

```python
{
    "marca_tiempo": "2026-04-05T18:00:00",
    "plataforma": "rappi | ubereats | didifood",
    "id_direccion": 1,
    "zona": "polanco",
    "tipo_zona": "premium",
    "direccion": "Presidente Masaryk 513...",
    "lat": 19.4322,
    "lng": -99.1966,
    "nombre_restaurante": "Burger King",
    "vertical": "fast_food | retail",
    "nombre_producto": "Whopper | Famous Star | Big Mac | Coca-Cola",
    "precio_producto": 144.0,        # MXN
    "costo_envio": 20.0,             # MXN (0 = promo nuevos usuarios)
    "costo_servicio": None,          # % o MXN (requiere login)
    "tiempo_entrega_min": 30,        # minutos
    "tiempo_entrega_max": 45,
    "descuento_activo": True,
    "descripcion_descuento": "Hasta 47% Off",
    "restaurante_disponible": True,
    "calificacion": 4.4,
    "estado_scraping": "ok | error | sin_datos | fallido",
    "mensaje_error": None
}
```
