"""
Rappi Competitive Intelligence -- Main Entry Point
Usage:
    python main.py                          # full run, all platforms, all addresses
    python main.py --platform ubereats      # single platform
    python main.py --addresses 5            # first N addresses only (quick test)
    python main.py --headless false         # show browser
    python main.py --report-only            # skip scraping, regenerate report
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scrapers.ubereats import UberEatsScraper
from scrapers.didifood import DidiScraper
from scrapers.rappi import RappiScraper
from storage.db import ingest_dataframe, summary
from analysis.report import generate_html_report, load_data

console = Console(highlight=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/scraper.log", mode="a", encoding="utf-8"),
    ],
)

SCRAPERS = {
    "ubereats": UberEatsScraper,
    "didifood": DidiScraper,
    "rappi": RappiScraper,
}


def load_addresses(limit: int | None = None) -> list[dict]:
    path = Path("config/addresses.json")
    addresses = json.loads(path.read_text(encoding="utf-8"))
    if limit:
        addresses = addresses[:limit]
    return addresses


def print_banner():
    console.print("\n[bold red]Rappi Competitive Intelligence System[/bold red]")
    console.print("[dim]Scraping Rappi vs Uber Eats vs DiDi Food - CDMX[/dim]\n")


def print_summary(all_results: list[dict]):
    df = pd.DataFrame(all_results)
    table = Table(title="Resumen de Scraping", show_header=True, header_style="bold red")
    table.add_column("Plataforma", style="bold")
    table.add_column("Total Registros")
    table.add_column("OK")
    table.add_column("Fallidos")
    table.add_column("Zonas")

    for plataforma in df["plataforma"].unique():
        p_df = df[df["plataforma"] == plataforma]
        ok = len(p_df[p_df["estado_scraping"] == "ok"])
        fallidos = len(p_df[p_df["estado_scraping"] != "ok"])
        zonas = p_df["zona"].nunique()
        table.add_row(plataforma, str(len(p_df)), f"[green]{ok}[/green]", f"[red]{fallidos}[/red]", str(zonas))

    console.print(table)


def _resolver_credenciales(args, plataforma: str) -> dict | None:
    """
    Resuelve credenciales para una plataforma con la siguiente prioridad:
      1. --[plataforma]-email / --[plataforma]-password  (especifico)
      2. --email / --password                            (global)
      3. None                                             (sin credenciales)
    """
    email = getattr(args, f"{plataforma}_email", None) or getattr(args, "email", None)
    password = getattr(args, f"{plataforma}_password", None) or getattr(args, "password", None)
    if email and password:
        return {"email": email, "password": password}
    return None


async def run_scraper(
    platform_name: str,
    addresses: list[dict],
    headless: bool = True,
    proxy_url: str | None = None,
    credenciales: dict | None = None,
) -> list[dict]:
    ScraperClass = SCRAPERS[platform_name]
    scraper = ScraperClass(headless=headless, proxy_url=proxy_url, credenciales=credenciales)
    results = await scraper.run(addresses)
    csv_path = scraper.save_csv()
    scraper.save_intercepted()
    return results


async def main(args):
    print_banner()

    # Load addresses
    addresses = load_addresses(limit=args.addresses)
    console.print(f"[bold]Addresses:[/bold] {len(addresses)} zones selected")

    # Determine platforms to scrape
    platforms = [args.platform] if args.platform else list(SCRAPERS.keys())
    console.print(f"[bold]Platforms:[/bold] {', '.join(platforms)}\n")

    # Load proxy if set
    proxy_url = None
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        proxy_url = os.getenv("PROXY_URL")
        if proxy_url:
            console.print(f"[dim]Using proxy: {proxy_url[:30]}...[/dim]")
    except ImportError:
        pass

    all_results: list[dict] = []
    start = time.time()

    for platform in platforms:
        console.rule(f"[bold red]{platform.upper()}[/bold red]")
        try:
            creds = _resolver_credenciales(args, platform)
            results = await run_scraper(
                platform,
                addresses,
                headless=(args.headless.lower() != "false"),
                proxy_url=proxy_url,
                credenciales=creds,
            )
            all_results.extend(results)
            console.print(f"[green]OK[/green] {platform}: {len(results)} records")
        except Exception as e:
            console.print(f"[red]FAIL[/red] {platform} failed: {e}")
            logging.exception(f"Platform {platform} crashed")

    if not all_results:
        console.print("\n[red]No data collected. Check logs at data/scraper.log[/red]")
        return

    # Store in DuckDB
    df = pd.DataFrame(all_results)
    ingest_dataframe(df)
    console.print(f"\n[green]OK[/green] Data stored in DuckDB")

    # Summary table
    print_summary(all_results)

    # Generate report
    console.print("\n[bold]Generating report...[/bold]")
    try:
        report_path = generate_html_report(df)
        console.print(f"[green]OK[/green] Report: {report_path}")
    except Exception as e:
        console.print(f"[yellow]WARN[/yellow] Report generation failed: {e}")

    elapsed = time.time() - start
    console.print(f"\n[bold green]Done in {elapsed:.0f}s[/bold green]")
    console.print(f"Raw data: [dim]data/raw/[/dim]")
    console.print(f"Report:   [dim]data/report.html[/dim]\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Rappi Competitive Intelligence Scraper",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--platform", choices=list(SCRAPERS.keys()), help="Scrape a single platform")
    parser.add_argument("--addresses", type=int, default=None, help="Limit to first N addresses")
    parser.add_argument("--headless", default="true", help="Show browser: true/false")
    parser.add_argument("--report-only", action="store_true", help="Skip scraping, regenerate report only")

    # Credenciales globales (aplican a todas las plataformas si no hay especificas)
    creds_group = parser.add_argument_group(
        "credenciales",
        "Cuenta de usuario por plataforma.\n"
        "Usar --email/--password para todas, o --[plataforma]-email para una especifica.\n"
        "Si no se proporcionan para una plataforma, el sistema continua sin autenticacion.\n"
        "Ejemplo: python main.py --didifood-email yo@mail.com --didifood-password 1234",
    )
    creds_group.add_argument("--email", metavar="EMAIL", help="Email para todas las plataformas")
    creds_group.add_argument("--password", metavar="PASS", help="Password para todas las plataformas")
    creds_group.add_argument("--rappi-email", metavar="EMAIL", dest="rappi_email")
    creds_group.add_argument("--rappi-password", metavar="PASS", dest="rappi_password")
    creds_group.add_argument("--didifood-email", metavar="EMAIL", dest="didifood_email")
    creds_group.add_argument("--didifood-password", metavar="PASS", dest="didifood_password")
    creds_group.add_argument("--ubereats-email", metavar="EMAIL", dest="ubereats_email")
    creds_group.add_argument("--ubereats-password", metavar="PASS", dest="ubereats_password")

    args = parser.parse_args()

    if args.report_only:
        df = load_data()
        if df.empty:
            console.print("[red]No data found. Run scraper first.[/red]")
        else:
            path = generate_html_report(df)
            console.print(f"[green]OK[/green] Report: {path}")
    else:
        asyncio.run(main(args))
