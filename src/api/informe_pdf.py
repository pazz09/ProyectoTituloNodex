"""Informe de análisis en PDF (Fase B).

Presenta como documento narrativo lo que el sistema ya produce: el
diagnóstico, la confianza, los veredictos del auditor, las técnicas MITRE
ATT&CK relacionadas y los comandos de mitigación. **No genera contenido
nuevo** ni vuelve a correr el grafo -- se arma con lo que quedó persistido
en `src/api/historial.py`, así que descargar el informe no cuesta cuota de
LLM.

Usa `fpdf2` por ser Python puro, sin binarios de sistema: encaja con el
modelo de distribución autohospedado, donde el cliente instala el sistema
en su propia infraestructura y no queremos obligarlo a resolver
dependencias nativas.

**Saneamiento de texto.** Las fuentes base de `fpdf2` (Helvetica y
compañía) codifican en latin-1, y ahí se rompe con datos reales: los
diagnósticos que genera el LLM usan raya (—), puntos suspensivos (…) y
comillas tipográficas, ninguno de los cuales existe en latin-1. Verificado
el 9-sep-2026: `multi_cell()` lanza `FPDFUnicodeEncodingException` con
cualquiera de ellos. Los acentos del español sí están en latin-1 y se
conservan intactos.

Se resuelve mapeando esos caracteres a su equivalente ASCII antes de
escribir, en vez de empotrar una fuente TTF Unicode: un archivo de fuente
son ~750 KB de binario en el repositorio, y para un informe técnico en
español la pérdida tipográfica es irrelevante. Cualquier carácter que
igual quede fuera de latin-1 se reemplaza por "?" -- el informe se degrada,
pero nunca falla la descarga.
"""

import itertools
import json
import unicodedata
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from src.config import MITRE_ATTACK_ATTRIBUTION

# Caracteres tipográficos frecuentes en la salida del LLM que latin-1 no
# tiene. Se mapean explícitamente para que el reemplazo sea legible y no un
# "?" en medio de una frase.
_EQUIVALENCIAS = {
    "—": "--", "–": "-",          # raya y semirraya
    "…": "...",                         # puntos suspensivos
    "→": "->", "←": "<-",          # flechas
    "“": '"', "”": '"',            # comillas dobles tipográficas
    "‘": "'", "’": "'",            # comillas simples tipográficas
    "•": "-",                           # viñeta
    " ": " ",                           # espacio duro
    "≥": ">=", "≤": "<=",
    "×": "x",
}

_LIMITE_COMANDOS = 40


def sanear(texto) -> str:
    """Devuelve `texto` escribible con las fuentes base de fpdf2."""
    if texto is None:
        return ""
    s = str(texto)
    for original, reemplazo in _EQUIVALENCIAS.items():
        s = s.replace(original, reemplazo)
    # Lo que quede fuera de latin-1 se intenta descomponer (á -> a) antes de
    # rendirse: preserva más significado que un "?" directo.
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        pass
    salida = []
    for ch in s:
        try:
            ch.encode("latin-1")
            salida.append(ch)
        except UnicodeEncodeError:
            plano = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            salida.append(plano or "?")
    return "".join(salida)


class _InformePDF(FPDF):
    """Añade el pie de página automático a todas las hojas."""

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        generado = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.cell(0, 5, sanear(
            f"Generado automáticamente por NODEX el {generado}  |  "
            f"Página {self.page_no()}"), align="C")
        self.set_text_color(0, 0, 0)


