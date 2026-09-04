"""Tests de `_extraer_tecnicas` (src/tools/preparar_mitre_attack.py).

Cubre solo la función PURA de parseo STIX -- sin red, sin ChromaDB --
siguiendo la convención ya usada en el repo: la capa que toca ChromaDB
(`cargar_tecnicas_attack`/`retrieve_attack_techniques` en src/memory.py, y
`main()` de este mismo script, que necesita red real) no tiene tests
pytest, solo verificación manual con un stub -- igual que
`memory.py`/`tool_consultar_rag.py` para las otras 3 colecciones.

El bundle de ejemplo usado abajo es un STIX 2.1 minimalista, escrito a
mano, que reproduce la forma real del bundle oficial de
`mitre-attack/attack-stix-data` (bundle -> objects[], con varios tipos de
objeto mezclados) pero con muchos menos campos que un objeto real -- solo
los que `_extraer_tecnicas` efectivamente lee.
"""

from src.tools.preparar_mitre_attack import _extraer_tecnicas, _version_del_bundle


def _attack_pattern(
    technique_id="T1110",
    name="Brute Force",
    description="Adversaries may use brute force techniques...",
    tactics=("credential-access",),
    is_subtechnique=False,
    revoked=False,
    deprecated=False,
    sin_referencia_mitre=False,
) -> dict:
    """Arma un objeto STIX `attack-pattern` sintético con la forma mínima
    que `_extraer_tecnicas` necesita leer."""
    obj = {
        "type": "attack-pattern",
        "name": name,
        "description": description,
        "kill_chain_phases": [
            {"kill_chain_name": "mitre-attack", "phase_name": t} for t in tactics
        ],
        "x_mitre_is_subtechnique": is_subtechnique,
        "external_references": [],
    }
    if not sin_referencia_mitre:
        obj["external_references"].append({
            "source_name": "mitre-attack",
            "external_id": technique_id,
            "url": f"https://attack.mitre.org/techniques/{technique_id}/",
        })
    # Referencia externa "ruidosa" que sí trae bundles reales (p. ej. CAPEC) --
    # no debe confundirse con la de mitre-attack.
    obj["external_references"].append({"source_name": "capec", "external_id": "CAPEC-112"})
    if revoked:
        obj["revoked"] = True
    if deprecated:
        obj["x_mitre_deprecated"] = True
    return obj


def _bundle(*objects) -> dict:
    return {"type": "bundle", "id": "bundle--fake", "objects": list(objects)}


def test_extrae_una_tecnica_valida():
    bundle = _bundle(_attack_pattern())
    tecnicas = _extraer_tecnicas(bundle)
    assert len(tecnicas) == 1
    t = tecnicas[0]
    assert t["technique_id"] == "T1110"
    assert t["name"] == "Brute Force"
    assert t["tactics"] == ["credential-access"]
    assert t["is_subtechnique"] is False
    assert t["url"] == "https://attack.mitre.org/techniques/T1110/"


def test_excluye_revoked():
    bundle = _bundle(_attack_pattern(technique_id="T9999", revoked=True))
    assert _extraer_tecnicas(bundle) == []


def test_excluye_deprecated():
    bundle = _bundle(_attack_pattern(technique_id="T9998", deprecated=True))
    assert _extraer_tecnicas(bundle) == []


def test_detecta_subtecnica():
    bundle = _bundle(_attack_pattern(technique_id="T1110.001", is_subtechnique=True))
    tecnicas = _extraer_tecnicas(bundle)
    assert len(tecnicas) == 1
    assert tecnicas[0]["is_subtechnique"] is True


def test_ignora_attack_pattern_sin_referencia_mitre_attack():
    # Un attack-pattern sin external_reference de mitre-attack no tiene ID
    # de técnica citable -- no debería aparecer en bundles Enterprise
    # reales, pero si aparece, se descarta en vez de fallar.
    bundle = _bundle(_attack_pattern(sin_referencia_mitre=True))
    assert _extraer_tecnicas(bundle) == []


def test_ignora_objetos_que_no_son_attack_pattern():
    # El bundle real mezcla muchos tipos de objeto STIX en "objects" --
    # tácticas, colecciones, relaciones, identidades, marcas de referencia.
    # Ninguno de estos debe colarse como "técnica".
    otros = [
        {"type": "x-mitre-tactic", "name": "Credential Access"},
        {"type": "x-mitre-collection", "name": "Enterprise ATT&CK", "x_mitre_version": "19.1"},
        {"type": "relationship", "relationship_type": "uses"},
        {"type": "identity", "name": "The MITRE Corporation"},
        {"type": "marking-definition"},
    ]
    bundle = _bundle(*otros)
    assert _extraer_tecnicas(bundle) == []


def test_bundle_mixto_solo_extrae_las_attack_pattern_validas():
    bundle = _bundle(
        _attack_pattern(technique_id="T1110", name="Brute Force"),
        _attack_pattern(technique_id="T1110.001", name="Password Guessing", is_subtechnique=True),
        _attack_pattern(technique_id="T0000", revoked=True),
        _attack_pattern(technique_id="T0001", deprecated=True),
        {"type": "x-mitre-tactic", "name": "Credential Access"},
        {"type": "relationship", "relationship_type": "uses"},
    )
    tecnicas = _extraer_tecnicas(bundle)
    ids = {t["technique_id"] for t in tecnicas}
    assert ids == {"T1110", "T1110.001"}


def test_descripcion_y_tacticas_multiples_se_preservan():
    bundle = _bundle(_attack_pattern(
        technique_id="T1078",
        name="Valid Accounts",
        description="Adversaries may obtain and abuse credentials...",
        tactics=("defense-evasion", "persistence", "privilege-escalation", "initial-access"),
    ))
    t = _extraer_tecnicas(bundle)[0]
    assert t["description"] == "Adversaries may obtain and abuse credentials..."
    assert t["tactics"] == ["defense-evasion", "persistence", "privilege-escalation", "initial-access"]


def test_ignora_kill_chain_phase_de_otro_kill_chain_name():
    # Algunos objetos STIX de terceros reusan kill_chain_phases con un
    # kill_chain_name distinto de "mitre-attack" -- no debe colarse como
    # táctica ATT&CK.
    obj = _attack_pattern(technique_id="T1595")
    obj["kill_chain_phases"].append({"kill_chain_name": "otro-framework", "phase_name": "recon"})
    tecnicas = _extraer_tecnicas(_bundle(obj))
    assert tecnicas[0]["tactics"] == ["credential-access"]


def test_version_del_bundle_encuentra_x_mitre_collection():
    bundle = _bundle(
        {"type": "x-mitre-collection", "name": "Enterprise ATT&CK", "x_mitre_version": "19.1"},
        _attack_pattern(),
    )
    assert _version_del_bundle(bundle) == "19.1"


def test_version_del_bundle_none_si_no_hay_coleccion():
    bundle = _bundle(_attack_pattern())
    assert _version_del_bundle(bundle) is None
