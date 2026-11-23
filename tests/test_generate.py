from bots import common, generate


def test_plan_families_are_known_and_allowed():
    for scenario, family, _ in generate.PLAN:
        assert family in common.FAMILIES
        assert family in common.load_scenario(scenario)["families"]
        assert family in common.load_splits()


def test_seeds_are_unique_and_reproducible():
    jobs = generate.build_jobs(scale=2)
    seeds = [s for _, _, s in jobs]
    assert len(seeds) == len(set(seeds))
    assert jobs == generate.build_jobs(scale=2)
    assert min(seeds) >= generate.SEED_BASE


def test_scale_and_only():
    assert len(generate.build_jobs(scale=2)) == 2 * len(generate.build_jobs(scale=1))
    assert {f for _, f, _ in generate.build_jobs(only="http_basic")} == {"http_basic"}
