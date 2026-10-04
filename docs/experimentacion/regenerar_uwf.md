# Cómo regenerar los CSV de UWF

Los CSV intermedios de UWF (**138 MB**: 111 MB de eventos y 27 MB de
etiquetas) **no están versionados**. Lo que sí está versionado es todo lo
necesario para reproducirlos byte a byte:

- los 13 Parquet de origen, en `data/logs/UWF-ZeekDataFall22-parquet/`;
- el conversor, en `src/experimentation/datasets/uwf.py`;
- el SHA-256 de cada CSV producido, en
  `experiments/manifests/uwf_conversion.json`;
- los 104 casos compuestos y sus referencias, en `experiments/`, que son
  pequeños y sí están versionados.

Es la división que pidió la autorización del 3-oct-2026: la conversión es un
paso **offline** y los experimentos consumen los CSV y sus hashes.

## Regeneración

```bash
py -3.13 -m venv .venv-preparacion
.venv-preparacion\Scripts\python -m pip install -r requirements-experimentacion.txt
.venv-preparacion\Scripts\python -m src.experimentation.datasets.uwf
```

Produce `data/experimentacion/uwf_csv/{eventos,etiquetas}/` y reescribe
`experiments/manifests/uwf_conversion.json`. Para confirmar que la
regeneración dio lo mismo, comparar los `sha256_eventos` y
`sha256_etiquetas` del manifiesto nuevo contra los del commit.

Los casos compuestos se regeneran después, y también son determinísticos
(semilla `20261003`, registrada en cada caso):

```bash
.venv-preparacion\Scripts\python -m src.experimentation.datasets.uwf_casos
```

## Por qué pyarrow no es una dependencia de NODEX

`pyarrow` vive solo en `requirements-experimentacion.txt` y solo lo importa
`src/experimentation/datasets/uwf.py`, de forma diferida dentro de la
función que lee el Parquet. Ni el pipeline, ni los agentes, ni los
evaluadores lo importan. Comprobable con:

```bash
grep -rn "pyarrow" src/ | grep -v "datasets/uwf.py"
```

No debe devolver nada. `requirements.txt` y `constraints.txt` quedaron sin
tocar, así que el CI sigue corriendo contra las dependencias fijadas de la
Fase 7.
