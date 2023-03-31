# Cheapi (cheap API) 

Lightweight wrapper to cache expensive function results in-memory or on disk.


## Installation

```bash
pip install cheapi
```

## Usage

```python
from cheapi import CachingWrapper
import openai


def _ask_chatgpt(prompt):
    res = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant for a software engineer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        timeout=10,
    )
    choice, *_ = res["choices"]
    usage = res["usage"]["total_tokens"]
    print(f"OpenAI usage: {usage}")

    result = choice["message"]["content"]
    return result


ash_chatgpt = CachingWrapper(_ask_chatgpt, cache_backend="memory")

for i in range(2):
    print(ash_chatgpt("Write a short joke about caching?") + "\n")
```
or even simpler:
```python

from cheapi import cached

@cached(cache_backend="memory")
def ask_chatgpt(prompt):
    ...

for i in range(2):
    print(ask_chatgpt("Write a short joke about caching?") + "\n")
```

## Caching backends

Using memory backend is mostly equivalent to using `functools.lru_cache` but with more configuration.
SQLite backend is useful for persistent caching, and is similar to `joblib.Memory`.
Cloud backend is being dreamed of, but not implemented yet.

## Why? 

[NIH](https://en.wikipedia.org/wiki/Not_invented_here) + so I could [RIIR](https://www.urbandictionary.com/define.php?term=riir) later.