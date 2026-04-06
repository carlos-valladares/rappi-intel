# Sistema de Inteligencia Competitiva Rappi

Sistema automatizado de inteligencia competitiva para comparar **Rappi vs Uber Eats vs DiDi Food** en 25 zonas de CDMX. Recopila precios, costos de envío, tiempos de entrega y promociones activas de forma automatizada.

---

## Tecnologias

| Tecnologia | Rol |
|---|---|
| **Python 3.11+** | Lenguaje base |
| **Playwright 1.44+** | Automatizacion de browser (Chromium) con stealth y geolocalizacion |
| **DuckDB 0.10+** | Base de datos analitica local para acumulacion de datos |
| **Pandas 2.2+** | Manipulacion y normalizacion de registros |
| **Plotly 5.22+** | Graficas interactivas en el reporte HTML |
| **Rich 13.7+** | Output formateado en consola (tablas, colores) |
| **Tenacity 8.3+** | Reintentos automaticos con backoff exponencial |
| **python-dotenv 1.0+** | Gestion de variables de entorno (.env) |

---

## Instalacion rapida

### Requisitos
- Python 3.11+

### Instalacion

```bash
git clone <url-del-repo>
cd rappi-intel
pip install -r requirements.txt
playwright install chromium
```

### Opcion adicional — Con entorno virtual (aislado)

Si manejas multiples proyectos Python y no quieres mezclar dependencias:

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
playwright install chromium
```

### Variable de entorno (opcional — solo si usas proxy)

```bash
cp .env.example .env
# Editar .env y agregar PROXY_URL si aplica
```

---

## Ejecucion

### Sin credenciales (sesion guest)

```bash
# Todas las plataformas, todas las zonas
python main.py

# Solo una plataforma
python main.py --platform rappi
python main.py --platform ubereats
python main.py --platform didifood

# Prueba rapida (primeras N zonas)
python main.py --addresses 3

# Ver el browser en accion
python main.py --headless false

# Solo regenerar el reporte (sin scraping)
python main.py --report-only
```

Al terminar la ejecucion, abre el reporte en tu browser:

```
data/report.html
```

### Con credenciales (datos completos) — Trabajo futuro

> **Nota:** El login con credenciales aun no esta implementado. Los parametros CLI
> estan disponibles pero la autenticacion contra cada plataforma es una mejora futura.
> Ver seccion "Trabajo futuro" al final.

```bash
# Credenciales por plataforma especifica (disponible cuando se implemente el login)
python main.py \
  --rappi-email tu@email.com    --rappi-password tupass \
  --ubereats-email tu@email.com --ubereats-password tupass \
  --didifood-email tu@email.com --didifood-password tupass

# Una cuenta para todas las plataformas
python main.py --email tu@email.com --password tupass

