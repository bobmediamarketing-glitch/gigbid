"""Fast unit tests for metrics, claim verification, query decomposition and the BM25 pipeline path."""
from __future__ import annotations

from pathlib import Path

import pytest

from evals.metrics import cohen_kappa, mrr, ndcg_at_k, prf, recall_at_k
from rag.ingest.loaders import Corpus
from rag.pipeline import Pipeline, PipelineConfig, build_units, rrf
from rag.query import decompose, expand
from rag.verify import check_sentence, classify, verify_text

ROOT = Path(__file__).resolve().parents[2]


def test_metrics():
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 5) == 1.0
    assert recall_at_k(["a", "x"], set("abcdefg"), 5) == 0.2      # capped: 1 of min(5, 7)
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert ndcg_at_k(["a", "b"], {"a": 2, "b": 1}, 10) == pytest.approx(1.0)
    assert ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 10) < 1.0
    assert prf([True, True, False], [True, False, True])["f1"] == 0.5
    assert cohen_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], "quadratic") == 1.0
    assert cohen_kappa([1, 1, 5, 5], [5, 5, 1, 1], "quadratic") < 0


def test_claim_verification():
    ev = {"ai_ml-cs-05": "The project cut manual effort by 74%. Built with huggingface."}
    assert check_sentence("It cut manual effort by 74% [ai_ml-cs-05].", ev)[0] is True
    assert check_sentence("It cut effort by 90% [ai_ml-cs-05].", ev)[0] is False        # wrong number
    assert check_sentence("It cut effort by 74% [ai_ml-cs-99].", ev)[0] is False        # unknown id
    assert check_sentence("I have 12 years of experience.", ev)[0] is False             # uncited metric
    assert check_sentence("I would start with a short call.", ev)[0] is None            # not a claim
    text, v = verify_text("Good opener. It cut effort by 74% [ai_ml-cs-05]. I have 12 years in NLP.", ev)
    assert "12 years" not in text and "74%" in text and v.checked == 2 and v.supported == 1


def test_decompose_and_expand():
    post = "We need an agent.\n\nRequirements:\n- Experience with redis\n- An async python api with automatic docs"
    assert decompose(post) == ["Experience with redis", "An async python api with automatic docs"]
    assert decompose("Details in chat.") == ["Details in chat."]                  # vague: whole post
    assert "fastapi" in expand("An async python api with automatic docs").lower()


def test_rrf_rewards_agreement():
    fused = rrf([[("a", 1), ("b", 1)], [("b", 1), ("c", 1)]])
    assert fused[0][0] == "b"


def test_multivector_units_split_readme_and_code():
    c = Corpus(ROOT / "data" / "personas" / "fullstack")
    repo = next(d for d in c.all() if d.type == "repo")
    units = [t for d, t in build_units([repo], "multivector", 60) if d == repo.id]
    assert any(" readme: " in u for u in units) and any(" code: " in u for u in units)


def test_bm25_pipeline_finds_exact_tool_names():
    c = Corpus(ROOT / "data" / "personas" / "data_analyst")
    pipe = Pipeline(c, PipelineConfig(name="t", query="both", units="multivector", retrieval="bm25"))
    hits = pipe.search("Requirements:\n- Experience with dbt\n- Experience with snowflake", k=5)
    assert hits and any({"dbt", "snowflake"} & set(h.doc.skills) for h in hits)
    assert all(h.doc.persona == "data_analyst" for h in hits)


def test_partly_supported_claims_are_rewritten_not_dropped():
    ev = {"ai_ml-cs-05": "The project cut manual effort by 74%."}
    label, _, fixed = classify("It cut effort by 74% [ai_ml-cs-05][ai_ml-cs-77].", ev)
    assert label == "partly" and "cs-77" not in fixed and "[ai_ml-cs-05]" in fixed
    text, v = verify_text("It cut effort by 74% [ai_ml-cs-05][ai_ml-cs-77]. It is 99% accurate [ai_ml-cs-05].", ev)
    assert (v.supported, v.partly, v.unsupported, v.unsupported_after) == (0, 1, 1, 0)
