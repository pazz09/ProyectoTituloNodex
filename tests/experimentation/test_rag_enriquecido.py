"""Los controles deben rechazar contaminación aunque cambien nombres o UID."""
from copy import deepcopy

import pytest

from src.experimentation.knowledge import rag_enriquecido as rag


def example():
    return {"historical_case_id": "uwf_hist_001", "original_id": "dev_episode",
            "fragment_sha256": "fragment-a", "partition": "desarrollo", "dataset": "uwf",
            "time_window": [10, 20], "records": [{"source_file_sha256": "source-a",
                "source_line": 5, "uid": "uid-a", "original_event_sha256": "event-a"}]}


def forbidden():
    return {"case_ids": set(), "hashes": set(), "records": set(), "events": set(),
            "uids": set(), "windows": [], "incidents": set(), "incident_shards": set()}


@pytest.mark.parametrize("kind", ["case", "alias", "source", "uid", "derived", "time", "partition",
                                 "same_episode_crop", "same_campaign_week"])
def test_contamination_rejected(kind):
    c, f = example(), forbidden()
    if kind == "case":
        f["case_ids"].add(c["original_id"])
    elif kind == "alias":
        c["original_id"] = "renamed_copy"
        f["hashes"].add(c["fragment_sha256"])
    elif kind == "source":
        f["records"].add(("source-a", 5))
    elif kind == "uid":
        f["uids"].add("uid-a")
    elif kind == "derived":
        # Incluso con nombre y UID cambiados, debe conservarse la identidad
        # del evento original reconstruida desde su procedencia.
        c["records"][0]["uid"] = "changed-uid"
        f["events"].add("event-a")
    elif kind == "time":
        f["windows"].append({"dataset": "uwf", "window": [20, 25]})
    elif kind == "partition":
        c["partition"] = "evaluacion"
    elif kind == "same_episode_crop":
        c.update(incident_id="episode#r3", incident_shard="week-b")
        f["incidents"].add("episode")
    elif kind == "same_campaign_week":
        c.update(incident_id="different_episode", incident_shard="week-a")
        f["incident_shards"].add("week-a")
    with pytest.raises(ValueError):
        rag.validate_disjoint([c], f)


def test_disjoint_records_and_windows_pass():
    assert rag.validate_disjoint([example()], forbidden())["shared_records"] == 0


@pytest.mark.parametrize("kind", ["id", "fragment", "record", "uid", "event", "window"])
def test_internal_duplicates_rejected(kind):
    a, b = example(), deepcopy(example())
    b.update(historical_case_id="uwf_hist_002", original_id="other", fragment_sha256="fragment-b",
             time_window=[30, 40], records=[{"source_file_sha256": "source-b", "source_line": 8,
                 "uid": "uid-b", "original_event_sha256": "event-b"}])
    if kind == "id":
        b['historical_case_id'] = a['historical_case_id']
    elif kind == "fragment":
        b['fragment_sha256'] = a['fragment_sha256']
    elif kind == "record":
        b['records'][0].update(source_file_sha256="source-a", source_line=5)
    elif kind == "uid":
        b['records'][0]['uid'] = "uid-a"
    elif kind == "event":
        b['records'][0]['original_event_sha256'] = "event-a"
    elif kind == "window":
        b['time_window'] = [15, 35]
    with pytest.raises(ValueError):
        rag.validate_disjoint([a, b], forbidden())


def test_selection_is_deterministic_and_covers_patterns():
    pool = [{"original_id": "a", "selection_features": ["x"]},
            {"original_id": "b", "selection_features": ["x"]},
            {"original_id": "c", "selection_features": ["y"]}]
    assert [x['original_id'] for x in rag.choose_diverse(pool, 2)] == ['a', 'c']
    assert rag.choose_diverse(pool, 2) == rag.choose_diverse(list(reversed(pool)), 2)


def test_insufficient_candidates_never_fabricated():
    with pytest.raises(ValueError, match="insuficientes"):
        rag.choose_diverse([], 8)


def test_collection_integrity_uses_serialized_configuration():
    class Collection:
        metadata = {"hnsw:space": "cosine"}
        configuration_json = {"embedding_function": {"name": "sentence_transformer"}}

        @property
        def configuration(self):
            raise AssertionError("No comparar instancias nuevas de funciones de embeddings")

        def get(self, **kwargs):
            return {"ids": ["historical"], "documents": ["signature"], "metadatas": [{"clasificacion": "normal"}],
                    "embeddings": [[1.] + [0.] * 383]}

    assert rag.collection_state(Collection()) == rag.collection_state(Collection())


def test_frozen_corpus_integrity():
    """Valida el artefacto real sin importar Chroma ni cargar embeddings."""
    if not rag.DEFAULT_OUTPUT.exists():
        pytest.skip("Corpus aún no construido")
    cases = rag.load_corpus(rag.DEFAULT_OUTPUT)
    assert len(cases) == 30
    assert {c['partition'] for c in cases} == {'desarrollo'}
    for c in cases:
        assert c['signature'].startswith('v2|')
        assert c['records']
        if c['classification'] == 'normal':
            assert not c['mitre_references']
        if c['dataset'] == 'uwf' and c['classification'] == 'anomalo':
            assert all(r['original_label'] == 'True' for r in c['records'])
            assert c['incident_shard'] not in {'2022-08-28_2022-09-04', '2022-09-11_2022-09-18',
                                               '2022-09-18_2022-09-25'}
