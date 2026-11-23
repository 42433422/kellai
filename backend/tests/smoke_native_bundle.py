"""Inspect an installed CI candidate and run its packaged backend, without external accounts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def single(paths: list[Path]) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"Expected one candidate artifact, found {len(paths)}")
    return paths[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads((ROOT / "backend/build-info.json").read_text(encoding="utf-8"))
    assert expected["source_sha"] == args.source_sha, "Candidate checkout identity does not match the requested source"
    bundles = ROOT / "desktop/src-tauri/target/release/bundle"
    with tempfile.TemporaryDirectory(prefix="kellai-native-candidate-") as temporary:
        directory = Path(temporary)
        mounted = False
        install_dir = directory / "installed"
        try:
            if sys.platform == "win32":
                package = single(list((bundles / "nsis").glob("*.exe")))
                subprocess.run([str(package), "/S", f"/D={install_dir}"], check=True, timeout=180)
                shell = install_dir / "kellai-desktop.exe"
                resources = install_dir
                binary_name = "kellai-backend.exe"
            elif sys.platform == "darwin":
                package = single(list((bundles / "dmg").glob("*.dmg")))
                install_dir.mkdir()
                subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint",
                                str(install_dir), str(package)], check=True, timeout=120, capture_output=True)
                mounted = True
                app = single(list(install_dir.glob("*.app")))
                info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
                shell = app / "Contents/MacOS" / info["CFBundleExecutable"]
                resources = app / "Contents/Resources"
                binary_name = "kellai-backend"
            else:
                raise RuntimeError("The native installer smoke runs on Windows or macOS")
            manifest = resources / "backend/build-info.json"
            binary = resources / "backend" / binary_name
            assert json.loads(manifest.read_text(encoding="utf-8")) == expected, "Bundled manifest differs from source"
            shell_info = subprocess.run([str(shell), "--build-info"], check=True, timeout=20,
                                        capture_output=True, text=True, encoding="utf-8")
            assert json.loads(shell_info.stdout) == expected, "Native shell embeds a different source identity"
            assert digest(binary) == digest(ROOT / "backend/dist" / binary_name), "Installer changed the frozen backend"
            backend_evidence = directory / "backend-smoke.json"
            subprocess.run([sys.executable, str(ROOT / "backend/tests/smoke_packaged_backend.py"), str(binary),
                            "--expected-build-info", str(manifest), "--output", str(backend_evidence)],
                           check=True, timeout=60)
            evidence = {"status": "PASS", "artifact_kind": "unsigned_ci_candidate", "build_info": expected,
                        "package_name": package.name, "package_sha256": digest(package),
                        "shell_sha256": digest(shell), "shell_identity_matches": True,
                        "packaged_backend": json.loads(backend_evidence.read_text(encoding="utf-8")),
                        "signature_verified": False, "installed_gui_and_keyring_verified": False}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        finally:
            if mounted:
                subprocess.run(["hdiutil", "detach", str(install_dir)], check=True, timeout=60, capture_output=True)
            if os.name == "nt" and (install_dir / "uninstall.exe").exists():
                subprocess.run([str(install_dir / "uninstall.exe"), "/S", f"_?={install_dir}"],
                               check=True, timeout=120)


if __name__ == "__main__":
    main()
