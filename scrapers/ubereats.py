"""
Uber Eats scraper — CDMX

API confirmada por intercepcion:
  getFeedV1: feedItems > carousel > stores[]
    store.storeUuid          -> UUID para llamar getStoreV1
    store.title.text         -> nombre
    store.meta[0].text       -> ETA ("10 min" o "10-15 min")
    store.rating.text        -> calificacion
    store.signposts[].text   -> descuentos activos
    store.actionUrl          -> path de la pagina de tienda

API de tienda confirmada (sin login):
  POST /_p/api/getStoreV1?localeCode=mx  body: {"storeUuid": "..."}
    data.fareInfo.serviceFeeCents        -> costo de servicio en centavos (None sin login)
    data.catalogSectionsMap.*[].payload.standardItemsPayload.catalogItems[]
      .title                             -> nombre del producto
      .price                             -> precio en centavos (dividir / 100)

LIMITACION CONOCIDA — Delivery fee $0 para nuevos usuarios (promo confirmada):
  La pagina de tienda muestra "MXN0 delivery fee | new customers".
  Es una promo explicita para nuevos usuarios, NO el precio real de envio.
  El texto "new customers" aparece junto al valor en el HTML — marcador claro de promo.
  No refleja el costo real para usuarios existentes (tipicamente MXN 15-49 CDMX).

LIMITACION CONOCIDA — Service fee null requiere autenticacion:
  fareInfo.serviceFeeCents retorna null para sesiones guest.
  A diferencia del delivery fee, NO hay ningun texto "new customers" ni marcador de
  primera orden asociado al service fee — es una restriccion de autenticacion pura.
  Requiere --ubereats-email / --ubereats-password para obtener el valor real.
"""
import asyncio
import json
import re
from typing import Any

from playwright.async_api import BrowserContext, Page

from scrapers.base import ScraperBase, PRODUCTOS_OBJETIVO

PATRONES_INTERCEPCION = ["ubereats.com", "uber.com"]
RESTAURANTES_OBJETIVO = ["mcdonald", "burger king", "oxxo", "7-eleven", "seven eleven"]


