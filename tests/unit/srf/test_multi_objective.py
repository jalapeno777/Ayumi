"""Tests for SRF Multi-Objective Optuna."""

import optuna
from srf.multi_objective import (
    pareto_front_trials,
    summarize_pareto_front,
)


class TestParetoFront:
    def test_simple_pareto(self):
        """Two objectives, clear Pareto front."""
        study = optuna.create_study(
            directions=["maximize", "minimize"],
            sampler=optuna.samplers.RandomSampler(seed=42),
        )

        def obj(trial):
            x = trial.suggest_float("x", 0, 10)
            return (x, x * 2)  # maximize x, minimize x*2

        study.optimize(obj, n_trials=20)
        front = pareto_front_trials(study)
        # All non-dominated trials form the Pareto front
        assert len(front) >= 1
        assert len(front) <= 20

    def test_dominated_trial_excluded(self):
        study = optuna.create_study(
            directions=["maximize", "maximize"],
            sampler=optuna.samplers.RandomSampler(seed=42),
        )

        def obj(trial):
            x = trial.suggest_float("x", 0, 1)
            y = trial.suggest_float("y", 0, 1)
            return (x, y)

        study.optimize(obj, n_trials=30)
        front = pareto_front_trials(study)

        # Verify every front trial is actually non-dominated
        all_trials = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        for ft in front:
            dominated = False
            for ot in all_trials:
                if ot.number == ft.number:
                    continue
                if (
                    ot.values[0] >= ft.values[0]
                    and ot.values[1] >= ft.values[1]
                    and (ot.values[0] > ft.values[0] or ot.values[1] > ft.values[1])
                ):
                    dominated = True
                    break
            assert not dominated, f"Trial {ft.number} is dominated but in front"

    def test_empty_study(self):
        study = optuna.create_study(directions=["maximize"])
        front = pareto_front_trials(study)
        assert front == []

    def test_summarize(self):
        study = optuna.create_study(directions=["maximize"], sampler=optuna.samplers.RandomSampler(seed=42))
        study.optimize(lambda t: (t.suggest_float("x", 0, 1),), n_trials=5)
        result = summarize_pareto_front(study, top_k=3)
        assert len(result) <= 3
        assert "trial_number" in result[0]
        assert "values" in result[0]
        assert "params" in result[0]


class TestModuleInterface:
    def test_imports(self):
        import srf.multi_objective as mo

        assert callable(mo.pareto_front_trials)
        assert callable(mo.summarize_pareto_front)
        assert callable(mo.run_multi_objective_study)
        assert callable(mo.build_multi_objective)

    def test_backup_module(self):
        from srf.backup_db import backup_db

        assert callable(backup_db)

    def test_nightly_module(self):
        from srf.nightly_topk import nightly_topk

        assert callable(nightly_topk)

    def test_weekly_module(self):
        from srf.weekly_sweep import weekly_sweep

        assert callable(weekly_sweep)
