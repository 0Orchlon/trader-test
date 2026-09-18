"""Walk-forward validation (T-27, LLD §21).

**Curve-fitting-ийн хаалт.** In-sample дээр сайжирсан нь шинэ стратеги БИШ —
энэ өгөгдөл дээр таарсан гэсэн үг. Тиймээс out-of-sample сайжралгүй бол
санал огт үүсэхгүй.

Метрикийг ЭНД тооцохгүй: `evaluate(window, value) -> Decimal` нь дуудагчаас
ирнэ. Ингэснээр энэ модуль нь backtest engine-ээс ХАМААРАХГҮЙ, тест нь
детерминистик функцээр ажиллана.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence

#: Хамгийн цөөн fold. Нэг fold нь walk-forward БИШ, зүгээр нэг хуваалт.
MIN_FOLDS = 2

#: Fold нь in-sample-ийн үнэмлэхүй хэмжээний хэдэн хувь хүртэл унаж болох вэ.
COLLAPSE_BAND = Decimal("0.5")


class NotEnoughData(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Fold:
    index: int
    in_sample: Decimal
    out_of_sample: Decimal

    @property
    def held_up(self) -> bool:
        """Out-of-sample нь in-sample-аас ХЭТ доогуур унаагүй эсэх.

        Үржүүлэх харьцуулалт (`out >= in * 0.5`) нь СӨРӨГ метрик дээр
        эсрэгээрээ ажиллана: −84 нь −42-оос бага тул сайн fold ч унана.
        Тиймээс in-sample-ийн ҮНЭМЛЭХҮЙ хэмжээнээс хасна — тэмдгээс
        хамаарахгүй.
        """
        return self.out_of_sample >= self.in_sample - abs(self.in_sample) * COLLAPSE_BAND


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    folds: list[Fold]
    in_sample_metric: Decimal
    out_of_sample_metric: Decimal

    @property
    def fold_count(self) -> int:
        return len(self.folds)

    def to_contract(self) -> dict:
        """contracts.yaml `walk_forward`. Хоёулаа бичигдэнэ — сайныг нь л
        харуулах нь curve-fitting-ийг далдална."""
        return {
            "folds": self.fold_count,
            "in_sample_metric": f"metric={self.in_sample_metric}",
            "out_of_sample_metric": f"metric={self.out_of_sample_metric}",
        }


def split(series: Sequence, folds: int) -> list[tuple[Sequence, Sequence]]:
    """Дараалсан (anchored) хуваалт: fold бүрийн сургалт нь өмнөх БҮХ
    өгөгдөл, шалгалт нь ДАРААГИЙН хэсэг. Ирээдүйг харах зам БАЙХГҮЙ."""
    if folds < MIN_FOLDS:
        raise NotEnoughData(f"folds >= {MIN_FOLDS} байх ёстой, өгсөн нь {folds}")
    if len(series) < folds + 1:
        raise NotEnoughData(f"{folds} fold-д хамгийн багадаа {folds + 1} мөр хэрэгтэй")
    chunk = len(series) // (folds + 1)
    out = []
    for i in range(folds):
        train_end = chunk * (i + 1)
        test_end = chunk * (i + 2) if i < folds - 1 else len(series)
        out.append((series[:train_end], series[train_end:test_end]))
    return out


def run(
    series: Sequence, value, evaluate: Callable[[Sequence, object], Decimal], *, folds: int
) -> WalkForwardResult:
    results = [
        Fold(index=i, in_sample=evaluate(train, value), out_of_sample=evaluate(test, value))
        for i, (train, test) in enumerate(split(series, folds))
    ]
    count = Decimal(len(results))
    return WalkForwardResult(
        folds=results,
        in_sample_metric=sum((f.in_sample for f in results), Decimal("0")) / count,
        out_of_sample_metric=sum((f.out_of_sample for f in results), Decimal("0")) / count,
    )
