"""Build the Lambda zip (Python 3.12, arm64) without Docker: deploy/.build/lambda.zip

    backend\\.venv\\Scripts\\python deploy\\build.py

Linux arm64 wheels are downloaded with pip --platform, pinned to the versions in backend/.venv
(the ones the tests ran against). The zip is written with Unix permissions so run.sh stays
executable even when built on Windows.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
OUT = Path(__file__).resolve().parent / ".build"
PKG = OUT / "package"
ZIP = OUT / "lambda.zip"
# Lambda python3.12 runs on Amazon Linux 2023 (glibc 2.34), so wheels up to manylinux_2_34 work
PLATFORMS = [f"--platform=manylinux_{v}_aarch64" for v in ("2_34", "2_28", "2_17")] + ["--platform=manylinux2014_aarch64"]
SKIP_REQS = ("pytest",)  # test-only
SKIP_DIRS = {"__pycache__"}
SKIP_TOP = ("boto3", "botocore", "s3transfer", "bin")  # runtime provides boto3; bin = console scripts


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    PKG.mkdir(parents=True)

    reqs = [
        line for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith(SKIP_REQS)
    ]
    reqs = ["uvicorn>=0.30" if r.startswith("uvicorn") else r for r in reqs]  # no uvloop/watchfiles needed
    (OUT / "requirements.txt").write_text("\n".join(reqs), encoding="utf-8")
    frozen = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
    (OUT / "constraints.txt").write_text(frozen.stdout, encoding="utf-8")

    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "-r", str(OUT / "requirements.txt"), "-c", str(OUT / "constraints.txt"),
            "--target", str(PKG), *PLATFORMS,
            "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:",
        ],
        check=True,
    )
    shutil.copytree(BACKEND / "app", PKG / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        run = zipfile.ZipInfo("run.sh")
        run.external_attr = 0o100755 << 16
        run.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(run, (ROOT / "deploy" / "run.sh").read_bytes().replace(b"\r\n", b"\n"))
        for path in sorted(PKG.rglob("*")):
            rel = path.relative_to(PKG)
            if path.is_dir() or SKIP_DIRS & set(rel.parts) or rel.parts[0].startswith(SKIP_TOP):
                continue
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = (0o100755 if path.suffix == ".so" else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    print(f"built {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
