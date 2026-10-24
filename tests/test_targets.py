"""
Tests for target weights (src/portfolio/targets.py). Tickers and weights
are made up; real holdings never go in tests.
"""

import numpy as np
import pandas as pd
import pytest

from src.portfolio.exposure import risk_contributions
from src.portfolio.targets import (
    Limits,
    TargetSettings,
    TickerTarget,
    equal_risk_weights,
    load_targets,
    target_weights,
)


def _cov(vols, corr):
    vols = np.asarray(vols, dtype=float)
    names = [f"T{i}" for i in range(len(vols))]
    return pd.DataFrame(np.outer(vols, vols) * np.asarray(corr), index=names, columns=names)


class TestEqualRiskWeights:
    def test_uncorrelated_is_inverse_volatility(self):
        cov = _cov([0.1, 0.2, 0.4], np.eye(3))
        inverse = np.array([10, 5, 2.5]) / 17.5
        assert list(equal_risk_weights(cov)) == pytest.approx(list(inverse))

    def test_equal_volatility_and_correlation_is_equal_weight(self):
        corr = np.full((4, 4), 0.3) + 0.7 * np.eye(4)
        assert list(equal_risk_weights(_cov([0.2] * 4, corr))) == pytest.approx([0.25] * 4)

    def test_correlated_pair_gets_less(self):
        corr = np.array([[1.0, 0.9, 0.0], [0.9, 1.0, 0.0], [0.0, 0.0, 1.0]])
        cov = _cov([0.2, 0.2, 0.2], corr)
        weights = equal_risk_weights(cov)
        assert weights["T2"] > 0.4 > weights["T0"] == pytest.approx(weights["T1"])
        shares = risk_contributions(weights, cov)
        assert list(shares) == pytest.approx([1 / 3] * 3)

    def test_risk_shares_equal_on_a_realistic_matrix(self):
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.03, (104, 12)) + rng.normal(0, 0.02, (104, 1))
        cov = pd.DataFrame(np.cov(returns.T))
        weights = equal_risk_weights(cov)
        assert weights.sum() == pytest.approx(1.0)
        assert list(risk_contributions(weights, cov)) == pytest.approx([1 / 12] * 12, abs=1e-8)


# ==================== Targets ====================


def _settings(**limits):
    return TargetSettings(limits=Limits(**limits))


def _targets(weights, sectors=None, settings=None, exits=(), frozen=(), cov=None):
    names = list(weights)
    cov = cov if cov is not None else pd.DataFrame(np.eye(len(names)) * 0.04, names, names)
    return target_weights(
        weights=weights,
        cov=cov,
        sectors=sectors or {t: f"Sector {t}" for t in names},
        settings=settings or _settings(max_position=1.0, max_sector=1.0),
        exits=set(exits),
        frozen=set(frozen),
    )


