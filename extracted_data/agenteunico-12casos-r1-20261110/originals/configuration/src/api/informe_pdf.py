"""Informe de análisis en PDF.

Presenta como documento lo que el sistema ya produjo: el diagnóstico, la
evidencia, la secuencia temporal, las técnicas de MITRE ATT&CK, los
precedentes y la mitigación propuesta. **No genera contenido nuevo** ni
vuelve a correr el grafo -- se arma con lo que quedó persistido en
`src/api/historial.py`, así que emitir el informe no cuesta cuota de LLM.

Plantilla (11-sep-2026)
-----------------------
Réplica de la plantilla editorial que eligió Antonia: portada con el título
en cuerpo grande, un encabezado corrido de dos líneas en cada hoja, cada
sección en su propia página con el título en versales y una regla gruesa
debajo, cuerpo en monoespaciado, y los datos en filas etiqueta/valor
separadas por reglas finas. Blanco y negro, con un solo acento.

Usa `fpdf2` por ser Python puro, sin binarios de sistema: encaja con el
modelo de distribución autohospedado.

**Tipografías.** La referencia usa una grotesca para los títulos y una
monoespaciada de palo seco para el cuerpo. Con las fuentes base de fpdf2
los equivalentes disponibles son Helvetica y Courier; replican la
*estructura* tipográfica (contraste sans/mono, versales, jerarquía por
peso) pero no el dibujo exacto de las letras. Empotrar las fuentes reales
serían ~750 KB de binario en el repositorio, que se decidió no agregar.

**Saneamiento de texto.** Las fuentes base codifican en latin-1, y ahí se
rompe con datos reales: los diagnósticos del LLM usan raya (—), puntos
suspensivos (…) y comillas tipográficas, que no existen en latin-1.
Verificado el 9-sep-2026: `multi_cell()` lanza
`FPDFUnicodeEncodingException` con cualquiera de ellos. Se mapean a su
equivalente ASCII antes de escribir; los acentos del español sí están en
latin-1 y se conservan intactos.
"""

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
    "—": "--", "–": "-",
    "…": "...",
    "→": "->", "←": "<-",
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "•": "-",
    " ": " ",
    "≥": ">=", "≤": "<=",
    "×": "x",
}

# --- Sistema visual del documento ------------------------------------------
NEGRO = (17, 17, 17)
GRIS = (122, 122, 122)
GRIS_REGLA = (206, 206, 206)
ACENTO = (21, 82, 216)

MARGEN = 22          # mm a cada lado
CUERPO = 8.6         # pt del texto en monoespaciado
INTERLINEA = 4.6     # mm entre líneas del cuerpo

_LIMITE_COMANDOS = 40
_LIMITE_CRONOLOGIA = 26


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


def _si_no(valor) -> str:
    if valor is None:
        return "sin determinar"
    return "sí" if valor else "no"


