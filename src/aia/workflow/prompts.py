from pathlib import Path


def _root_path() -> Path:
    return Path(__file__).resolve().parents[3]


def load_prompt(name: str) -> str:
    path = _root_path() / "specs" / "v1" / "prompts" / name
    return path.read_text(encoding="utf-8")


def render_template(template: str, **kwargs: str) -> str:
    output = template
    for key, value in kwargs.items():
        output = output.replace("{{" + key + "}}", value)
    return output

