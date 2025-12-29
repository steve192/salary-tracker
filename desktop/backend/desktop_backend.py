import argparse
import os
import sys
from pathlib import Path


def resolve_project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS)
    else:
        root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    return root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Salary Tracker desktop backend")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resolve_project_root()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salary_tracker.settings")

    import django
    from django.conf import settings
    from django.core.management import call_command, execute_from_command_line

    django.setup()

    if os.environ.get("DJANGO_DESKTOP_SKIP_MIGRATE", "false").lower() != "true":
        call_command("migrate", interactive=False, verbosity=0)

    if os.environ.get("DJANGO_DESKTOP_SKIP_COLLECTSTATIC", "false").lower() != "true":
        manifest_path = Path(settings.STATIC_ROOT) / "staticfiles.json"
        if not manifest_path.exists():
            call_command("collectstatic", interactive=False, verbosity=0)

    execute_from_command_line(
        ["manage.py", "runserver", f"127.0.0.1:{args.port}", "--noreload"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
