import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / ".env"


def load_env_file(path: Path) -> dict:
    values: dict = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def resolve_setting(file_values: dict, name: str, default: str = "") -> str:
    env_name = name.upper()
    if env_name in os.environ and os.environ[env_name]:
        return os.environ[env_name]
    return file_values.get(name, file_values.get(env_name, default))


def main() -> int:
    file_values = load_env_file(ENV_PATH)
    api_key = resolve_setting(file_values, "OPENAI_API_KEY")
    base_url = resolve_setting(file_values, "BASE_URL", "https://api.gmi-serving.com/v1")
    model = resolve_setting(file_values, "MODEL", "MiniMaxAI/MiniMax-M3")
    max_tokens = int(resolve_setting(file_values, "MAX_TOKENS", "1024"))

    if not api_key:
        print("OPENAI_API_KEY missing in .env", file=sys.stderr)
        return 2

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a capable AI coding assistant"},
            {"role": "user", "content": "Refactor this multi-file Python module to make it async-ready"},
        ],
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    timeout = int(os.environ.get("MINIMAX_PROBE_TIMEOUT", "60"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")

    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw

    print(json.dumps({
        "url": url,
        "model": model,
        "status": status,
        "body": parsed,
    }, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