class _Informe(FPDF):
    """Documento con el encabezado corrido y el pie de la plantilla.

    `portada` desactiva el encabezado en la primera hoja, donde la marca ya
    aparece compuesta con la fecha.
    """

    def __init__(self):
        super().__init__(format="A4", unit="mm")
        self.set_margins(MARGEN, 20, MARGEN)
        self.set_auto_page_break(auto=True, margin=24)

    def header(self) -> None:
        # La portada compone su propia marca junto a la fecha.
        if self.page_no() == 1:
            return
        self.set_y(16)
        self.set_font("Helvetica", "B", 7.4)
        self.set_text_color(*NEGRO)
        self.cell(0, 3.4, "NODEX", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(0, 3.4, "INTELIGENCIA DE SEGURIDAD", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(34)

    def footer(self) -> None:
        # El pie se dibuja al CERRAR cada hoja, así que no puede depender de
        # una bandera que la portada apaga al terminar de escribirse: se
        # decide por número de página.
        if self.page_no() == 1:
            return
        self.set_y(-16)
        self.set_font("Courier", size=7.4)
        self.set_text_color(*GRIS)
        self.cell(0, 4, sanear(f"NODEX  ·  página {self.page_no() - 1} de {{nb}}"), align="R")
        self.set_text_color(*NEGRO)


# --- Primitivas de la plantilla --------------------------------------------

def _ancho(pdf: FPDF) -> float:
    return pdf.w - MARGEN * 2


def _seccion(pdf: _Informe, titulo: str) -> None:
    """Abre una sección: página nueva, versales y regla gruesa debajo.

    Cada sección arranca en su propia hoja, como en la plantilla. Cuesta
    páginas, pero es lo que hace que el documento se lea como un informe y
    no como una pila de bloques.
    """
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 9.6)
    pdf.set_text_color(*NEGRO)
    pdf.cell(0, 5, sanear(titulo.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2.4)
    pdf.set_line_width(0.7)
    pdf.set_draw_color(*NEGRO)
    y = pdf.get_y()
    pdf.line(MARGEN, y, pdf.w - MARGEN, y)
    pdf.set_line_width(0.2)
    pdf.ln(7)


def _subtitulo(pdf: FPDF, texto: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 8.6)
    pdf.set_text_color(*NEGRO)
    pdf.cell(0, 5, sanear(texto.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)


def _parrafo(pdf: FPDF, texto: str, gris: bool = False) -> None:
    """Cuerpo en monoespaciado.

    Todas las llamadas a `multi_cell` fijan `new_x=LMARGIN`: el default de
    fpdf2 deja el cursor pegado al margen derecho, y la llamada siguiente
    calcula entonces un ancho útil de 0 y lanza `FPDFException: Not enough
    horizontal space to render a single character`.
    """
    pdf.set_font("Courier", size=CUERPO)
    pdf.set_text_color(*(GRIS if gris else NEGRO))
    pdf.multi_cell(0, INTERLINEA, sanear(texto), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEGRO)
    pdf.ln(2)


def _fila(pdf: FPDF, etiqueta: str, valor, sangria: float = 4.0) -> None:
    """Fila etiqueta/valor con la regla fina debajo, como la plantilla.

    La etiqueta va sangrada y el valor alineado a una columna fija, que es
    lo que le da al bloque su aspecto de estado contable.
    """
    ancho = _ancho(pdf)
    col_valor = ancho * 0.52
    pdf.set_font("Courier", size=CUERPO)
    pdf.set_text_color(*NEGRO)
    y = pdf.get_y()
    pdf.set_x(MARGEN + sangria)
    pdf.cell(col_valor - sangria, 6.4, sanear(etiqueta))
    pdf.set_x(MARGEN + col_valor)
    pdf.multi_cell(ancho - col_valor, 6.4, sanear("" if valor is None else str(valor)),
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    # La regla se dibuja al final, a la altura real que ocupó la fila: un
    # valor largo puede haber usado dos líneas.
    fin = pdf.get_y()
    pdf.set_draw_color(*GRIS_REGLA)
    pdf.line(MARGEN + sangria, fin, pdf.w - MARGEN, fin)
    pdf.set_y(fin)
    if fin - y < 6.5:
        pdf.ln(0.4)


def _grafico_lineas(pdf: _Informe, puntos: list, etiqueta_y: str = "") -> None:
    """Serie temporal con ejes, como la de la plantilla.

    Se dibuja con primitivas de fpdf2: ejes en gris fino, línea de la serie
    en negro y un punto por muestra. Con menos de dos muestras no se dibuja
    nada -- un gráfico de un solo punto se lee como un dato inventado.
    """
    if len(puntos) < 2:
        return

    ancho = _ancho(pdf)
    alto = 52.0
    x0 = MARGEN + 12
    y0 = pdf.get_y() + 4
    w = ancho - 12
    maximo = max(p[1] for p in puntos) or 1
    techo = max(1, -(-maximo // 1))

    # Guías horizontales y escala.
    pdf.set_font("Courier", size=7)
    pdf.set_text_color(*GRIS)
    for fraccion in (0.0, 0.5, 1.0):
        y = y0 + alto - alto * fraccion
        pdf.set_draw_color(*GRIS_REGLA)
        pdf.line(x0, y, x0 + w, y)
        pdf.set_xy(MARGEN - 2, y - 2)
        pdf.cell(12, 4, sanear(str(int(round(techo * fraccion)))), align="R")

    # Serie.
    pdf.set_draw_color(*NEGRO)
    pdf.set_line_width(0.45)
    coords = [
        (x0 + (i / (len(puntos) - 1)) * w, y0 + alto - (v / techo) * alto)
        for i, (_, v) in enumerate(puntos)
    ]
    for (xa, ya), (xb, yb) in zip(coords, coords[1:]):
        pdf.line(xa, ya, xb, yb)
    pdf.set_fill_color(*NEGRO)
    for x, y in coords:
        pdf.circle(x=x - 0.7, y=y - 0.7, radius=0.7, style="F")
    pdf.set_line_width(0.2)

    # Etiquetas del eje horizontal, saltadas si no caben.
    paso = max(1, len(puntos) // 6)
    pdf.set_text_color(*GRIS)
    for i, (etiqueta, _) in enumerate(puntos):
        if i % paso and i != len(puntos) - 1:
            continue
        x = coords[i][0]
        pdf.set_xy(x - 12, y0 + alto + 2)
        pdf.cell(24, 4, sanear(etiqueta), align="C")

    pdf.set_y(y0 + alto + 9)
    if etiqueta_y:
        pdf.set_font("Courier", size=7)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 4, sanear(etiqueta_y), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEGRO)
    pdf.ln(2)


def _serie_cronologia(cronologia: list, cubos: int = 8) -> list:
    """Registros relevantes agrupados en intervalos iguales.

    Los agrupa por POSICIÓN en la secuencia y no por reloj: las marcas de
    tiempo vienen en el formato de cada origen --`Sep 9 03:12:01` en
    auth-log, `2005-06-04-00.24.32` en BGL-- y normalizarlas acá sería
    reimplementar el parseo que el preprocesamiento ya hizo. Lo que la
    curva muestra es la concentración de los registros relevantes a lo
    largo del lote, que es la forma del incidente.
    """
    if len(cronologia) < 2:
        return []
    numeros = [e.get("n") or 0 for e in cronologia]
    primero, ultimo = min(numeros), max(numeros)
    if ultimo == primero:
        return []
    tamano = (ultimo - primero) / cubos
    conteo = [0] * cubos
    for n in numeros:
        indice = min(cubos - 1, int((n - primero) / tamano))
        conteo[indice] += 1
    return [
        (f"{int(primero + tamano * i)}", conteo[i])
        for i in range(cubos)
    ]


# --- Documento --------------------------------------------------------------

def _portada(pdf: _Informe, corrida: dict) -> None:
    pdf.add_page()

    pdf.set_y(22)
    pdf.set_font("Helvetica", "B", 7.4)
    pdf.set_text_color(*NEGRO)
    pdf.cell(_ancho(pdf) * 0.6, 3.4, "NODEX")
    pdf.set_font("Courier", size=8)
    pdf.cell(0, 3.4, sanear(_fecha_larga(corrida.get("timestamp"))), align="R",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "B", 7.4)
    pdf.cell(0, 3.4, "INTELIGENCIA DE SEGURIDAD", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(104)
    pdf.set_font("Helvetica", "B", 33)
    pdf.multi_cell(0, 13.5, sanear("Informe de\nanálisis"),
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11.5)
    pdf.cell(0, 6, sanear(corrida.get("archivo_origen") or "lote sin nombre"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Bloque de datos al pie, en dos columnas.
    pdf.set_y(238)
    pdf.set_font("Courier", size=8)
    pdf.set_text_color(*GRIS)
    izquierda = [
        sanear(f"Formato detectado: {(corrida.get('formato_detectado') or '-').upper()}"),
        sanear(f"Motor de preprocesamiento: {corrida.get('motor_preprocesamiento') or '-'}"),
        sanear(f"Registros analizados: {corrida.get('total_lineas') or 0}"),
    ]
    derecha = [
        sanear(f"Ejecución: {(corrida.get('job_id') or '-')[:16]}"),
        sanear(f"Estado: {corrida.get('estado') or '-'}"),
        "Generado por NODEX, sin intervención manual",
    ]
    media = _ancho(pdf) / 2
    for a, b in zip(izquierda, derecha):
        pdf.cell(media, 4.6, a)
        pdf.multi_cell(media, 4.6, b, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*NEGRO)


def _fecha_larga(iso) -> str:
    if not iso:
        return "sin fecha"
    try:
        d = datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return str(iso)
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


def _veredicto(corrida: dict) -> str:
    if corrida.get("estado") == "error":
        return "EJECUCIÓN INCOMPLETA"
    if corrida.get("hay_incidente"):
        return "INCIDENTE DE SEGURIDAD"
    if corrida.get("hay_anomalia"):
        return "ANOMALÍA OPERATIVA"
    return "SIN HALLAZGOS"


def generar_informe_pdf(corrida: dict, comprimir: bool = True) -> bytes:
    """Arma el informe de una corrida. Nunca lanza por datos faltantes.

    `comprimir=False` desactiva la compresión FlateDecode del contenido
    (`pdf.set_compression`, ver fpdf2). Existe para poder auditar el PDF
    por bytes en las pruebas (Fase 3 del cierre de auditoría, 23-sep-2026):
    con la compresión activa -- el default en producción, sin cambios --
    ni un string tan obvio como el nombre del archivo aparece como
    substring literal en la salida.
    """
    corrida = corrida or {}
    resumen = _como_dict(corrida.get("resumen_json"))
    reporte = _como_dict(corrida.get("reporte_json"))

    pdf = _Informe()
    pdf.set_compression(comprimir)
    _portada(pdf, corrida)

    # --- Resumen del análisis ---------------------------------------------
    _seccion(pdf, "Resumen del análisis")
    if corrida.get("estado") == "error":
        _parrafo(pdf, "La ejecución no pudo completarse. El sistema registró el "
                      "siguiente error, de modo que las conclusiones de este "
                      "informe están incompletas:")
        _parrafo(pdf, corrida.get("error_mensaje") or "Error no especificado.", gris=True)
    else:
        _parrafo(pdf, corrida.get("diagnostico") or
                 "El sistema no registró un diagnóstico para esta ejecución.")

    _subtitulo(pdf, "Veredicto")
    confianza = corrida.get("confianza")
    _fila(pdf, "Clasificación", _veredicto(corrida))
    _fila(pdf, "Nivel de confianza", "sin determinar" if confianza is None else f"{confianza:.2f}")
    _fila(pdf, "Anomalía detectada", _si_no(corrida.get("hay_anomalia")))
    _fila(pdf, "Incidente de seguridad", _si_no(corrida.get("hay_incidente")))
    _fila(pdf, "Revisión humana", "requerida" if corrida.get("requiere_revision_humana")
          else "no requerida")

    serie = _serie_cronologia(resumen.get("cronologia") or [])
    if serie:
        _subtitulo(pdf, "Concentración de los registros relevantes")
        _grafico_lineas(pdf, serie, "eje horizontal: número de registro dentro del lote")

    # --- Evidencia observada ----------------------------------------------
    _seccion(pdf, "Evidencia observada")
    _parrafo(pdf, "Todo lo de esta sección sale del preprocesamiento "
                  "determinístico del lote. No interviene el modelo de lenguaje.",
             gris=True)

    _subtitulo(pdf, "Lote")
    _fila(pdf, "Archivo de origen", corrida.get("archivo_origen") or "-")
    _fila(pdf, "Registros analizados", corrida.get("total_lineas") or 0)
    ventana = resumen.get("ventana_temporal") or {}
    if ventana.get("inicio"):
        _fila(pdf, "Primer registro", ventana["inicio"])
    if ventana.get("fin"):
        _fila(pdf, "Último registro", ventana["fin"])
    _fila(pdf, "Formato detectado", (corrida.get("formato_detectado") or "-").upper())
    _fila(pdf, "Direcciones IP distintas", resumen.get("n_ips_distintas") or 0)
    if resumen.get("n_usuarios_distintos"):
        _fila(pdf, "Actores distintos", resumen["n_usuarios_distintos"])

    servicios = resumen.get("servicios") or {}
    if servicios:
        _subtitulo(pdf, "Servicios")
        for nombre, n in sorted(servicios.items(), key=lambda kv: -kv[1])[:8]:
            _fila(pdf, nombre, f"{n}")

    eventos = resumen.get("eventos") or {}
    if eventos:
        _subtitulo(pdf, "Tipos de evento")
        for nombre, n in sorted(eventos.items(), key=lambda kv: -kv[1]):
            _fila(pdf, nombre.replace("_", " "), f"{n}")

    codigos = resumen.get("codigos_respuesta") or {}
    if codigos:
        _subtitulo(pdf, "Códigos de respuesta")
        for codigo, n in sorted(codigos.items()):
            _fila(pdf, codigo, f"{n}")

    usuarios = resumen.get("usuarios") or {}
    if usuarios:
        _subtitulo(pdf, "Actores más frecuentes")
        for nombre, n in sorted(usuarios.items(), key=lambda kv: -kv[1])[:8]:
            _fila(pdf, nombre, f"{n}")

    reputacion = resumen.get("reputacion_ips") or {}
    if reputacion:
        _subtitulo(pdf, "Reputación de las direcciones observadas")
        for ip, datos in reputacion.items():
            d = datos or {}
            score = d.get("score")
            detalle = d.get("categoria", "desconocido")
            if score is not None:
                detalle = f"{detalle}  ({d.get('fuente', 'fuente desconocida')}, score {score})"
            _fila(pdf, ip, detalle)

    entidades = resumen.get("entidades") or []
    if entidades:
        _subtitulo(pdf, "Entidades involucradas")
        for e in entidades:
            partes = [f"{e.get('n_eventos', 0)} eventos"]
            if e.get("intentos_fallidos"):
                partes.append(f"{e['intentos_fallidos']} fallidos")
            if e.get("servicios"):
                partes.append(", ".join(e["servicios"]))
            if e.get("usuarios_objetivo"):
                partes.append("objetivos: " + ", ".join(e["usuarios_objetivo"]))
            _fila(pdf, e.get("ip", "?"), "  ·  ".join(partes))

    if not any((servicios, eventos, reputacion, entidades)):
        _parrafo(pdf, "No se registró el detalle de la evidencia para esta ejecución.")

    # --- Secuencia temporal -----------------------------------------------
    cronologia = resumen.get("cronologia") or []
    if cronologia:
        _seccion(pdf, "Secuencia temporal de los registros relevantes")
        omitidos = resumen.get("cronologia_omitidos") or 0
        _parrafo(pdf, "Registros que se apartan del comportamiento base del lote, "
                      "en orden de aparición. La selección es determinística.", gris=True)
        for entrada in cronologia[:_LIMITE_CRONOLOGIA]:
            actores = [f"{k}={entrada[k]}" for k in
                       ("ip", "ip_destino", "usuario", "codigo_respuesta")
                       if entrada.get(k)]
            cabecera = "  ·  ".join(filter(None, (
                f"#{entrada.get('n', '?')}",
                entrada.get("timestamp") or "sin marca de tiempo",
                entrada.get("servicio") or None,
                entrada.get("evento") or None,
                " ".join(actores) or None,
            )))
            pdf.set_font("Helvetica", "B", 7.8)
            pdf.multi_cell(0, 4, sanear(cabecera), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Courier", size=7.8)
            pdf.set_text_color(*GRIS)
            pdf.multi_cell(0, 4, sanear(entrada.get("mensaje", "")),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*NEGRO)
            pdf.ln(2.6)
        sobrantes = max(0, len(cronologia) - _LIMITE_CRONOLOGIA) + omitidos
        if sobrantes:
            _parrafo(pdf, f"({sobrantes} registros relevantes más, omitidos por "
                          "extensión. Los conteos de la sección anterior se "
                          "calculan sobre el lote completo.)", gris=True)

    # --- MITRE ATT&CK ------------------------------------------------------
    tecnicas = corrida.get("tecnicas_mitre") or []
    if tecnicas:
        _seccion(pdf, "Técnicas MITRE ATT&CK relacionadas")
        _parrafo(pdf, "Recuperadas por similitud semántica contra el catálogo "
                      "oficial de ATT&CK cargado en la memoria del sistema.", gris=True)
        for t in tecnicas:
            meta = t.get("meta", t) if isinstance(t, dict) else {}
            tid = meta.get("technique_id") or meta.get("id") or "?"
            nombre = meta.get("nombre") or meta.get("name") or ""
            pdf.set_font("Helvetica", "B", 9)
            pdf.multi_cell(0, 5, sanear(f"{tid}   {nombre}".rstrip()),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if meta.get("tactics"):
                pdf.set_font("Courier", size=7.6)
                pdf.set_text_color(*GRIS)
                pdf.multi_cell(0, 4, sanear(str(meta["tactics"]).replace(",", " · ")),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(*NEGRO)
            if meta.get("url"):
                pdf.set_font("Courier", size=7.6)
                pdf.set_text_color(*ACENTO)
                pdf.multi_cell(0, 4, sanear(str(meta["url"])),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(*NEGRO)
            pdf.ln(3)
        # Requisito de atribución del propio MITRE: solo corresponde si
        # efectivamente se muestran datos de ATT&CK.
        pdf.ln(2)
        pdf.set_draw_color(*GRIS_REGLA)
        y = pdf.get_y()
        pdf.line(MARGEN, y, pdf.w - MARGEN, y)
        pdf.ln(3)
        pdf.set_font("Courier", size=7)
        pdf.set_text_color(*GRIS)
        pdf.multi_cell(0, 3.8, sanear(MITRE_ATTACK_ATTRIBUTION),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*NEGRO)

    # --- Precedentes -------------------------------------------------------
    precedentes = reporte.get("precedentes") or []
    cves = reporte.get("cves_encontrados") or []
    if precedentes or cves:
        _seccion(pdf, "Evidencias externas y precedentes")
        if cves:
            _subtitulo(pdf, "Vulnerabilidades consultadas")
            _fila(pdf, "CVEs devueltos por la NVD", len(cves))
        if precedentes:
            _subtitulo(pdf, "Precedentes de la memoria del sistema")
            _parrafo(pdf, "Casos anteriores que el agente de triage tuvo a la vista "
                          "al redactar el diagnóstico.", gris=True)
            for p in precedentes:
                texto = str(p.get("clasificacion") or "sin clasificación")
                if len(texto) > 300:
                    texto = f"{texto[:300].rstrip()}..."
                pdf.set_font("Courier", size=CUERPO)
                pdf.multi_cell(0, INTERLINEA, sanear(texto),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                detalle = [f"similitud {p['similitud']}" for _ in (1,) if p.get("similitud") is not None]
                if p.get("confianza") is not None:
                    detalle.append(f"confianza registrada {p['confianza']}")
                if p.get("host"):
                    detalle.append(f"host {p['host']}")
                if detalle:
                    pdf.set_font("Courier", size=7.4)
                    pdf.set_text_color(*GRIS)
                    pdf.multi_cell(0, 4, sanear("  ·  ".join(detalle)),
                                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_text_color(*NEGRO)
                pdf.ln(3)

    # --- Evaluación del auditor -------------------------------------------
    _seccion(pdf, "Evaluación del auditor")
    _parrafo(pdf, corrida.get("evaluacion_auditor") or
             "El auditor no dejó una evaluación registrada para esta ejecución.")
    if reporte.get("intentos_correccion"):
        _subtitulo(pdf, "Ciclos del flujo")
        _fila(pdf, "Intentos de mitigación", reporte["intentos_correccion"])

    # --- Mitigación --------------------------------------------------------
    _seccion(pdf, "Mitigación propuesta")
    comandos = reporte.get("comandos_mitigacion")
    if comandos is None and corrida.get("n_comandos_mitigacion"):
        _parrafo(pdf, f"El analisis propuso {corrida['n_comandos_mitigacion']} "
                      "comandos, pero esta ejecución es anterior al registro del "
                      "detalle y no se conservó su contenido.")
    elif comandos:
        _parrafo(pdf, "Comandos validados por el sistema. Se entregan como "
                      "recomendación: NODEX no los ejecuta.", gris=True)
        _subtitulo(pdf, "Comandos")
        for i, c in enumerate(comandos[:_LIMITE_COMANDOS], start=1):
            _fila(pdf, f"{i:02d}", c, sangria=0)
        if len(comandos) > _LIMITE_COMANDOS:
            _parrafo(pdf, f"({len(comandos) - _LIMITE_COMANDOS} comandos mas, "
                          "omitidos por extensión.)", gris=True)
        _subtitulo(pdf, "Validación")
        _fila(pdf, "Estado", "aprobados" if reporte.get("comandos_validos") else "sin validar")
    else:
        _parrafo(pdf, "No se requiere mitigación. El análisis no identificó "
                      "acciones necesarias sobre la evidencia observada.")

    # --- Revisión humana ---------------------------------------------------
    if corrida.get("feedback_correcto") is not None:
        _seccion(pdf, "Revisión del analista")
        _fila(pdf, "Veredicto del analista",
              "diagnóstico correcto" if corrida["feedback_correcto"]
              else "diagnóstico incorrecto")
        if corrida.get("feedback_timestamp"):
            _fila(pdf, "Fecha de la revisión", corrida["feedback_timestamp"])
        if corrida.get("feedback_comentario"):
            _subtitulo(pdf, "Comentario")
            _parrafo(pdf, corrida["feedback_comentario"])

    return bytes(pdf.output())
