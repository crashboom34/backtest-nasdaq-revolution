from optimization_presets import get_preset, preset_names


def test_quick_local_preset_values():
    preset = get_preset("Test rapide local", cpu_count=8)

    assert preset.max_rows == 20_000
    assert preset.max_combinations == 12
    assert preset.workers == 1
    assert preset.benchmark_n_sample == 1


def test_medium_preset_values():
    preset = get_preset("Test moyen", cpu_count=8)

    assert preset.max_rows == 100_000
    assert preset.max_combinations == 100
    assert preset.workers == 2
    assert preset.benchmark_n_sample == 3


def test_full_optimization_keeps_worker_choice():
    preset = get_preset("Optimisation complète", cpu_count=8)

    assert preset.full_history is True
    assert preset.max_rows is None
    assert preset.max_combinations is None
    assert preset.workers is None
    assert preset.benchmark_n_sample == 5
    assert preset.configurable_workers is True


def test_powerful_server_has_configurable_limit_and_workers():
    preset = get_preset("Serveur puissant", cpu_count=12)

    assert preset.full_history is True
    assert preset.max_rows is None
    assert preset.max_combinations == 500_000
    assert preset.workers == 12
    assert preset.benchmark_n_sample == 5
    assert preset.configurable_max_combinations is True
    assert preset.configurable_workers is True


def test_custom_preset_leaves_manual_control():
    preset = get_preset("Personnalisé", cpu_count=8)

    assert preset.manual_control is True
    assert preset.max_rows is None
    assert preset.max_combinations is None
    assert preset.workers is None


def test_preset_order_matches_ui_expectation():
    assert preset_names(cpu_count=8) == [
        "Test rapide local",
        "Test moyen",
        "Optimisation complète",
        "Serveur puissant",
        "Personnalisé",
    ]
