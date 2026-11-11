"""Check the SPEC cloud graph; explicitly sync references/export or run probes."""
import argparse
import json
import sys

from backend.config import Settings
from src.utils.config import load_config
from src.utils.errors import AnalyticsError
from src.utils.langflow import LangflowConformance, write_conformance_report


def main() -> int:
    """Make any correction explicit and keep the default command read-only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync", action="store_true", help="Sincronizar referencias existentes y export; no cambia modelos ni claves.")
    parser.add_argument("--probe", action="store_true", help="Probar Groq y Gemini con un caso público existente; consume API cloud.")
    args = parser.parse_args()
    settings = load_config()
    try:
        connection = LangflowConformance(settings, Settings.from_env())
        result = connection.synchronize() if args.sync else connection.check()
        if args.probe:
            result["primary_probe"] = connection.probe()
            result["fallback_probe"] = connection.probe(force_fallback=True)
        write_conformance_report(settings, result)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result["credential_references_valid"] and result["export_matches_runtime"] else 1
    except AnalyticsError as error:
        write_conformance_report(settings, {"status": "failed", "safe_reason": str(error)})
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
