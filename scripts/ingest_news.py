#!/usr/bin/env python3
"""
Pipeline de ingesta de novedades del sector para RichAds Digital Marketing.

Lee feeds RSS de fuentes clave de SEA / SEO / tracking, filtra las entradas
de las ultimas 24 horas, las resume y clasifica con la API de Claude, y
escribe un documento markdown por dia en conocimiento/novedades/.

La clave de API se lee de la variable de entorno ANTHROPIC_API_KEY,
que en GitHub Actions viene del secreto del repo. Nunca va en el codigo.
"""

import os
import sys
import json
import datetime as dt
from pathlib import Path
from email.utils import parsedate_to_datetime

import feedparser
import requests

# ─────────────────────────────────────────────────────────────
# CONFIGURACION
# ─────────────────────────────────────────────────────────────

# Modelo del pipeline: Haiku es suficiente para resumir y abarata el coste.
# El trabajo de diagnostico se hace aparte con un modelo superior.
MODEL = "claude-haiku-4-5-20251001"

# Ventana de tiempo: entradas publicadas en las ultimas N horas.
# 26h (no 24) da margen para desfases de hora de ejecucion y husos.
LOOKBACK_HOURS = 26

# Fuentes. Anadir o quitar aqui. Cada una necesita un feed RSS valido.
FUENTES = [
    {"nombre": "Google Ads & Commerce Blog", "url": "https://blog.google/products/ads-commerce/rss/", "area": "SEA"},
    {"nombre": "Search Engine Land", "url": "https://searchengineland.com/feed", "area": "SEA/SEO"},
    {"nombre": "Search Engine Roundtable", "url": "https://www.seroundtable.com/index.xml", "area": "SEA/SEO"},
    {"nombre": "Simo Ahava", "url": "https://www.simoahava.com/rss.xml", "area": "Tracking/GTM"},
    {"nombre": "Google Analytics Blog", "url": "https://blog.google/products/marketingplatform/analytics/rss/", "area": "Tracking"},
]

API_URL = "https://api.anthropic.com/v1/messages"

# Prompt de resumen, calibrado a criterio de consultor senior.
SYSTEM_PROMPT = """Eres el analista de novedades de un consultor senior de marketing digital (SEA, SEO, tracking) que trabaja mercados DACH, Espana y UK.

Tu tarea: resumir una novedad del sector para que el consultor decida en 10 segundos si le afecta y que hacer.

Reglas:
- Se preciso y tecnico. Nada de relleno ni entusiasmo de marketing.
- Si la novedad es un cambio de producto de Google Ads / GA4 / plataformas, explica QUE cambia y QUE implicacion operativa tiene.
- Distingue entre novedad relevante (cambio real de plataforma, feature, politica) y ruido (opinion, recopilatorio, promocion). Marca el nivel de relevancia.
- Si detectas que algo deja obsoleta una practica anterior, dilo explicitamente.
- Responde SOLO con el JSON pedido, sin texto adicional ni backticks."""

USER_TEMPLATE = """Novedad a resumir:

Titulo: {titulo}
Fuente: {fuente} ({area})
Fecha: {fecha}
Extracto: {resumen}

Devuelve exactamente este JSON:
{{
  "relevancia": "alta" | "media" | "baja",
  "titular": "una frase clara de que ha pasado",
  "implicacion": "que implica operativamente para el consultor, o 'ninguna' si es ruido",
  "obsolescencia": "que practica anterior queda obsoleta, o '-' si ninguna",
  "area": "SEA" | "SEO" | "Tracking" | "General"
}}"""


# ─────────────────────────────────────────────────────────────
# LOGICA
# ─────────────────────────────────────────────────────────────

def entrada_reciente(entry, limite):
    """True si la entrada se publico despues del limite temporal."""
    fecha = None
    for campo in ("published", "updated"):
        val = entry.get(campo)
        if val:
            try:
                fecha = parsedate_to_datetime(val)
                break
            except (TypeError, ValueError):
                pass
    if fecha is None and entry.get("published_parsed"):
        import calendar
        fecha = dt.datetime.fromtimestamp(
            calendar.timegm(entry.published_parsed), tz=dt.timezone.utc
        )
    if fecha is None:
        return False, None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=dt.timezone.utc)
    return fecha >= limite, fecha


