"""
DiDi Food scraper — CDMX
Dominio activo: web.didiglobal.com/mx/food/

ARQUITECTURA:
  DiDi Food opera en Mexico a traves de una app + web marketing SSR (Next.js).
  La web es un portal de marketing sin API de pedidos ni paginas de tienda
  individuales con menu. Todos los links de restaurante abren la app movil
  (didi-food.com/es-MX/store?...).

DATOS DISPONIBLES EN LA WEB:
    - Listado de restaurantes a nivel ciudad (no por zona)
    - Rating por restaurante

LIMITACIONES TECNICAS DOCUMENTADAS (datos = None):
    - costo_envio / costo_servicio: requiere wsgsig de la app
    - tiempo_entrega_min / max: requiere wsgsig de la app
    - precio_producto: la web no tiene paginas individuales con menu

ESTRATEGIA DE SCRAPING:
  1. Navegar a paginas de categoria (hamburguesas) de CDMX
  2. Parsear HTML SSR: nombre restaurante, rating
  3. Ejecutar UNA sola vez por corrida (datos son ciudad-CDMX, no por zona)
  4. Las direcciones posteriores retornan lista vacia (datos ya capturados)

NOTA SOBRE ZONAS:
  DiDi Food web no expone datos por zona ni por coordenada.
  El catalogo es a nivel ciudad. Generar 1 registro por restaurante por ejecucion
  evita duplicar los mismos datos en las 25 zonas.
"""
import asyncio
import re
from typing import Any

from playwright.async_api import BrowserContext, Page

from scrapers.base import ScraperBase, PRODUCTOS_OBJETIVO

URLS_CATEGORIA = [
    "https://web.didiglobal.com/mx/food/ciudad-de-mexico-cdmx/categoria/hamburguesas/",
    "https://web.didiglobal.com/mx/food/ciudad-de-mexico-cdmx/categoria/abarrotes/",
]

RESTAURANTES_OBJETIVO = ["mcdonald", "burger king", "oxxo", "7-eleven", "seven eleven"]

# Palabras de UI de DiDi que actuan como separadores en el HTML SSR
CATEGORIAS_DIDI = {
    "hamburguesas", "pizza", "mexicana", "americana", "tacos", "pollo", "alitas",
    "sushi", "asiatica", "sandwich", "tortas", "postres", "helados", "bebidas",
    "abarrotes", "carne", "cafe", "italiana", "latinoamericana", "fideos",
    "pasaboca", "panes",
}


