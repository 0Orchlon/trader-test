"""Bounded search (T-27, LLD §21, AC-22).

Хайлт нь `tuning_whitelist.yaml`-ийн муж ба `step`-ээр БҮРЭН хязгаарлагдана.
Муж гадуурх утга нь «сайн үр дүн» гаргалаа ч санал болж ГАРАХГҮЙ — хайлтын
орон зай нь batлагдсан сүлжээ, тасралтгүй муж биш.

Санал үүсэх ДӨРВӨН нөхцөл (бүгд хангагдана):
1. Утга нь whitelist-ийн муж + step дотор.
2. Out-of-sample метрик нь одоогийн утгынхаас САЙН.
3. Out-of-sample нь in-sample-ийн ард хэт унаагүй (curve-fitting).
4. `applies_to` = `paper`. `live` нь зөвхөн хүний `promote`.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence

from app.tuning.walkforward import WalkForwardResult, run as walk_forward
from app.tuning.whitelist import ParameterSpec


@dataclass(frozen=True, slots=True)
class Candidate:
    value: Decimal
    walk_forward: WalkForwardResult

    @property
    def score(self) -> Decimal:
        return self.walk_forward.out_of_sample_metric


@dataclass(frozen=True, slots=True)
class SearchResult:
    parameter: str
    current_value: Decimal
    best: Candidate | None
    #: Санал үүсээгүй бол ШАЛТГААН нь ил — чимээгүй хоосон үр дүн биш.
    reason: str | None = None

    @property
    def has_proposal(self) -> bool:
        return self.best is not None


def search(
    spec: ParameterSpec,
    series: Sequence,
    evaluate: Callable[[Sequence, Decimal], Decimal],
    *,
    current_value: Decimal,
    folds: int,
) -> SearchResult:
    grid = spec.grid()
    candidates = [
        Candidate(value=value, walk_forward=walk_forward(series, value, evaluate, folds=folds))
        for value in grid
    ]
    baseline = next((c for c in candidates if c.value == current_value), None)
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    best = ranked[0]

    if best.value == current_value:
        return SearchResult(spec.name, current_value, None, "одоогийн утга хамгийн сайн хэвээр")
    if baseline is not None and best.score <= baseline.score:
        return SearchResult(
            spec.name, current_value, None, "out-of-sample сайжралгүй — санал үүсэхгүй"
        )
    if not all(f.held_up for f in best.walk_forward.folds):
        return SearchResult(
            spec.name, current_value, None, "fold-уудад тогтворгүй — curve-fitting сэжигтэй"
        )
    return SearchResult(spec.name, current_value, best)
