import pytest

from cheapi import CachingWrapper, SqliteCache, cached


class Function:
    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return f"result_{self.calls}"


@pytest.mark.parametrize("cache_type", ["memory", "sqlite"])
def test_base(cache_type):
    fn = Function()
    cache = CachingWrapper(fn, cache_backend=cache_type, max_size=2, max_age=None)
    assert cache(1, 2, 3) == "result_1"
    assert cache(1, 2, 3) == "result_1"
    assert fn.calls == 1
    assert cache(1, 2, 3, a=1) == "result_2"
    assert fn.calls == 2
    assert cache(1, 2, 3, a=2) == "result_3"
    assert fn.calls == 3
    assert len(cache.cache) == 2

    assert cache(1, 2, 3) == "result_4"

    if cache_type == "sqlite":
        assert isinstance(cache.cache, SqliteCache)
        path = cache.cache.cache_file
        assert path.exists()
        cache.cache.clear()
        assert not path.exists()


def test_decorator():
    fn = Function()

    @cached
    def run(*args, **kwargs):
        return fn(*args, **kwargs)

    assert run(1, 2, 3) == "result_1"
    assert run(1, 2, 3) == "result_1"

    assert fn.calls == 1


def test_decorator_kwargs():
    fn = Function()

    @cached(max_size=2, max_age=None)
    def run(*args, **kwargs):
        return fn(*args, **kwargs)

    assert run(1, 2, 3) == "result_1"
    assert run(1, 2, 3) == "result_1"

    assert fn.calls == 1