class DidiScraper(ScraperBase):
    plataforma = "didifood"

    # Cache ciudad: scraping se ejecuta solo una vez por corrida (datos son ciudad-CDMX)
    _cache_ciudad: list[dict] | None = None

    async def scrape_address(self, direccion: dict, contexto: BrowserContext) -> list[dict]:
        # Si ya se hizo el scraping en esta corrida, no duplicar datos
        if DidiScraper._cache_ciudad is not None:
            self.log.debug(
                f"DiDi: datos ciudad ya capturados ({len(DidiScraper._cache_ciudad)} restaurantes). "
                f"Omitiendo {direccion['zone']} — DiDi web no tiene datos por zona."
            )
            return []

        # Primera ejecucion: advertir sobre limitaciones
        if not self.credenciales:
            self.log.warning(
                "DiDi Food: sin credenciales. Se capturan nombre y rating (web publica). "
                "Para fees, ETAs y precios de producto, proporcionar cuenta: "
                "--didifood-email <email> --didifood-password <pass>"
            )

        # Primera ejecucion: scraper la ciudad completa
        pagina = await contexto.new_page()
        restaurantes_ciudad = []
        try:
            await self._establecer_geolocalizacion(contexto, direccion["lat"], direccion["lng"])

            # LOGIN (futuro — Opcion B)
            # Si se proporcionan credenciales, aqui se realizaria el login antes de scraping:
            #   await self._login_didi(pagina, self.credenciales["email"], self.credenciales["password"])
            # Esto desbloquearia: fees, ETAs, precios de producto, disponibilidad por zona.
            if self.credenciales:
                self.log.info(
                    f"DiDi Food: credenciales recibidas para {self.credenciales.get('email')}. "
                    "Login automatico no implementado aun (Opcion B pendiente)."
                )

            for url_cat in URLS_CATEGORIA:
                encontrados = await self._scraper_pagina_categoria(pagina, url_cat)
                restaurantes_ciudad.extend(encontrados)
                await asyncio.sleep(1.5)
        except Exception as e:
            self.log.error(f"DiDi error scraping ciudad: {e}")
        finally:
            await pagina.close()

        # Deduplicar por nombre
        vistos: set = set()
        unicos = []
        for r in restaurantes_ciudad:
            if r["nombre_restaurante"] not in vistos:
                vistos.add(r["nombre_restaurante"])
                unicos.append(r)

        DidiScraper._cache_ciudad = unicos
        self.log.info(f"DiDi: {len(unicos)} restaurantes objetivo capturados (catalogo CDMX — dato unico por corrida)")

        if not unicos:
            rec = self._registro_base(direccion)
            rec["estado_scraping"] = "sin_datos"
            rec["mensaje_error"] = "No se encontraron restaurantes objetivo en DiDi Food CDMX web"
            return [rec]

        # Asignar a la primera direccion (catalogo es ciudad-CDMX, no por zona)
        return self._asignar_direccion(unicos, direccion)

    async def _scraper_pagina_categoria(self, pagina: Page, url: str) -> list[dict]:
        """
        Scraper una pagina de categoria de DiDi Food.
        NOTA: DiDi no expone paginas individuales de restaurante en el web.
        Todos los links de tarjeta redirigen a la app movil.
        Solo se extraen: nombre de restaurante y rating del HTML SSR.
        """
        restaurantes = []
        try:
            self.log.info(f"DiDi: scraping {url}")
            await pagina.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(4)

            for _ in range(8):
                await pagina.mouse.wheel(0, 700)
                await asyncio.sleep(0.4)
            await asyncio.sleep(2)

            texto = await pagina.inner_text("body")
            lineas = [l.strip() for l in texto.split("\n") if l.strip()]
            restaurantes_basicos = self._parsear_lineas_restaurante(lineas)

            # Asignar producto objetivo por restaurante (precio = None — app-only)
            for r in restaurantes_basicos:
                nombre_lower = r["nombre_restaurante"].lower()
                producto_objetivo = next(
                    (prod for clave, prod in PRODUCTOS_OBJETIVO.items() if clave in nombre_lower),
                    None,
                )
                r["nombre_producto"] = producto_objetivo
                r["precio_producto"] = None  # No disponible en web de DiDi
                restaurantes.append(r)

            self.log.info(f"DiDi {url.split('/')[-2]}: {len(restaurantes)} restaurantes objetivo")

        except Exception as e:
            self.log.warning(f"DiDi error en categoria ({url}): {e}")

        return restaurantes

    def _parsear_lineas_restaurante(self, lineas: list[str]) -> list[dict]:
        """
        Parsear listado SSR de DiDi Food.
        Patron:
          [Nombre Restaurante]  <- contiene target keyword
          [Direccion opcional]
          [Rating: "4.2"]
        """
        restaurantes = []
        i = 0
        while i < len(lineas):
            linea = lineas[i]
            if any(t in linea.lower() for t in RESTAURANTES_OBJETIVO):
                nombre = linea
                rating_val = None
                for j in range(i + 1, min(i + 6, len(lineas))):
                    sig = lineas[j]
                    if re.match(r"^\d(\.\d)?$", sig):
                        rating_val = float(sig)
                        break

                restaurantes.append({
                    "nombre_restaurante": nombre,
                    "calificacion": rating_val,
                    "vertical": self._detectar_vertical(nombre),
                    "nombre_producto": None,
                    "precio_producto": None,
                })
            i += 1
        return restaurantes

    def _asignar_direccion(self, restaurantes_ciudad: list[dict], direccion: dict) -> list[dict]:
        """Generar registros completos asignando datos de ciudad a una direccion especifica."""
        registros = []
        for r in restaurantes_ciudad:
            rec = self._registro_base(direccion)
            rec["nombre_restaurante"] = r["nombre_restaurante"]
            rec["restaurante_disponible"] = True
            rec["calificacion"] = r.get("calificacion")
            rec["costo_envio"] = None       # Solo disponible en app
            rec["costo_servicio"] = None    # Solo disponible en app
            rec["tiempo_entrega_min"] = None  # Solo disponible en app
            rec["tiempo_entrega_max"] = None  # Solo disponible en app
            rec["vertical"] = r.get("vertical", "fast_food")
            rec["descuento_activo"] = False
            rec["nombre_producto"] = r.get("nombre_producto")
            rec["precio_producto"] = r.get("precio_producto")
            rec["estado_scraping"] = "ok"
            registros.append(rec)
        return registros

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detectar_vertical(self, nombre: str) -> str:
        nombre_lower = nombre.lower()
        if any(x in nombre_lower for x in ["oxxo", "7-eleven", "seven eleven", "walmart",
                                            "chedraui", "soriana", "bodega"]):
            return "retail"
        return "fast_food"
