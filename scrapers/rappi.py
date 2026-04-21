"""
Rappi scraper — CDMX (baseline propio)

API confirmada por intercepcion de red:
  services.mxgrability.rappi.com/api/restaurant-bus/stores/catalog-paged/home
  Campos por tienda:
    brand_name             -> nombre de la marca
    delivery_price         -> costo de envio en MXN
    eta_value              -> ETA en minutos
    etas[0].{min,max}      -> rango de ETA
    status                 -> "OPEN" / "CLOSED"
    is_currently_available -> bool
    rating.score           -> calificacion
    global_offers.tags     -> promociones activas
    store_id               -> ID de tienda (para API de menu)
    friendly_url           -> slug de URL

API de menu por tienda (precio de producto + costo de servicio):
  POST services.mxgrability.rappi.com/api/web-gateway/web/restaurants-bus/store/id/{store_id}/
  Estructura: corridors[].products[].{name, price}
  Top-level: percentage_service_fee

LIMITACION CONOCIDA — Costo de envio $0 para primera orden:
  El campo global_offers.tags contiene un tag con title "Envio gratis en tu primera orden"
  y descripcion "MX_ONB_FO_NOCASH_FS_V1" (ONB=Onboarding, FO=First Order).
  Es una promo explicita para nuevos usuarios, NO el precio real de envio.
  El precio real se encuentra en delivery_price del catalog (ej. $9.9, $20, $30).

LIMITACION CONOCIDA — Costo de servicio = 0 requiere autenticacion:
  percentage_service_fee retorna 0.0 para sesiones guest.
  A diferencia del envio, NO hay ningun marcador de "primera orden" asociado:
    metadata.service_fee = null
    metadata.onboarding = null
    charges.service.show_fee = False (sin etiqueta de promo)
  Conclusion: el fee de servicio es ocultado por el backend para sesiones sin login.
  Requiere --rappi-email / --rappi-password para obtener el valor real.
  El login en Rappi es 100% por API (POST /api/rocket/v2/login con email+password).

IMPLEMENTACION DE LOGIN:
  Nivel 1 (guest):      token de POST /api/rocket/v2/guest → percentage_service_fee = 0
  Nivel 2/3 (usuario):  token de POST /api/rocket/v2/login → percentage_service_fee = valor real
  El token autenticado sobreescribe el guest token en self._bearer_token.
"""
import asyncio
import json
import re
from typing import Any

from playwright.async_api import BrowserContext, Page

from scrapers.base import ScraperBase, PRODUCTOS_OBJETIVO

PATRONES_INTERCEPCION = [
    "catalog-paged",
    "restaurant-bus/stores",
    "mxgrability.rappi.com",
]

PATRON_API_TIENDA = "restaurants-bus/store/id/"

# NOTA: McDonald's no opera en Rappi Mexico — es exclusivo de Uber Eats.
# Carl's Jr y Burger King si estan disponibles en Rappi CDMX.
RESTAURANTES_OBJETIVO = ["burger king", "carl's jr", "carl jr", "oxxo", "7-eleven", "seven eleven"]