def _titulo(pdf: FPDF, texto: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(47, 95, 224)
    pdf.multi_cell(0, 6, sanear(texto), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=10)
    pdf.ln(1)


def _parrafo(pdf: FPDF, texto: str) -> None:
    """Todas las llamadas a `multi_cell` fijan `new_x=LMARGIN`.

    El default de fpdf2 es `new_x=RIGHT`, que deja el cursor pegado al
    margen derecho; la llamada siguiente calcula entonces un ancho útil de
    0 y lanza `FPDFException: Not enough horizontal space to render a
    single character`. Solo se manifiesta con dos `multi_cell` seguidas,
    que es exactamente el caso de la lista de comandos.
    """
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 5, sanear(texto), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def _campo(pdf: FPDF, etiqueta: str, valor) -> None:
    """Escribe "Etiqueta: valor" con la etiqueta en negrita.

    Usa `write()` y no `cell()` + `multi_cell()`: esa combinación calcula
    el ancho restante a partir de la posición del cursor, y con una
    etiqueta larga no queda espacio suficiente para el valor. fpdf2 lanza
    entonces `FPDFException: Not enough horizontal space to render a single
    character`. `write()` fluye el texto sobre el ancho completo y salta de
    línea solo.
    """
    pdf.set_font("Helvetica", "B", 10)
    pdf.write(5, sanear(f"{etiqueta}: "))
    pdf.set_font("Helvetica", size=10)
    pdf.write(5, sanear("" if valor is None else str(valor)))
    pdf.ln(5)


def _si_no(valor) -> str:
    if valor is None:
        return "sin determinar"
    return "sí" if valor else "no"


def _como_dict(valor) -> dict:
    """Los blobs vuelven del historial ya deserializados, pero un archivo
    viejo o un JSON corrupto pueden devolver texto: se tolera."""
    if isinstance(valor, dict):
        return valor
    if isinstance(valor, str) and valor.strip():
        try:
            cargado = json.loads(valor)
            return cargado if isinstance(cargado, dict) else {}
        except ValueError:
            return {}
    return {}


def generar_informe_pdf(corrida: dict) -> bytes:
    """Arma el informe de una corrida. Nunca lanza por datos faltantes."""
    corrida = corrida or {}
    resumen = _como_dict(corrida.get("resumen_json"))
    reporte = _como_dict(corrida.get("reporte_json"))

    pdf = _InformePDF()
    # Las secciones 3 (MITRE/CVE) y la de revisión humana solo se emiten si
    # hay datos, así que la numeración se lleva con un contador: con números
    # fijos el informe saltaba de "2." a "4." y se leía como una página
    # faltante.
    numero = itertools.count(1)

    def seccion(titulo: str) -> None:
        _titulo(pdf, f"{next(numero)}. {titulo}")

    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- 1. Encabezado ----------------------------------------------------
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, sanear("Informe de Análisis de Incidente — NODEX"),
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    _campo(pdf, "Fecha del análisis", corrida.get("timestamp") or "sin registrar")
    _campo(pdf, "Archivo analizado", corrida.get("archivo_origen") or "sin registrar")
    _campo(pdf, "Formato detectado", corrida.get("formato_detectado") or "sin determinar")
    _campo(pdf, "Motor de preprocesamiento", corrida.get("motor_preprocesamiento") or "sin registrar")
    _campo(pdf, "Identificador de la corrida", corrida.get("job_id") or "sin registrar")

    # --- 2. Resumen ejecutivo --------------------------------------------
    seccion("Resumen ejecutivo")
    if corrida.get("estado") == "error":
        _parrafo(pdf, "El análisis no pudo completarse. El sistema registró el "
                      "siguiente error, de modo que las conclusiones de este "
                      "informe están incompletas:")
        _parrafo(pdf, corrida.get("error_mensaje") or "Error no especificado.")
    else:
        confianza = corrida.get("confianza")
        conf_txt = "sin determinar" if confianza is None else f"{confianza:.2f}"
        _parrafo(pdf, corrida.get("diagnostico") or
                 "El sistema no registró un diagnóstico para esta corrida.")
        _campo(pdf, "Nivel de confianza", conf_txt)
        _campo(pdf, "¿Anomalía detectada?", _si_no(corrida.get("hay_anomalia")))
        _campo(pdf, "¿Incidente de seguridad?", _si_no(corrida.get("hay_incidente")))
        if corrida.get("requiere_revision_humana"):
            _campo(pdf, "Escalamiento", "SÍ requiere revisión de un analista humano "
                                        "(confianza bajo el umbral)")
        else:
            _campo(pdf, "Escalamiento", "no requiere revisión humana")

    # --- 3. Evidencia observada ------------------------------------------
    seccion("Evidencia observada")
    _campo(pdf, "Total de líneas analizadas", corrida.get("total_lineas") or "sin registrar")

    ventana = resumen.get("ventana_temporal") or {}
    if ventana.get("inicio") or ventana.get("fin"):
        _campo(pdf, "Ventana temporal",
               f"{ventana.get('inicio', '?')}  a  {ventana.get('fin', '?')}")

    servicios = resumen.get("servicios") or {}
    if servicios:
        principales = sorted(servicios.items(), key=lambda kv: -kv[1])[:6]
        _campo(pdf, "Servicios principales",
               ", ".join(f"{k} ({v})" for k, v in principales))

    eventos = resumen.get("eventos") or {}
    if eventos:
        _campo(pdf, "Distribución de eventos",
               ", ".join(f"{k}: {v}" for k, v in eventos.items()))

    n_ips = resumen.get("n_ips_distintas")
    if n_ips is not None:
        _campo(pdf, "Direcciones IP distintas", n_ips)

    reputacion = resumen.get("reputacion_ips") or {}
    if reputacion:
        categorias: dict[str, int] = {}
        for datos in reputacion.values():
            cat = (datos or {}).get("categoria", "desconocido")
            categorias[cat] = categorias.get(cat, 0) + 1
        _campo(pdf, "Reputación (AbuseIPDB)",
               ", ".join(f"{k}: {v}" for k, v in sorted(categorias.items())))
    if not any((ventana, servicios, eventos, n_ips is not None, reputacion)):
        _parrafo(pdf, "No se registró el detalle de la evidencia para esta corrida.")

    # --- 4. Contexto y técnicas relacionadas -----------------------------
    tecnicas = corrida.get("tecnicas_mitre") or []
    cves = reporte.get("cves_encontrados") or []
    if tecnicas or cves:
        seccion("Contexto y técnicas relacionadas")
        if tecnicas:
            _parrafo(pdf, "Técnicas de MITRE ATT&CK relacionadas con el "
                          "comportamiento observado:")
            for t in tecnicas:
                meta = t.get("meta", t) if isinstance(t, dict) else {}
                tid = meta.get("technique_id") or meta.get("id") or "?"
                nombre = meta.get("nombre") or meta.get("name") or ""
                _parrafo(pdf, f"   {tid}  {nombre}".rstrip())
            # Requisito de atribución del propio MITRE: solo corresponde
            # incluirlo si efectivamente se muestran datos de ATT&CK.
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(0, 4, sanear(MITRE_ATTACK_ATTRIBUTION),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
        if cves:
            _campo(pdf, "CVEs consultados en la NVD", len(cves))

    # --- 5. Evaluación del auditor ---------------------------------------
    seccion("Evaluación del auditor")
    _parrafo(pdf, corrida.get("evaluacion_auditor") or
             "El auditor no dejó una evaluación registrada para esta corrida.")

    # --- 6. Mitigación propuesta -----------------------------------------
    seccion("Mitigación propuesta")
    comandos = reporte.get("comandos_mitigacion")
    if comandos is None and corrida.get("n_comandos_mitigacion"):
        # Se sabe cuántos comandos hubo, pero no cuáles: la corrida es
        # anterior a que se guardara el reporte completo.
        _parrafo(pdf, f"El análisis propuso {corrida['n_comandos_mitigacion']} "
                      "comando(s), pero esta corrida es anterior al registro "
                      "del detalle y no se conservó su contenido.")
    elif comandos:
        _parrafo(pdf, "Comandos validados por el sistema. Se entregan como "
                      "recomendación: NODEX no los ejecuta.")
        pdf.set_font("Courier", size=9)
        for c in comandos[:_LIMITE_COMANDOS]:
            pdf.multi_cell(0, 4.5, sanear(f"  {c}"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", size=10)
        if len(comandos) > _LIMITE_COMANDOS:
            _parrafo(pdf, f"({len(comandos) - _LIMITE_COMANDOS} comando(s) más, "
                          "omitidos por extensión.)")
    else:
        # No se deja la sección vacía sin explicación: un informe con un
        # hueco silencioso se lee como un fallo del sistema.
        _parrafo(pdf, "No se requiere mitigación. El análisis no identificó "
                      "acciones necesarias sobre la evidencia observada.")

    if corrida.get("feedback_correcto") is not None:
        seccion("Revisión humana")
        _campo(pdf, "Veredicto del analista",
               "diagnóstico correcto" if corrida["feedback_correcto"]
               else "diagnóstico incorrecto")
        if corrida.get("feedback_comentario"):
            _campo(pdf, "Comentario", corrida["feedback_comentario"])
        if corrida.get("feedback_timestamp"):
            _campo(pdf, "Fecha de la revisión", corrida["feedback_timestamp"])

    return bytes(pdf.output())
