from .wrapper import CachingWrapper, InMemoryCache, SqliteCache

cached = CachingWrapper.cache_fn