class RappiScraper(ScraperBase):
    plataforma = "rappi"
    _cache_precios: dict = {}  # "{store_id}:{producto}" -> precio float | None

    async def scrape_address(self, direccion: dict, contexto: BrowserContext) -> list[dict]:
        self._interceptadas.clear()
        await contexto.clear_cookies()
        pagina = await contexto.new_page()
        registros = []

        try:
            await self._establecer_geolocalizacion(contexto, direccion["lat"], direccion["lng"])
            self._configurar_intercepcion(pagina, PATRONES_INTERCEPCION)

            # LOGIN por API (si se proporcionan credenciales)
            if self.credenciales.get("email") and self.credenciales.get("password"):
                await self._login_rappi(contexto)

            await pagina.goto(
                "https://www.rappi.com.mx",
                wait_until="domcontentloaded",
                timeout=35000,
            )
            await pagina.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch(e) {} }")
            await asyncio.sleep(8)

            registros = await self._raspar_con_direccion(pagina, direccion, contexto)

        except Exception as e:
            self.log.error(f"Rappi error en {direccion['zone']}: {e}")
            rec = self._registro_base(direccion)
            rec["estado_scraping"] = "error"
            rec["mensaje_error"] = str(e)
            registros = [rec]
        finally:
            await pagina.close()

        return registros

    async def _raspar_con_direccion(
        self, pagina: Page, direccion: dict, contexto: BrowserContext
    ) -> list[dict]:
        try:
            sel_input = (
                'input[placeholder*="irección"], input[placeholder*="Dirección"], '
                'input[data-testid*="address"], input[placeholder*="ubica"]'
            )
            campo = pagina.locator(sel_input).first
            if await campo.count() > 0:
                await campo.click()
                await asyncio.sleep(0.5)
                await campo.fill(direccion["address"][:60])
                await asyncio.sleep(2.5)
                sugerencia = pagina.locator('[role="option"], [class*="suggestion"], li[class*="item"]').first
                if await sugerencia.count() > 0:
                    await sugerencia.click()
                    await asyncio.sleep(4)
        except Exception as e:
            self.log.debug(f"Rappi input direccion fallido (no critico): {e}")

        await self._scroll_humano(pagina, scrolls=5)
        await asyncio.sleep(3)

        # Extraer bearer token de las capturas (obtenido durante la carga del home)
        self._extraer_token()

        if self._interceptadas:
            registros = self._parsear_interceptadas(direccion)
        else:
            registros = await self._parsear_html_feed(pagina, direccion)

        if registros:
            await self._enriquecer_precios_producto(contexto, registros, direccion)

        return registros if registros else [self._registro_sin_datos(direccion)]

    async def _login_rappi(self, contexto: BrowserContext):
        """
        Autentica con la API de Rappi usando email+password.
        POST /api/rocket/v2/login retorna access_token que sobreescribe el token guest.
        Con este token, percentage_service_fee retorna el valor real en lugar de 0.
        """
        email = self.credenciales["email"]
        password = self.credenciales["password"]
        try:
            respuesta = await contexto.request.post(
                "https://services.mxgrability.rappi.com/api/rocket/v2/login",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "app-version": "1.161.2",
                    "accept-language": "es-MX",
                },
                data=json.dumps({
                    "email": email,
                    "password": password,
                    "type": "email",
                }),
            )
            if respuesta.ok:
                cuerpo = await respuesta.json()
                token = cuerpo.get("access_token") or (cuerpo.get("data") or {}).get("access_token")
                if token:
                    self._bearer_token = token
                    self.log.info(f"Rappi: login exitoso para {email} — token autenticado activo")
                else:
                    self.log.warning(f"Rappi: login OK pero sin access_token en respuesta: {list(cuerpo.keys())}")
            else:
                texto = await respuesta.text()
                self.log.warning(f"Rappi login fallido ({respuesta.status}): {texto[:200]}")
        except Exception as e:
            self.log.error(f"Rappi login error: {e}")

    def _extraer_token(self):
        """Extrae el bearer token de guest de las capturas interceptadas."""
        for captura in self._interceptadas:
            body = captura.get("body", {})
            if isinstance(body, dict) and "access_token" in body:
                # Solo usar token de captura si no tenemos ya un token autenticado
                if not getattr(self, "_bearer_token", None):
                    self._bearer_token = body["access_token"]
                    self.log.debug(f"Rappi: token guest extraido ({self._bearer_token[:20]}...)")
                return

    def _parsear_interceptadas(self, direccion: dict) -> list[dict]:
        registros = []

        for captura in self._interceptadas:
            cuerpo = captura.get("body", {})

            lista_tiendas = []
            if isinstance(cuerpo, dict) and "stores" in cuerpo:
                lista_tiendas = cuerpo["stores"]
            else:
                lista_tiendas = self._extraer_tiendas_recursivo(cuerpo)

            for tienda in lista_tiendas:
                marca = (
                    tienda.get("brand_name", "")
                    or tienda.get("name", "")
                    or tienda.get("store_name", "")
                )
                if not marca or not any(t in marca.lower() for t in RESTAURANTES_OBJETIVO):
                    continue

                rec = self._registro_base(direccion)
                rec["nombre_restaurante"] = marca

                # Disponibilidad
                estado = tienda.get("status", "")
                disponible = tienda.get("is_currently_available", True)
                rec["restaurante_disponible"] = (estado == "OPEN") and disponible

                # Costo de envio
                precio_envio = tienda.get("delivery_price")
                if precio_envio is not None:
                    rec["costo_envio"] = self._precio_seguro(precio_envio)

                # ETA
                etas = tienda.get("etas", [])
                if etas and isinstance(etas[0], dict):
                    rec["tiempo_entrega_min"] = etas[0].get("min")
                    rec["tiempo_entrega_max"] = etas[0].get("max")
                elif tienda.get("eta_value"):
                    v = int(tienda["eta_value"])
                    rec["tiempo_entrega_min"] = max(1, v - 5)
                    rec["tiempo_entrega_max"] = v
                elif tienda.get("eta"):
                    mn, mx = self._parsear_eta(str(tienda["eta"]))
                    rec["tiempo_entrega_min"] = mn
                    rec["tiempo_entrega_max"] = mx

                # Calificacion
                obj_rating = tienda.get("rating", {})
                if isinstance(obj_rating, dict):
                    rec["calificacion"] = obj_rating.get("score")

                # Descuentos
                ofertas = tienda.get("global_offers", {})
                etiquetas = ofertas.get("tags", []) if isinstance(ofertas, dict) else []
                if not etiquetas:
                    etiquetas = tienda.get("promotions", []) or tienda.get("tags_offers", [])
                if etiquetas:
                    rec["descuento_activo"] = True
                    descs = [
                        (et.get("tag", "") or et.get("title", ""))
                        for et in etiquetas
                        if isinstance(et, dict)
                    ]
                    rec["descripcion_descuento"] = ", ".join(d for d in descs if d)[:200]

                rec["vertical"] = self._detectar_vertical(marca)

                # Campos temporales para enriquecimiento (se eliminan al final)
                rec["_store_id"] = str(tienda.get("store_id", ""))
                # friendly_url puede ser un dict {"store_id": ..., "friendly_url": "slug"}
                friendly_raw = tienda.get("friendly_url", "")
                if isinstance(friendly_raw, dict):
                    rec["_store_slug"] = friendly_raw.get("friendly_url", "")
                else:
                    rec["_store_slug"] = str(friendly_raw).lower().replace(" ", "-")
                rec["_producto_objetivo"] = next(
                    (prod for clave, prod in PRODUCTOS_OBJETIVO.items() if clave in marca.lower()),
                    None,
                )

                registros.append(rec)

        # Deduplicar por (id_direccion, nombre_restaurante)
        vistos: set = set()
        unicos = []
        for r in registros:
            clave = (r["id_direccion"], r["nombre_restaurante"])
            if clave not in vistos:
                vistos.add(clave)
                unicos.append(r)
        return unicos

    async def _enriquecer_precios_producto(
        self, contexto: BrowserContext, registros: list[dict], direccion: dict
    ):
        """
        Obtener precio del producto objetivo y costo de servicio via API directa de Rappi.
        Usa el bearer token de guest + coordenadas de la direccion para llamar
        POST /api/web-gateway/web/restaurants-bus/store/id/{store_id}/
        sin necesidad de navegar a ninguna pagina.

        La API retorna 'percentage_service_fee' en el top-level (ej. 10.0 = 10%).
        Se guarda en costo_servicio como porcentaje.
        """
        lat = direccion["lat"]
        lng = direccion["lng"]

        for rec in registros:
            store_id = rec.pop("_store_id", "")
            rec.pop("_store_slug", "")
            producto_objetivo = rec.pop("_producto_objetivo", None)

            if not store_id or not producto_objetivo:
                continue

            clave_cache = f"{store_id}:{producto_objetivo}"
            if clave_cache in RappiScraper._cache_precios:
                cached = RappiScraper._cache_precios[clave_cache]
                rec["nombre_producto"] = producto_objetivo
                rec["precio_producto"] = cached.get("precio")
                rec["costo_servicio"] = cached.get("servicio")
                self.log.debug(f"Cache Rappi: {store_id} {producto_objetivo}={rec['precio_producto']}")
                continue

            precio, pct_servicio = await self._capturar_precio_api(
                contexto, store_id, producto_objetivo, lat, lng
            )
            RappiScraper._cache_precios[clave_cache] = {"precio": precio, "servicio": pct_servicio}
            rec["nombre_producto"] = producto_objetivo
            rec["precio_producto"] = precio
            rec["costo_servicio"] = pct_servicio

    async def _capturar_precio_api(
        self,
        contexto: BrowserContext,
        store_id: str,
        producto_objetivo: str,
        lat: float,
        lng: float,
    ) -> tuple[float | None, float | None]:
        """
        Llama directamente a la API de menu de Rappi con POST y retorna:
          - precio mas bajo del producto objetivo
          - percentage_service_fee (% de cargo por servicio, ej. 10.0)

        API: POST /api/web-gateway/web/restaurants-bus/store/id/{store_id}/
        Body: {"lat": ..., "lng": ..., "store_type": "restaurant", ...}
        Retorna top-level: percentage_service_fee, delivery_price, corridors[]
        """
        if not getattr(self, "_bearer_token", None):
            self.log.debug(f"Rappi: sin token para obtener precio de {producto_objetivo}")
            return None, None

        url_api = f"https://services.mxgrability.rappi.com/api/web-gateway/web/restaurants-bus/store/id/{store_id}/"
        payload = json.dumps({
            "lat": lat,
            "lng": lng,
            "store_type": "restaurant",
            "is_prime": False,
            "prime_config": {"unlimited_shipping": False},
        })

        try:
            respuesta = await contexto.request.post(
                url_api,
                headers={
                    "Authorization": f"Bearer {self._bearer_token}",
                    "accept-language": "es-MX",
                    "app-version": "1.161.2",
                    "needappsflyerid": "false",
                    "content-type": "application/json",
                },
                data=payload,
            )
            if respuesta.ok:
                cuerpo = await respuesta.json()

                # Costo de servicio: porcentaje en top-level
                pct_raw = cuerpo.get("percentage_service_fee") if isinstance(cuerpo, dict) else None
                pct_servicio = float(pct_raw) if pct_raw is not None else None

                precio = self._precio_desde_corridors(cuerpo, producto_objetivo)
                if precio is not None:
                    self.log.info(
                        f"Rappi API: {producto_objetivo} = ${precio} | "
                        f"costo_servicio={pct_servicio}% (tienda {store_id})"
                    )
                return precio, pct_servicio
            else:
                self.log.debug(f"Rappi API {respuesta.status} para tienda {store_id}")
        except Exception as e:
            self.log.debug(f"Rappi API error precio tienda {store_id}: {e}")
        return None, None

    def _precio_desde_corridors(self, cuerpo: Any, producto_objetivo: str) -> float | None:
        """
        Buscar precio en corridors[].products[] de la API de menu.
        Retorna el precio MAS BAJO entre los productos que coincidan,
        para capturar el item standalone en lugar de un combo/meal.
        """
        nombre_lower = producto_objetivo.lower()
        corridors = []
        if isinstance(cuerpo, dict):
            corridors = cuerpo.get("corridors", [])
            if not corridors:
                for val in cuerpo.values():
                    if isinstance(val, dict):
                        corridors = val.get("corridors", [])
                        if corridors:
                            break

        candidatos: list[float] = []
        for corredor in corridors:
            if not isinstance(corredor, dict):
                continue
            for producto in corredor.get("products", []):
                if not isinstance(producto, dict):
                    continue
                nombre_prod = (producto.get("name", "") or "").lower()
                if nombre_lower in nombre_prod or nombre_prod in nombre_lower:
                    precio_raw = (
                        producto.get("price")
                        or producto.get("real_price")
                        or producto.get("original_price")
                    )
                    if precio_raw is not None:
                        precio = self._precio_seguro(precio_raw)
                        if precio and 10 <= precio <= 2000:
                            candidatos.append(precio)

        # El item standalone suele ser el mas barato de los que coincidan
        return min(candidatos) if candidatos else None

    def _precio_desde_texto_html(self, texto: str, producto_objetivo: str) -> float | None:
        """Fallback: buscar precio en texto plano del HTML."""
        lineas = [l.strip() for l in texto.split("\n") if l.strip()]
        nombre_lower = producto_objetivo.lower()
        for i, linea in enumerate(lineas):
            if nombre_lower in linea.lower():
                contexto_local = " ".join(lineas[i:i+4])
                precios = re.findall(r'(?:MX)?\$\s*(\d+(?:[.,]\d+)?)', contexto_local)
                for p_str in precios:
                    try:
                        val = float(p_str.replace(",", "."))
                        if 10 <= val <= 2000:
                            return val
                    except ValueError:
                        pass
        return None

    def _extraer_tiendas_recursivo(self, cuerpo: Any) -> list[dict]:
        tiendas = []
        if isinstance(cuerpo, dict):
            for clave in ("stores", "data", "results", "items", "restaurants", "payload"):
                if clave in cuerpo:
                    tiendas.extend(self._extraer_tiendas_recursivo(cuerpo[clave]))
            if any(k in cuerpo for k in ("brand_name", "name", "store_name", "storeName")):
                tiendas.append(cuerpo)
        elif isinstance(cuerpo, list):
            for elem in cuerpo:
                tiendas.extend(self._extraer_tiendas_recursivo(elem))
        return tiendas

    async def _parsear_html_feed(self, pagina: Page, direccion: dict) -> list[dict]:
        registros = []
        try:
            selectores = [
                '[data-testid*="store"]',
                '[class*="store-card"]',
                '[class*="StoreCard"]',
                '[class*="restaurant"]',
            ]
            tarjetas = []
            for sel in selectores:
                encontradas = await pagina.query_selector_all(sel)
                if encontradas:
                    tarjetas = encontradas
                    break

            for tarjeta in tarjetas[:30]:
                try:
                    el_nombre = await tarjeta.query_selector("h3, h4, [class*='name'], [class*='title']")
                    nombre = (await el_nombre.inner_text()).strip() if el_nombre else ""

                    if not nombre or not any(t in nombre.lower() for t in RESTAURANTES_OBJETIVO):
                        continue

                    rec = self._registro_base(direccion)
                    rec["nombre_restaurante"] = nombre

                    el_envio = await tarjeta.query_selector("[class*='delivery'], [class*='fee'], [class*='envio']")
                    if el_envio:
                        rec["costo_envio"] = self._precio_seguro(await el_envio.inner_text())

                    el_eta = await tarjeta.query_selector("[class*='time'], [class*='eta'], [class*='min']")
                    if el_eta:
                        rec["tiempo_entrega_min"], rec["tiempo_entrega_max"] = self._parsear_eta(
                            await el_eta.inner_text()
                        )

                    rec["vertical"] = self._detectar_vertical(nombre)
                    registros.append(rec)
                except Exception as e:
                    self.log.debug(f"Rappi tarjeta HTML error: {e}")

        except Exception as e:
            self.log.debug(f"Rappi fallback HTML error: {e}")

        return registros

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _precio_seguro(self, valor: Any) -> float | None:
        if valor is None:
            return None
        if isinstance(valor, (int, float)):
            val = float(valor)
            val = val / 100 if val > 1000 else val
            return round(val, 2)
        limpio = re.sub(r"[^\d.]", "", str(valor))
        try:
            return round(float(limpio), 2) if limpio else None
        except ValueError:
            return None

    def _parsear_eta(self, texto: str) -> tuple[int | None, int | None]:
        nums = re.findall(r"\d+", str(texto))
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            v = int(nums[0])
            return max(1, v - 5), v
        return None, None

    def _detectar_vertical(self, nombre: str) -> str:
        if any(x in nombre.lower() for x in ["oxxo", "7-eleven", "walmart", "chedraui"]):
            return "retail"
        return "fast_food"

    def _registro_sin_datos(self, direccion: dict) -> dict:
        rec = self._registro_base(direccion)
        rec["estado_scraping"] = "sin_datos"
        rec["mensaje_error"] = "No se encontraron restaurantes objetivo"
        return rec
