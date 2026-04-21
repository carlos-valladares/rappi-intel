# Decisiones Técnicas

Registro de decisiones de diseño con su contexto y razonamiento.

---

## DT-01 — Rappi: API directa en lugar de scraping HTML

**Decisión:** Usar la API interna de Rappi (`mxgrability.rappi.com`) con token guest
interceptado del browser, en lugar de parsear HTML.

**Contexto:** Rappi carga su contenido vía APIs JSON que el browser consume. El HTML
renderizado contiene poco dato útil.

**Razonamiento:**
- Más robusto: los campos JSON son estables; el HTML cambia con cada deploy
- Más rápido: sin necesidad de esperar render completo
- Más completo: la API retorna campos (`eta`, `delivery_price`, `rating.score`) que
  no siempre aparecen en el HTML

**Impacto:** `_parsear_interceptadas()` procesa el JSON del catalog. `_capturar_precio_api()`
llama directamente `POST /store/id/{store_id}/` con el bearer token.

---

## DT-02 — Rappi: Token guest + login autenticado por API

**Decisión:** Usar el token guest automático como fallback; si se proporcionan
credenciales, obtener token autenticado via `POST /api/rocket/v2/login` antes de
navegar la página.

**Contexto:** El browser obtiene el token guest automáticamente al cargar rappi.com.mx.
El login de Rappi es 100% por API REST, sin formulario web.

**Razonamiento:**
- Con token guest: catálogo, precios de productos, ETAs, delivery fee — todos disponibles
- Solo `percentage_service_fee` requiere token autenticado (retorna 0.0 para guests)
- El login por API es más robusto que automatización de formulario: sin CAPTCHA, sin 2FA

**Estado:** Pendiente de implementar. El scaffolding de credenciales está completo
(los parámetros `--rappi-email/password` se reciben y pasan al scraper), pero la
llamada al endpoint de login aún no se ejecuta en el flujo principal.

**Implementación futura:**
- Llamar `POST /api/rocket/v2/login` con `{email, password, type: "email"}` antes de navegar
- Sobreescribir `self._bearer_token` con el token autenticado
- Con token autenticado, `percentage_service_fee` retorna el valor real en lugar de 0.0

**Impacto actual:** Sin credenciales activas, `percentage_service_fee` = 0.0
(restricción de autenticación del backend, no una promo).

---

## DT-03 — UberEats: `getStoreV1` API para precios de producto

**Decisión:** Usar `POST /_p/api/getStoreV1?localeCode=mx` para obtener precios
de productos en lugar de parsear el HTML de la página de tienda.

**Contexto:** Los precios en HTML están en texto libre (`MX$144`) mezclados con
descripciones y nombres de combo. La API retorna precios en centavos en
`catalogSectionsMap.*.payload.standardItemsPayload.catalogItems[].price`.

**Razonamiento:**
- Precios en centavos: formato exacto y sin ambigüedad (14400 = MXN$144)
- Estructura tipada: `title` y `price` siempre presentes
- `min(candidatos)` captura el item standalone vs. combo

**Impacto:** `_capturar_store_api()` llama la API con `storeUuid` (capturado del feed).
El parsing HTML queda como fallback en `_precio_desde_texto_ue()`.

---

## DT-04 — DiDi Food: Limitación documentada (Opción C)

**Decisión:** Capturar solo `nombre_restaurante` y `calificacion` desde la web pública
de DiDi Food. No intentar scraping de la app móvil.

**Contexto:** DiDi Food opera en México con una web de marketing SSR. Todos los links
de restaurante redirigen a la app móvil (`didi-food.com/es-MX/store?...`). No hay
páginas individuales con menú en la web.

**Razonamiento:**
- La API de la app requiere `wsgsig` (firma de seguridad generada por el cliente móvil)
- Intentar replicar `wsgsig` es ingeniería reversa de la app nativa: riesgo legal y
  técnico alto
- El valor de inteligencia competitiva de DiDi se obtiene principalmente de Rappi y
  Uber Eats

**Investigación realizada:** Se confirmó que DiDi Food México admite login con Google
y Facebook OAuth (además de teléfono+SMS). Sin embargo, el login web no desbloquea
fees ni ETAs: la web sigue siendo un portal de marketing con las mismas limitaciones.
Los datos operativos (precios, tiempos, costos) existen solo en la API móvil protegida
por `wsgsig`.

**Alternativa descartada:** Replicar `wsgsig` requiere ingeniería reversa de la app
nativa — riesgo legal y técnico fuera del alcance del proyecto.

**Impacto:** `DidiScraper._cache_ciudad` almacena los datos a nivel ciudad.
El scraping se ejecuta **una sola vez por corrida** (ver DT-10).
`precio_producto`, `costo_envio`, `tiempo_entrega_*` = `None` permanentemente para DiDi.

---

## DT-05 — Geolocalización browser vs. IP del servidor

**Decisión:** Establecer geolocalización del browser (`context.set_geolocation()`) y
usar las coordenadas de la dirección en el body de las APIs.

**Contexto:** Rappi usa geolocalización IP del servidor para determinar tiendas
disponibles, no la geolocalización del browser. Si la IP de la máquina resuelve a
una zona diferente (ej. Iztapalapa en lugar de Polanco), la API de tienda redirige
a `restaurantNotFound=true`.

