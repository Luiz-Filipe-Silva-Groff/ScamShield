"""Verifica cenários contra uma API em execução; não precisa de dependências."""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads(
        (root / "src/scamshield/data/demo/manifest.json").read_text(encoding="utf-8")
    )
    key = os.environ.get("SCAMSHIELD_TEST_API_KEY", "scamshield-demo-local")
    failures = 0
    for case in cases:
        payload = (root / "demo/requests" / (case["id"] + ".json")).read_bytes()
        request = urllib.request.Request(
            args.url + "/v1/analise",
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": key},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.load(response)
            passed = (result["status"], result["score"]) == (
                case["expected_status"],
                case["expected_score"],
            )
            print(
                f"{'OK' if passed else 'FALHOU'} {case['id']}: {result['status']} / {result['score']}"
            )
            failures += not passed
        except (urllib.error.URLError, ValueError, KeyError):
            print(f"FALHOU {case['id']}: não foi possível verificar a resposta")
            failures += 1
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