# Combinado: solo Rappi, 2 zonas, con credenciales
python main.py --platform rappi --addresses 2 --rappi-email tu@email.com --rappi-password tupass
```

---

## Niveles de acceso y datos disponibles

El sistema opera en tres niveles. Cada nivel adiciona datos que el anterior no puede obtener.

### Nivel 1 — Sin login (sesion guest)

| Campo | Rappi | Uber Eats | DiDi Food |
|-------|-------|-----------|-----------|
| nombre_restaurante | OK | OK | OK |
| calificacion | OK | OK | OK |
| tiempo_entrega | OK | OK | - (app only) |
| descuento_activo | OK | OK | - |
| precio_producto | OK | OK | - (app only) |
| costo_envio | OK* | OK* | - (app only) |
| costo_servicio | 0** | null** | - (app only) |

`*` El costo de envio puede ser $0 por promo de nuevos usuarios (ver abajo).
`**` El costo de servicio requiere autenticacion — NO es una promo, es una restriccion del backend.

### Nivel 2 — Login usuario nuevo

Mismo que Nivel 1 pero con `costo_servicio` disponible. El envio puede seguir en $0
si la promo de primera orden esta activa.

### Nivel 3 — Login usuario normal (sin suscripcion premium)

Todos los datos disponibles con valores reales (sin promos). Es el caso mas valioso
para inteligencia competitiva: representa lo que pagan los usuarios recurrentes.

> Los niveles premium (Rappi Prime, Uber One, DiDi Club) estan fuera del alcance
> de este sistema. Ver seccion "Trabajo Futuro" al final.

---

## Por que algunos valores aparecen en cero o null

### Costo de envio = $0 (promo confirmada para nuevos usuarios)

Investigacion verificada con fuentes oficiales:

| Plataforma | Promo | Condicion | Fuente oficial |
|---|---|---|---|
| **Rappi** | Envio gratis hasta 30 ordenes | Tope $20 MXN/envio, primeros 30 dias | [promos.rappi.com/mexico/eg30-2025](http://promos.rappi.com/mexico/eg30-2025) |
| **Uber Eats** | $100 MXN descuento en 1er pedido | Minimo $200 MXN, codigo mensual | [ubereats.com/promo](https://www.ubereats.com/promo) |
| **DiDi Food** | Hasta $140 MXN descuento | Minimo $190 MXN, codigo variable | Reportado en app; sin pagina oficial |

Ademas, el envio $0 esta confirmado directamente en las APIs:
- **Rappi:** campo `global_offers.tags[].title = "Envio gratis en tu primera orden"`, codigo interno `MX_ONB_FO_NOCASH_FS_V1`
- **Uber Eats:** texto `"MXN0 delivery fee | new customers"` en HTML de tienda

### Costo de servicio = 0 o null (restriccion de autenticacion, NO es promo)

El `costo_servicio` NO es cero por una promo. El backend de cada plataforma oculta
este dato a sesiones sin autenticacion:

- **Rappi:** `percentage_service_fee: 0.0` en sesion guest. La API tiene el campo
  `metadata.service_fee: null` y `charges.service.show_fee: False` sin ningun
  marcador de "primera orden" — es una restriccion pura de autenticacion.

- **Uber Eats:** `fareInfo.serviceFeeCents: null` en sesion guest. Confirmado por
  feature flag `show_fares_and_total_in_cart: False` en bootstrap de la app.

Para obtener el valor real: proporcionar credenciales con `--rappi-email/password`
o `--ubereats-email/password`.
- **Rappi:** login via API (`POST /api/rocket/v2/login`) — pendiente de implementar.
- **Uber Eats:** login via formulario web — pendiente de implementar.

---

## Estructura del proyecto

```
rappi-intel/
├── main.py                  # Orquestador principal y CLI
├── requirements.txt
├── .env.example
├── .gitignore
│
├── scrapers/
│   ├── base.py              # Clase base abstracta (Playwright, stealth, retry)
│   ├── rappi.py             # Scraper Rappi (100% API directa)
│   ├── ubereats.py          # Scraper Uber Eats (API getStoreV1 + HTML)
│   └── didifood.py          # Scraper DiDi Food (HTML SSR, limitado)
│
├── storage/
│   └── db.py                # DuckDB: ingesta y queries
│
├── analysis/
│   └── report.py            # Reporte HTML con graficas Plotly
│
├── config/
│   └── addresses.json       # 25 zonas de CDMX con coordenadas
│
├── data/
│   ├── .gitkeep
│   ├── raw/                 # CSVs y JSONs por ejecucion (excluido de git)
│   ├── competitive_intel.duckdb  # Base de datos (excluida de git)
│   └── report.html          # Dashboard generado (excluido de git)
│
└── docs/
    ├── arquitectura.md
    ├── flujo_de_datos.md
    ├── decisiones_tecnicas.md
    ├── niveles_de_acceso.md
    ├── diagramas/
    │   ├── arquitectura_sistema.graphml   # Compatible con yEd Graph Editor
    │   └── flujo_datos.graphml
    ├── docx/                # Documentacion en formato Word
    └── generar_docx.py      # Script para regenerar los .docx
```

---

## Salida de datos

### Archivos generados por ejecucion

```
data/raw/
  rappi_20260405_120000.csv          # Registros normalizados
  rappi_raw_20260405_120000.json     # Respuestas API crudas (debug)
  ubereats_20260405_120000.csv
  ubereats_raw_20260405_120000.json
  didifood_20260405_120000.csv