def resumir(entry, fuente, api_key):
    """Llama a la API de Claude para resumir una entrada. Devuelve dict o None."""
    resumen_bruto = entry.get("summary", "") or entry.get("description", "")
    resumen_bruto = resumen_bruto[:1500]  # recortar para abaratar tokens

    payload = {
        "model": MODEL,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": USER_TEMPLATE.format(
                titulo=entry.get("title", "(sin titulo)"),
                fuente=fuente["nombre"],
                area=fuente["area"],
                fecha=entry.get("published", entry.get("updated", "?")),
                resumen=resumen_bruto or "(sin extracto)",
            ),
        }],
    }
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": api_key,
    }
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        texto = "".join(b.get("text", "") for b in data.get("content", []))
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(texto)
    except Exception as e:
        print(f"  ! Error resumiendo '{entry.get('title', '?')}': {e}", file=sys.stderr)
        return None


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: falta ANTHROPIC_API_KEY en el entorno.", file=sys.stderr)
        sys.exit(1)

    ahora = dt.datetime.now(dt.timezone.utc)
    limite = ahora - dt.timedelta(hours=LOOKBACK_HOURS)
    hoy = ahora.strftime("%Y-%m-%d")

    items = []
    for fuente in FUENTES:
        print(f"Leyendo {fuente['nombre']}...")
        try:
            feed = feedparser.parse(fuente["url"])
        except Exception as e:
            print(f"  ! No se pudo leer el feed: {e}", file=sys.stderr)
            continue
        for entry in feed.entries:
            reciente, fecha = entrada_reciente(entry, limite)
            if not reciente:
                continue
            resumen = resumir(entry, fuente, api_key)
            if resumen is None:
                continue
            items.append({
                "fuente": fuente["nombre"],
                "url": entry.get("link", ""),
                "fecha": fecha.strftime("%Y-%m-%d %H:%M") if fecha else "?",
                **resumen,
            })

    # Ordenar por relevancia (alta primero)
    orden = {"alta": 0, "media": 1, "baja": 2}
    items.sort(key=lambda x: orden.get(x.get("relevancia", "baja"), 3))

    escribir_documento(hoy, items, ahora)
    print(f"\nListo: {len(items)} novedades procesadas para {hoy}.")


def escribir_documento(hoy, items, ahora):
    """Escribe el markdown del dia con el frontmatter y estructura del proyecto."""
    destino = Path("conocimiento/novedades") / f"{hoy}_novedades.md"
    destino.parent.mkdir(parents=True, exist_ok=True)

    altas = [i for i in items if i.get("relevancia") == "alta"]
    tags = sorted({i.get("area", "General") for i in items}) or ["General"]

    lineas = [
        "---",
        f"tema: Novedades del sector",
        f"fecha: {hoy}",
        f"fuentes_escaneadas: {len(FUENTES)}",
        f"novedades: {len(items)}",
        f"relevancia_alta: {len(altas)}",
        f"tags: [novedades, {', '.join(t.lower() for t in tags)}]",
        "---",
        "",
        f"# Novedades del sector - {hoy}",
        "",
        f"Escaneo automatico de {len(FUENTES)} fuentes. "
        f"{len(items)} entradas en las ultimas {LOOKBACK_HOURS}h, "
        f"{len(altas)} de relevancia alta.",
        "",
    ]

    if not items:
        lineas.append("_Sin novedades relevantes en el periodo._")
    else:
        for nivel, etiqueta in (("alta", "Relevancia alta"), ("media", "Relevancia media"), ("baja", "Relevancia baja")):
            grupo = [i for i in items if i.get("relevancia") == nivel]
            if not grupo:
                continue
            lineas.append(f"## {etiqueta}")
            lineas.append("")
            for i in grupo:
                lineas.append(f"### {i.get('titular', i.get('url', 'novedad'))}")
                lineas.append(f"- **Area:** {i.get('area', '-')}  ")
                lineas.append(f"- **Fuente:** {i.get('fuente', '-')} ({i.get('fecha', '?')})  ")
                lineas.append(f"- **Implicacion:** {i.get('implicacion', '-')}  ")
                if i.get("obsolescencia", "-") not in ("-", "", "ninguna"):
                    lineas.append(f"- **Deja obsoleto:** {i.get('obsolescencia')}  ")
                if i.get("url"):
                    lineas.append(f"- **Enlace:** {i.get('url')}  ")
                lineas.append("")

    destino.write_text("\n".join(lineas), encoding="utf-8")
    print(f"Documento escrito: {destino}")


if __name__ == "__main__":
    main()
