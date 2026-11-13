"""Content policy for scene prompts, loaded from policy.toml."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("policy.toml")


@dataclass
class Result:
    prompt: str
    negative: str = ""
    no_people: bool = False
    rules: list = field(default_factory=list)


class Policy:
    def __init__(self, data):
        self.negative = data.get("defaults", {}).get("negative", "")
        self.places = [(re.compile(p["match"]), p["scene"]) for p in data.get("places", [])]
        self.rules = []
        for r in data.get("rules", []):
            if not r.get("enabled", True):
                continue
            r = dict(r)
            r["patterns"] = [re.compile(m) for m in r["match"]]
            self.rules.append(r)

    def apply(self, prompt):
        result = Result(prompt=prompt, negative=self.negative)
        for rule in self.rules:
            if not any(p.search(result.prompt) for p in rule["patterns"]):
                continue
            result.rules.append(rule["name"])
            if rule.get("negative"):
                result.negative = ", ".join(filter(None, [result.negative, rule["negative"]]))
            result.no_people = result.no_people or rule.get("no_people", False)
            action = rule["action"]
            if action == "replace":
                scene = rule["scene"]
                if rule.get("use_places"):
                    scene = next((s for p, s in self.places if p.search(result.prompt)), scene)
                result.prompt = f"deserted, nobody present, {scene}" if rule.get("no_people") else scene
                break
            if action == "substitute":
                for p in rule["patterns"]:
                    result.prompt = p.sub(rule["replacement"], result.prompt)
            elif action == "append":
                result.prompt = f"{result.prompt}, {rule['text']}"
        if result.no_people:
            result.negative = ", ".join(
                filter(None, [result.negative, "person, people, human, man, woman, crowd, face, figure, silhouette"])
            )
        result.prompt = re.sub(r"\s+", " ", result.prompt).strip(" ,")
        return result


def load(path=None):
    """Load a policy file. Returns None when path is "off"."""
    if str(path).lower() == "off":
        return None
    return Policy(tomllib.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")))