class UberEatsScraper(ScraperBase):
    plataforma = "ubereats"
    _cache_precios: dict = {}  # nombre_restaurante_lower -> {"precio": float|None, "servicio": float|None}

    async def scrape_address(self, direccion: dict, contexto: BrowserContext) -> list[dict]:
        self._interceptadas.clear()
        await contexto.clear_cookies()
        pagina = await contexto.new_page()
        registros = []
        try:
            await self._establecer_geolocalizacion(contexto, direccion["lat"], direccion["lng"])
            self._configurar_intercepcion(pagina, PATRONES_INTERCEPCION)

            # LOGIN (futuro — Opcion B)
            # Si se proporcionan credenciales, aqui se realizaria el login:
            #   await self._login_ubereats(pagina, self.credenciales["email"], self.credenciales["password"])
            # Esto desbloquearia: delivery fee real (actualmente $0 por promo nuevos usuarios).

            await pagina.goto("https://www.ubereats.com/mx", wait_until="domcontentloaded", timeout=30000)
            await pagina.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch(e) {} }")
            await asyncio.sleep(6)
            registros = await self._raspar_con_direccion(pagina, direccion)
            self.save_intercepted()
        except Exception as e:
            self.log.error(f"UberEats error en {direccion['zone']}: {e}")
            rec = self._registro_base(direccion)
            rec["estado_scraping"] = "error"
            rec["mensaje_error"] = str(e)
            registros = [rec]
        finally:
            await pagina.close()
        return registros

    async def _raspar_con_direccion(self, pagina: Page, direccion: dict) -> list[dict]:
        try:
            boton_addr = pagina.locator(
                '[data-testid="address-display"], button:has-text("¿A dónde"), '
                'button:has-text("Entrega"), input[placeholder*="irección"]'
            ).first
            if await boton_addr.count() > 0:
                await boton_addr.click()
                await asyncio.sleep(1)
                campo = pagina.locator('input[type="text"], input[placeholder*="irección"]').first
                await campo.fill(direccion["address"][:60])
                await asyncio.sleep(2.5)
                sugerencia = pagina.locator('[data-testid="location-suggestion"], li[role="option"]').first
                if await sugerencia.count() > 0:
                    await sugerencia.click()
                    await asyncio.sleep(4)
        except Exception as e:
            self.log.debug(f"UE input direccion fallido (no critico): {e}")

        await self._scroll_humano(pagina, scrolls=5)
        await asyncio.sleep(5)

        registros = self._parsear_feed(direccion)
        if not registros:
            registros = await self._parsear_html_feed(pagina, direccion)

        if registros:
            snapshot_interceptadas = list(self._interceptadas)
            await self._enriquecer_tiendas(pagina, registros)
            self._interceptadas = snapshot_interceptadas

        return registros if registros else [self._registro_sin_datos(direccion)]

    def _parsear_feed(self, direccion: dict) -> list[dict]:
        registros = []
        for captura in self._interceptadas:
            if "getFeedV1" not in captura["url"]:
                continue
            try:
                feed_items = captura["body"]["data"]["feedItems"]
            except (KeyError, TypeError):
                continue

            for item in feed_items:
                carousel = item.get("carousel", {})
                for tienda in carousel.get("stores", []):
                    nombre = tienda.get("title", {})
                    nombre = nombre.get("text", "") if isinstance(nombre, dict) else str(nombre)
                    if not nombre or not any(t in nombre.lower() for t in RESTAURANTES_OBJETIVO):
                        continue

                    eta_min, eta_max = None, None
                    meta = tienda.get("meta", [])
                    if meta and isinstance(meta, list) and isinstance(meta[0], dict):
                        # accessibilityText tiene el rango completo: "Entrega en 10-26 min"
                        # text solo tiene el tiempo inicial: "10 min"
                        eta_texto = (
                            meta[0].get("accessibilityText", "")
                            or meta[0].get("text", "")
                        )
                        eta_min, eta_max = self._parsear_eta(eta_texto)

                    descuento_activo = False
                    descripcion_descuento = None
                    signposts = tienda.get("signposts", [])
                    if signposts:
                        descuento_activo = True
                        textos = [sp.get("text", "") for sp in signposts if isinstance(sp, dict)]
                        descripcion_descuento = ", ".join(t for t in textos if t)

                    rating_raw = tienda.get("rating", {})
                    calificacion = rating_raw.get("text", "") if isinstance(rating_raw, dict) else ""

                    rec = self._registro_base(direccion)
                    rec["nombre_restaurante"] = nombre
                    rec["tiempo_entrega_min"] = eta_min
                    rec["tiempo_entrega_max"] = eta_max
                    rec["descuento_activo"] = descuento_activo
                    rec["descripcion_descuento"] = descripcion_descuento
                    rec["restaurante_disponible"] = True
                    rec["vertical"] = self._detectar_vertical(nombre)
                    rec["calificacion"] = calificacion
                    rec["_action_url"] = tienda.get("actionUrl", "")
                    rec["_store_uuid"] = tienda.get("storeUuid", "")
                    registros.append(rec)

        # Deduplicar
        vistos: set = set()
        unicos = []
        for r in registros:
            clave = (r["id_direccion"], r["nombre_restaurante"])
            if clave not in vistos:
                vistos.add(clave)
                unicos.append(r)
        return unicos

    async def _enriquecer_tiendas(self, pagina: Page, registros: list[dict]):
        """
        Enriquecer cada tienda con costo de envio, costo de servicio y precio de producto.

        Estrategia:
          1. Llamar POST /_p/api/getStoreV1 con storeUuid para obtener:
             - fareInfo.serviceFeeCents  -> costo_servicio (None sin login)
             - catalogSectionsMap        -> precio producto en centavos (mas confiable)
          2. Navegar a la pagina de tienda como fallback para costo de envio (HTML)
        """
        contexto = pagina.context

        for rec in registros:
            action_url = rec.pop("_action_url", None)
            store_uuid = rec.pop("_store_uuid", None)

            nombre_rest = rec.get("nombre_restaurante", "").lower()
            producto_objetivo = next(
                (prod for clave, prod in PRODUCTOS_OBJETIVO.items() if clave in nombre_rest),
                None,
            )

            try:
                # ── Llamada API getStoreV1 ─────────────────────────────────
                if store_uuid:
                    clave_cache = store_uuid
                    if clave_cache in UberEatsScraper._cache_precios:
                        cached = UberEatsScraper._cache_precios[clave_cache]
                        rec["precio_producto"] = cached.get("precio")
                        rec["costo_servicio"] = cached.get("servicio")
                        rec["nombre_producto"] = producto_objetivo
                    else:
                        precio, svc_fee = await self._capturar_store_api(
                            contexto, store_uuid, producto_objetivo
                        )
                        UberEatsScraper._cache_precios[clave_cache] = {
                            "precio": precio, "servicio": svc_fee
                        }
                        rec["nombre_producto"] = producto_objetivo
                        rec["precio_producto"] = precio
                        rec["costo_servicio"] = svc_fee

                # ── Pagina de tienda: delivery fee + fallback precio ───────
                if not action_url:
                    continue

                self._interceptadas.clear()
                await pagina.goto(
                    f"https://www.ubereats.com{action_url}",
                    wait_until="domcontentloaded",
                    timeout=25000,
                )
                await asyncio.sleep(5)
                await self._scroll_humano(pagina, scrolls=3)
                await asyncio.sleep(3)

                texto_pagina = await pagina.inner_text("body")

                # Costo de envio — desde API interceptada
                for captura in self._interceptadas:
                    tarifa = self._extraer_tarifa_de_cuerpo(captura["body"])
                    if tarifa is not None:
                        rec["costo_envio"] = tarifa
                        break

                # Costo de envio — fallback HTML "MXN0 delivery fee"
                if rec["costo_envio"] is None:
                    mxn_fees = re.findall(
                        r'MXN\s*(\d+(?:\.\d+)?)\s*delivery fee',
                        texto_pagina,
                        re.IGNORECASE,
                    )
                    if mxn_fees:
                        rec["costo_envio"] = float(mxn_fees[0])
                    else:
                        esp = re.findall(r'\$\s*(\d+(?:\.\d+)?)\s*(?:de\s+)?env[íi]o', texto_pagina, re.IGNORECASE)
                        if not esp:
                            esp = re.findall(r'env[íi]o\s*\$\s*(\d+(?:\.\d+)?)', texto_pagina, re.IGNORECASE)
                        if esp:
                            rec["costo_envio"] = float(esp[0])

                # Fallback precio desde HTML si la API no lo dio
                if rec.get("precio_producto") is None and producto_objetivo:
                    precio_html = self._precio_desde_texto_ue(texto_pagina, producto_objetivo)
                    if precio_html is not None:
                        rec["precio_producto"] = precio_html
                        clave_cache = nombre_rest
                        UberEatsScraper._cache_precios[clave_cache] = {
                            "precio": precio_html,
                            "servicio": rec.get("costo_servicio"),
                        }
                        self.log.info(
                            f"UE HTML fallback: {producto_objetivo} = MX${precio_html} ({rec['nombre_restaurante']})"
                        )

            except Exception as e:
                self.log.debug(f"UE enriquecimiento tienda fallido: {e}")
            finally:
                rec.pop("_action_url", None)
                rec.pop("_store_uuid", None)

        # Limpiar campos temporales restantes
        for rec in registros:
            rec.pop("_action_url", None)
            rec.pop("_store_uuid", None)

    async def _capturar_store_api(
        self,
        contexto: BrowserContext,
        store_uuid: str,
        producto_objetivo: str | None,
    ) -> tuple[float | None, float | None]:
        """
        Llama POST /_p/api/getStoreV1 y retorna (precio_producto, costo_servicio_cents/100).

        Campos extraidos:
          - data.fareInfo.serviceFeeCents  -> costo de servicio (None sin login)
          - data.catalogSectionsMap        -> precios de productos en centavos
        """
        try:
            resp = await contexto.request.post(
                "https://www.ubereats.com/_p/api/getStoreV1?localeCode=mx",
                headers={
                    "content-type": "application/json",
                    "x-csrf-token": "x",
                    "referer": "https://www.ubereats.com/mx",
                    "accept": "application/json",
                },
                data=json.dumps({"storeUuid": store_uuid}),
            )
            if not resp.ok:
                return None, None

            cuerpo = await resp.json()
            data = cuerpo.get("data", cuerpo) if isinstance(cuerpo, dict) else {}

            # Costo de servicio
            fare_info = data.get("fareInfo") or {}
            svc_cents = fare_info.get("serviceFeeCents") if isinstance(fare_info, dict) else None
            costo_servicio = float(svc_cents) / 100 if svc_cents is not None else None

            # Precio de producto desde catalogSectionsMap
            precio = None
            if producto_objetivo:
                precio = self._precio_desde_catalog(data, producto_objetivo)
                if precio is not None:
                    self.log.info(
                        f"UE API: {producto_objetivo} = MX${precio} | "
                        f"costo_servicio={costo_servicio} (tienda {store_uuid[:8]})"
                    )

            return precio, costo_servicio

        except Exception as e:
            self.log.debug(f"UE getStoreV1 error ({store_uuid[:8]}): {e}")
            return None, None

    def _precio_desde_catalog(self, data: dict, producto_objetivo: str) -> float | None:
        """
        Extraer precio del producto desde catalogSectionsMap de getStoreV1.
        Los precios vienen en centavos (ej. 14400 = MXN$144).
        Retorna el precio mas bajo del producto objetivo (standalone, no combo).
        """
        nombre_lower = producto_objetivo.lower()
        catalog = data.get("catalogSectionsMap", {})
        candidatos: list[float] = []

        for section_list in catalog.values():
            if not isinstance(section_list, list):
                continue
            for section in section_list:
                payload = section.get("payload", {}) if isinstance(section, dict) else {}
                items = payload.get("standardItemsPayload", {}).get("catalogItems", [])
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    titulo = (item.get("title") or "").lower()
                    if nombre_lower in titulo:
                        precio_cents = item.get("price")
                        if precio_cents and isinstance(precio_cents, (int, float)):
                            precio = float(precio_cents) / 100
                            if 10 <= precio <= 2000:
                                candidatos.append(precio)

        return min(candidatos) if candidatos else None

    def _precio_desde_texto_ue(self, texto: str, producto_objetivo: str) -> float | None:
        """
        Patron UberEats en pagina de tienda:
          [nombre_producto]
          MX$[precio]
          [descripcion]
        """
        lineas = [l.strip() for l in texto.split("\n") if l.strip()]
        nombre_lower = producto_objetivo.lower()
        for i, linea in enumerate(lineas):
            if nombre_lower in linea.lower() and len(linea) < 60:
                # Buscar precio en lineas siguientes
                for j in range(i + 1, min(i + 4, len(lineas))):
                    match = re.search(r'MX\$\s*(\d+(?:\.\d+)?)', lineas[j])
                    if match:
                        try:
                            val = float(match.group(1))
                            if 10 <= val <= 2000:
                                return val
                        except ValueError:
                            pass
                    # Formato alternativo: "$XXX" o "$ XXX"
                    match2 = re.search(r'^\$\s*(\d+(?:\.\d+)?)', lineas[j])
                    if match2:
                        try:
                            val = float(match2.group(1))
                            if 10 <= val <= 2000:
                                return val
                        except ValueError:
                            pass
        return None

    def _extraer_tarifa_de_cuerpo(self, cuerpo: Any) -> float | None:
        def buscar_tarifa(obj):
            if isinstance(obj, dict):
                if "fareInfo" in obj:
                    fare = obj["fareInfo"]
                    if isinstance(fare, dict):
                        for k in ("price", "displayString", "priceStr"):
                            if k in fare:
                                return self._precio_seguro(fare[k])
                for v in obj.values():
                    r = buscar_tarifa(v)
                    if r is not None:
                        return r
            elif isinstance(obj, list):
                for elem in obj:
                    r = buscar_tarifa(elem)
                    if r is not None:
                        return r
            return None
        return buscar_tarifa(cuerpo)

    async def _parsear_html_feed(self, pagina: Page, direccion: dict) -> list[dict]:
        registros = []
        try:
            tarjetas = await pagina.query_selector_all(
                '[data-testid="store-card"], [class*="StoreCard"], [class*="store-card"]'
            )
            for tarjeta in tarjetas[:30]:
                try:
                    el_nombre = await tarjeta.query_selector("h3, [class*='storeName'], [class*='title']")
                    nombre = (await el_nombre.inner_text()).strip() if el_nombre else ""
                    if not nombre or not any(t in nombre.lower() for t in RESTAURANTES_OBJETIVO):
                        continue
                    rec = self._registro_base(direccion)
                    rec["nombre_restaurante"] = nombre
                    el_eta = await tarjeta.query_selector("[class*='eta'], [class*='time']")
                    if el_eta:
                        rec["tiempo_entrega_min"], rec["tiempo_entrega_max"] = self._parsear_eta(
                            await el_eta.inner_text()
                        )
                    rec["vertical"] = self._detectar_vertical(nombre)
                    registros.append(rec)
                except Exception:
                    continue
        except Exception as e:
            self.log.debug(f"UE fallback HTML error: {e}")
        return registros

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _precio_seguro(self, valor: Any) -> float | None:
        if valor is None:
            return None
        if isinstance(valor, (int, float)):
            val = float(valor)
            return val / 100 if val > 1000 else val
        limpio = re.sub(r"[^\d.]", "", str(valor))
        try:
            return float(limpio) if limpio else None
        except ValueError:
            return None

    def _parsear_eta(self, texto: str) -> tuple[int | None, int | None]:
        nums = re.findall(r"\d+", str(texto))
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            v = int(nums[0])
            return v, v
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