class TestTargetWeights:
    def test_equal_risk_over_the_free_holdings(self):
        targets, notes = _targets({"A": 0.5, "B": 0.3, "C": 0.2})
        assert targets == pytest.approx({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
        assert notes["free"] == 3 and notes["unallocated"] == pytest.approx(0)

    def test_exit_frozen_and_fixed_take_their_share_first(self):
        settings = _settings(max_position=1.0, max_sector=1.0)
        settings.tickers["FUND"] = TickerTarget(target=0.3)
        targets, notes = _targets(
            {"FUND": 0.1, "OUT": 0.2, "FLAG": 0.1, "A": 0.3, "B": 0.3},
            settings=settings,
            exits={"OUT"},
            frozen={"FLAG"},
        )
        assert targets["OUT"] == 0.0
        assert targets["FLAG"] == pytest.approx(0.1)  # kept until looked into
        assert targets["FUND"] == pytest.approx(0.3)
        assert targets["A"] == pytest.approx(0.3) == targets["B"]  # (1 - 0.4) / 2
        assert notes["fixed"] == ["FLAG", "FUND"]

    def test_no_history_keeps_its_weight(self):
        cov = pd.DataFrame(np.eye(2) * 0.04, ["A", "B"], ["A", "B"])
        targets, _ = _targets({"A": 0.45, "B": 0.45, "NEW": 0.1}, cov=cov)
        assert targets == pytest.approx({"A": 0.45, "B": 0.45, "NEW": 0.1})

    def test_position_cap_spreads_the_excess(self):
        # A is the calmest, so ERC wants it at 2/3; the 40% cap moves the rest to B and C
        names = ["A", "B", "C"]
        cov = pd.DataFrame(np.diag([0.01, 0.16, 0.16]), names, names)
        targets, notes = _targets(
            {"A": 0.4, "B": 0.3, "C": 0.3},
            cov=cov,
            settings=_settings(max_position=0.4, max_sector=1.0),
        )
        assert targets == pytest.approx({"A": 0.4, "B": 0.3, "C": 0.3})
        assert notes["capped"] == ["A"]

    def test_ticker_cap_overrides_the_limit(self):
        settings = _settings(max_position=1.0, max_sector=1.0)
        settings.tickers["A"] = TickerTarget(max=0.2)
        targets, _ = _targets({"A": 0.5, "B": 0.5}, settings=settings)
        assert targets == pytest.approx({"A": 0.2, "B": 0.8})

    def test_sector_cap(self):
        sectors = {"E1": "Energy", "E2": "Energy", "T": "Tech", "F": "Financials"}
        targets, notes = _targets(
            {t: 0.25 for t in sectors},
            sectors=sectors,
            settings=_settings(max_position=1.0, max_sector=0.35),
        )
        assert targets["E1"] + targets["E2"] == pytest.approx(0.35)
        assert targets["T"] == pytest.approx(0.325) == targets["F"]
        assert sum(targets.values()) == pytest.approx(1.0)
        assert notes["capped"] == ["E1", "E2"]

    def test_funds_are_exempt_from_the_sector_cap(self):
        sectors = {"F1": "Fund", "F2": "Fund", "S": "Tech"}
        targets, _ = _targets(
            {t: 1 / 3 for t in sectors},
            sectors=sectors,
            settings=_settings(max_position=1.0, max_sector=0.35),
        )
        assert targets == pytest.approx({t: 1 / 3 for t in sectors})

    def test_everything_capped_leaves_weight_unallocated(self):
        targets, notes = _targets(
            {"A": 0.5, "B": 0.5}, settings=_settings(max_position=0.3, max_sector=1.0)
        )
        assert targets == pytest.approx({"A": 0.3, "B": 0.3})
        assert notes["unallocated"] == pytest.approx(0.4)


# ==================== Targets file ====================


class TestLoadTargets:
    def test_missing_file_gives_defaults(self, tmp_path):
        settings = load_targets(tmp_path / "targets.toml")
        assert settings.limits == Limits()
        assert settings.source is None

    def test_reads_limits_and_tickers(self, tmp_path):
        path = tmp_path / "targets.toml"
        path.write_text(
            "[limits]\nmax_position = 0.08\nmax_new = 2\n\n"
            '[ticker."xyz.de"]\ntarget = 0.12\n\n[ticker.ABC]\nmax = 0.05\n',
            encoding="utf-8",
        )
        settings = load_targets(path)
        assert settings.limits.max_position == 0.08
        assert settings.limits.max_new == 2 and isinstance(settings.limits.max_new, int)
        assert settings.limits.max_sector == 0.35  # default kept
        assert settings.tickers["XYZ.DE"].target == 0.12
        assert settings.tickers["ABC"].max == 0.05
        assert settings.source == str(path)

    @pytest.mark.parametrize(
        "text, message",
        [
            ("[limits]\nmax_positon = 0.1\n", "unknown limit"),
            ("[limit]\nmax_position = 0.1\n", "unknown section"),
            ("[ticker.ABC]\nweight = 0.1\n", "unknown key"),
            ("[ticker.ABC]\ntarget = 10\n", "between 0 and 1"),
        ],
    )
    def test_mistakes_are_reported(self, tmp_path, text, message):
        path = tmp_path / "targets.toml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_targets(path)