**Decisión específica para Rappi:** Pasar `{lat, lng}` explícitamente en el body de
`POST /store/id/{store_id}/`. El servidor usa esas coordenadas para verificar cobertura.

**Impacto:** `_capturar_precio_api()` recibe `lat, lng` de `direccion` y los incluye
en el payload. Sin esto, las 25 zonas convergerían a la tienda de la IP del servidor.

---

## DT-06 — Cache de precios por scraper (nivel de clase)

**Decisión:** `_cache_precios: dict = {}` como variable de clase (no instancia) en
`RappiScraper` y `UberEatsScraper`.

**Contexto:** El mismo restaurante (ej. Burger King Polanco) aparece en múltiples
direcciones. Llamar la API de menú 25 veces para el mismo store_id es redundante.

**Razonamiento:**
- Reduce llamadas API: de O(n_direcciones × n_restaurantes) a O(n_restaurantes)
- Para UberEats: `{precio, servicio}` por nombre de restaurante (storeUuid varía por zona)
- Para Rappi: `{precio, servicio}` por `store_id:producto`

**Impacto:** El segundo scraping de la misma tienda en diferente zona usa el cache.
El cache vive durante la sesión del proceso Python (se reinicia en cada ejecución).

---

## DT-07 — DuckDB como almacenamiento

**Decisión:** DuckDB en lugar de SQLite, PostgreSQL o CSV puro.

**Razonamiento:**
- Analítico: DuckDB está optimizado para queries OLAP sobre columnas
- Sin servidor: archivo local, sin instalación adicional
- Compatible con pandas: `duckdb.query().df()` retorna DataFrame directamente
- Velocidad: 10x más rápido que SQLite para queries de agregación sobre los datos
  de las 25 zonas × 3 plataformas

**Impacto:** `storage/db.py` usa `duckdb.connect("data/competitive_intel.duckdb")`.

---

## DT-08 — Stealth anti-detección

**Decisión:** Aplicar técnicas de stealth básicas sin usar `playwright-stealth` externo.

**Técnicas implementadas en `_construir_contexto()`:**
```javascript
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
Object.defineProperty(navigator, 'languages', { get: () => ['es-MX', 'es', 'en'] });
window.chrome = { runtime: {} };
```

**Adicional:**
- User-Agent rotado de pool de 4 agentes reales
- Locale `es-MX`, timezone `America/Mexico_City`
- `--disable-blink-features=AutomationControlled`
- Scroll humano con `mouse.wheel()` + sleeps aleatorios

**Razonamiento:** Las tres plataformas usan Cloudflare o detectores similares.
Sin stealth, el scraper es bloqueado en < 3 requests.

---

## DT-09 — Targets de Rappi: incluir Carl's Jr

**Decisión:** Incluir Carl's Jr como target de Rappi además de Burger King, OXXO y 7-Eleven.

**Contexto:** McDonald's no apareció en las respuestas de la API de Rappi durante las
zonas analizadas. Puede deberse a cobertura de zonas, configuración del scraper, o
disponibilidad real — pendiente de verificar con más zonas.

**Razonamiento:**
- Carl's Jr sí está disponible en Rappi CDMX con precios y ETAs accesibles
- Agrega un segundo punto de comparación en la vertical de fast food junto a Burger King

**Impacto:** `RESTAURANTES_OBJETIVO` en `rappi.py` incluye Carl's Jr; `PRODUCTOS_OBJETIVO`
en `base.py` mapea `"carl's jr"` → `"Famous Star"`.

---

## DT-10 — DiDi Food: scraping único por corrida (no por zona)

**Decisión:** Ejecutar el scraping de DiDi Food una sola vez por corrida, asignando
los registros a la primera dirección. Las direcciones posteriores retornan lista vacía.

**Contexto:** La web de DiDi Food muestra el catálogo a nivel ciudad-CDMX, sin
filtrado por coordenada o zona. Scraping por cada dirección producía 25 × 18 = 450
registros con datos idénticos salvo el campo `zona` — dato que DiDi no provee por zona.

**Razonamiento:**
- Datos duplicados contaminan el análisis comparativo por zona
- El valor de DiDi en este sistema es presencia de marcas y rating a nivel ciudad
- Una ejecución por corrida mantiene el dataset limpio y honesto

**Impacto:** `DidiScraper._cache_ciudad is not None` → `return []` en scrapes
subsiguientes. Total de registros DiDi por corrida: número de restaurantes encontrados
(~18), no `n_zonas × n_restaurantes`.

---

## DT-11 — UberEats: ETA desde `accessibilityText`, no desde `text`

**Decisión:** Leer el campo `accessibilityText` del objeto `meta[0]` del feed de
Uber Eats para obtener el rango completo de tiempo de entrega.

**Contexto:** El campo `meta[0].text` contiene solo el tiempo mínimo (`"10 min"`),
lo que hacía que `tiempo_entrega_min == tiempo_entrega_max`. El campo
`accessibilityText` contiene el rango real: `"Entrega en 10-26 min"`.

**Razonamiento:**
- El tiempo de entrega como rango (min–max) es más informativo que un valor único
- `accessibilityText` es el campo pensado para lectores de pantalla y contiene la
  representación textual completa
- Ambos campos siempre coexisten; `accessibilityText` se usa con fallback a `text`

**Impacto:** `_parsear_feed()` en `ubereats.py` prioriza `accessibilityText`.
`_parsear_eta()` retorna `(min, max)` correctamente cuando hay rango.
