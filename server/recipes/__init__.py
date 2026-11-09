import json
from functools import lru_cache

from ..config import RECIPE_DIR


@lru_cache
def all_recipes() -> dict[str, dict]:
    out = {}
    for path in sorted(RECIPE_DIR.glob("*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        out[recipe["id"]] = recipe
    return dict(sorted(out.items(), key=lambda kv: kv[1].get("order", 99)))


def get_recipe(recipe_id: str) -> dict:
    recipes = all_recipes()
    if recipe_id not in recipes:
        raise KeyError(f"unknown recipe: {recipe_id}")
    return recipes[recipe_id]


def event_ids(recipe: dict) -> list[str]:
    return [s["event"]["id"] for s in recipe["steps"]]