data/competitive_intel.duckdb        # Tabla acumulada datos_competencia
data/report.html                     # Dashboard interactivo
data/scraper.log                     # Log detallado
```

### Campos del CSV / base de datos

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| marca_tiempo | timestamp | Momento de captura |
| plataforma | str | rappi / ubereats / didifood |
| zona | str | polanco, iztapalapa, etc. |
| tipo_zona | str | premium / residencial / popular / comercial |
| nombre_restaurante | str | Nombre de la marca (McDonald's, Burger King, Carl's Jr, OXXO) |
| vertical | str | fast_food / retail |
| nombre_producto | str | Big Mac / Whopper / Famous Star / Coca-Cola |
| precio_producto | float | MXN |
| costo_envio | float | MXN (0 = promo nuevos usuarios) |
| costo_servicio | float | % o MXN (null sin login) |
| tiempo_entrega_min | int | minutos |
| tiempo_entrega_max | int | minutos |
| descuento_activo | bool | Hay promocion activa |
| descripcion_descuento | str | Texto de la promocion |
| restaurante_disponible | bool | Abierto al momento del scraping |
| calificacion | float | 0.0 - 5.0 |
| estado_scraping | str | ok / error / sin_datos / fallido |

---

## Cobertura geografica

25 zonas de CDMX:

| Tipo | Zonas | Ejemplo |
|------|-------|---------|
| Premium | 6 | Polanco, Lomas de Chapultepec, Santa Fe |
| Residencial | 7 | Coyoacan, Del Valle, Narvarte, Roma, Condesa |
| Comercial | 6 | Centro Historico, Insurgentes, Pedregal |
| Popular | 6 | Iztapalapa, Ecatepec, Xochimilco, Tlalpan |

---

## Limitaciones documentadas

| Limitacion | Plataforma | Causa | Estado |
|---|---|---|---|
| fees/ETAs/precios no disponibles | DiDi Food | Web es marketing SSR; APIs requieren wsgsig de app movil (no replicable) | Limitacion permanente |
| Datos DiDi a nivel ciudad | DiDi Food | Web no expone datos por zona geografica | Documentado — 1 scraping por corrida |
| costo_servicio = 0 | Rappi | Restriccion de autenticacion (no promo) | Requiere login Rappi (pendiente) |
| costo_servicio = null | Uber Eats | Restriccion de autenticacion (no promo) | Requiere login UberEats (pendiente) |
| costo_envio = $0 | Rappi, Uber Eats | Promo nuevos usuarios (confirmada en API) | Comportamiento esperado con cuenta nueva |
| McDonald's ausente en Rappi | Rappi | McDonald's opera exclusivamente en Uber Eats Mexico | Hallazgo de inteligencia competitiva |
| OXXO/7-Eleven en DiDi | DiDi Food | DiDi no opera retail en CDMX | Hallazgo de inteligencia competitiva |
| Precios dinamicos | Todas | Los precios varian por hora/demanda | Timestamp en cada registro |

---

## Etica y legalidad

- Rate limiting de 2-5 segundos entre requests con jitter aleatorio
- User-Agents de browsers reales rotados
- No se almacenan datos personales de usuarios
- Solo datos publicos de precios (equivalente a consultarlos manualmente)
- Uso exclusivo para analisis competitivo interno

---

## Trabajo futuro

**Login y autenticacion (alta prioridad):**
- [ ] Login Rappi via API (`POST /api/rocket/v2/login`) — desbloquea `costo_servicio` real
- [ ] Login UberEats via browser — desbloquea `costo_servicio` y `costo_envio` reales
- [ ] Soporte para suscripciones premium: Rappi Prime, Uber One

**DiDi Food:**
- [ ] Investigar API movil de DiDi (wsgsig) para desbloquear fees, ETAs y precios
  *(requiere ingenieria reversa de la app — alta complejidad)*

**Operaciones:**
- [ ] Scheduler para ejecucion periodica (cron / GitHub Actions)
- [ ] Alertas automaticas cuando un competidor cambia precios > X%

**Expansion:**
- [ ] Otras ciudades: Monterrey, Guadalajara
- [ ] Dashboard web en tiempo real (Streamlit o Marimo)

---

## Documentacion tecnica

Ver `/docs/` para documentacion completa:

- [Arquitectura del sistema](docs/arquitectura.md)
- [Flujo de datos](docs/flujo_de_datos.md)
- [Decisiones tecnicas](docs/decisiones_tecnicas.md)
- [Niveles de acceso](docs/niveles_de_acceso.md)
- Diagramas `.graphml` (compatibles con [yEd Graph Editor](https://www.yworks.com/products/yed) y [draw.io](https://app.diagrams.net/))
