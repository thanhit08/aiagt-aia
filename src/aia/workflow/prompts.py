from pathlib import Path
import os


def _candidate_prompt_dirs() -> list[Path]:
    candidates: list[Path] = []
    env_dir = os.getenv("AIA_PROMPTS_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path.cwd() / "specs" / "v1" / "prompts")
    candidates.append(Path(__file__).resolve().parents[4] / "specs" / "v1" / "prompts")
    return candidates


def load_prompt(name: str) -> str:
    for base_dir in _candidate_prompt_dirs():
        path = base_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")

    searched = ", ".join(str(p) for p in _candidate_prompt_dirs())
    raise FileNotFoundError(f"Prompt file '{name}' not found. Searched: {searched}")


def render_template(template: str, **kwargs: str) -> str:
    output = template
    for key, value in kwargs.items():
        output = output.replace("{{" + key + "}}", value)
    return output
