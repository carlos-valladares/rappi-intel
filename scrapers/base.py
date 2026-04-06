"""
Clase base de scraping con stealth, reintentos e intercepcion de red.
Todos los scrapers de plataforma heredan de esta clase.
"""
import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page, Response
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configuracion de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)

AGENTES_USUARIO = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

DIRECTORIO_DATOS = Path("data/raw")
DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)

# Productos objetivo por tipo de restaurante
PRODUCTOS_OBJETIVO = {
    "mcdonald": "Big Mac",
    "burger king": "Whopper",
    "carl's jr": "Famous Star",
    "carl jr": "Famous Star",
    "oxxo": "Coca-Cola",
    "7-eleven": "Coca-Cola",
    "seven eleven": "Coca-Cola",
}


class ScraperBase(ABC):
    """
    Clase base abstracta para todos los scrapers de plataforma.
    Gestiona: ciclo de vida del browser, stealth, geolocalizacion,
    rate limiting, reintentos con backoff y logging estandarizado.
    Las subclases solo implementan `scrape_address`.
    """

    plataforma: str = "base"

    def __init__(
        self,
        headless: bool = True,
        proxy_url: str | None = None,
        rate_limit_seconds: tuple[float, float] = (2.0, 5.0),
        credenciales: dict | None = None,
    ):
        self.headless = headless
        self.proxy_url = proxy_url
        self.rate_limit = rate_limit_seconds
        self.credenciales = credenciales or {}  # {"email": ..., "password": ...}
        self.log = logging.getLogger(self.__class__.__name__)
        self.resultados: list[dict] = []
        self._interceptadas: list[dict] = []  # Respuestas API capturadas

    # ── Gestion del browser ───────────────────────────────────────────────────

    async def _construir_contexto(self, playwright) -> BrowserContext:
        """Lanza el browser con configuracion de stealth anti-deteccion."""
        opciones_lanzamiento: dict[str, Any] = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,800",
            ],
        }
        if self.proxy_url:
            opciones_lanzamiento["proxy"] = {"server": self.proxy_url}

        browser = await playwright.chromium.launch(**opciones_lanzamiento)

        contexto = await browser.new_context(
            user_agent=random.choice(AGENTES_USUARIO),
            viewport={"width": 1280, "height": 800},
            locale="es-MX",
            timezone_id="America/Mexico_City",
            extra_http_headers={
                "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        # Stealth: sobreescribir propiedades del navegador detectables por bots
        await contexto.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-MX', 'es', 'en'] });
            window.chrome = { runtime: {} };
        """)

        return contexto

    async def _establecer_geolocalizacion(self, contexto: BrowserContext, lat: float, lng: float):
        """Establece la geolocalizacion del browser para simular la direccion."""
        await contexto.set_geolocation({"latitude": lat, "longitude": lng})
        await contexto.grant_permissions(["geolocation"])

    async def _espera_aleatoria(self):
        """Pausa aleatoria entre requests para simular comportamiento humano."""
        espera = random.uniform(*self.rate_limit)
        await asyncio.sleep(espera)

    async def _scroll_humano(self, pagina: Page, scrolls: int = 3):
        """Simula scroll humano para activar lazy loading de contenido."""
        for _ in range(scrolls):
            await pagina.mouse.wheel(0, random.randint(300, 700))
            await asyncio.sleep(random.uniform(0.3, 0.8))

    # ── Intercepcion de red ───────────────────────────────────────────────────

    def _configurar_intercepcion(self, pagina: Page, patrones_url: list[str]):
        """Captura respuestas JSON de la API que coincidan con los patrones dados."""

        async def manejar_respuesta(respuesta: Response):
            try:
                if any(pat in respuesta.url for pat in patrones_url):
                    tipo_contenido = respuesta.headers.get("content-type", "")
                    if "json" in tipo_contenido or "javascript" in tipo_contenido:
                        cuerpo = await respuesta.json()
                        self._interceptadas.append({
                            "url": respuesta.url,
                            "status": respuesta.status,
                            "body": cuerpo,
                            "marca_tiempo": datetime.utcnow().isoformat(),
                        })
                        self.log.debug(f"Interceptada: {respuesta.url[:80]}")
            except Exception as e:
                self.log.debug(f"Error al parsear intercepcion: {e}")

        pagina.on("response", manejar_respuesta)

    # ── Construccion de registros ─────────────────────────────────────────────

    def _registro_base(self, direccion: dict) -> dict:
        """Retorna un registro plantilla con todos los campos estandarizados en espanol."""
        return {
            "marca_tiempo": datetime.utcnow().isoformat(),
            "plataforma": self.plataforma,
            "id_direccion": direccion["id"],
            "zona": direccion["zone"],
            "tipo_zona": direccion["zone_type"],
            "direccion": direccion["address"],
            "lat": direccion["lat"],
            "lng": direccion["lng"],
            "nombre_restaurante": None,
            "vertical": None,
            "nombre_producto": None,
            "precio_producto": None,
            "costo_envio": None,
            "costo_servicio": None,
            "tiempo_entrega_min": None,
            "tiempo_entrega_max": None,
            "descuento_activo": False,
            "descripcion_descuento": None,
            "restaurante_disponible": None,
            "calificacion": None,
            "estado_scraping": "ok",
            "mensaje_error": None,
        }

    # ── Reintento con backoff ─────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _scrape_con_reintento(self, direccion: dict, contexto: BrowserContext) -> list[dict]:
        """Envuelve scrape_address con logica de reintento automatico (hasta 3 intentos)."""
        return await self.scrape_address(direccion, contexto)

    # ── Punto de entrada principal ────────────────────────────────────────────

    async def run(self, direcciones: list[dict]) -> list[dict]:
        """Ejecuta el scraper sobre una lista de direcciones secuencialmente."""
        self.log.info(f"Iniciando scraper '{self.plataforma}' — {len(direcciones)} direcciones")
        inicio = time.time()

        async with async_playwright() as p:
            contexto = await self._construir_contexto(p)
            try:
                for i, direccion in enumerate(direcciones, 1):
                    self.log.info(
                        f"[{i}/{len(direcciones)}] {self.plataforma} — "
                        f"{direccion['zone']} ({direccion['address'][:50]}...)"
                    )
                    try:
                        registros = await self._scrape_con_reintento(direccion, contexto)
                        self.resultados.extend(registros)
                        self.log.info(f"  OK {len(registros)} registros")
                    except Exception as e:
                        self.log.error(f"  FALLO despues de reintentos: {e}")
                        rec = self._registro_base(direccion)
                        rec["estado_scraping"] = "fallido"
                        rec["mensaje_error"] = str(e)
                        self.resultados.append(rec)

                    await self._espera_aleatoria()

            finally:
                await contexto.browser.close()

        elapsed = time.time() - inicio
        self.log.info(
            f"Finalizado '{self.plataforma}': {len(self.resultados)} registros en {elapsed:.0f}s"
        )
        return self.resultados

    # ── Metodo abstracto ──────────────────────────────────────────────────────

    @abstractmethod
    async def scrape_address(self, direccion: dict, contexto: BrowserContext) -> list[dict]:
        """
        Implementa la logica de scraping especifica de la plataforma.
        Debe retornar una lista de registros normalizados (usar _registro_base como plantilla).
        """
        ...

    # ── Persistencia ──────────────────────────────────────────────────────────

    def guardar_csv(self) -> Path:
        """Guarda los resultados en un archivo CSV con timestamp."""
        import csv
        if not self.resultados:
            self.log.warning("Sin resultados para guardar.")
            return None

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        ruta = DIRECTORIO_DATOS / f"{self.plataforma}_{ts}.csv"

        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            escritor = csv.DictWriter(f, fieldnames=self.resultados[0].keys())
            escritor.writeheader()
            escritor.writerows(self.resultados)

        self.log.info(f"CSV guardado: {len(self.resultados)} filas -> {ruta}")
        return ruta

    def guardar_interceptadas(self) -> Path:
        """Guarda las respuestas API interceptadas en JSON para debug."""
        if not self._interceptadas:
            return None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        ruta = DIRECTORIO_DATOS / f"{self.plataforma}_raw_{ts}.json"
        ruta.write_text(
            json.dumps(self._interceptadas, indent=2, ensure_ascii=True),
            encoding="utf-8"
        )
        self.log.info(f"JSON raw guardado: {len(self._interceptadas)} capturas -> {ruta}")
        return ruta

    # Alias para compatibilidad con main.py
    def save_csv(self) -> Path:
        return self.guardar_csv()

    def save_intercepted(self) -> Path:
        return self.guardar_interceptadas()
