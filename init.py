"""Init script for auto-imagegen plugin. Delegates all logic to image_gen.py."""
import os
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_NAME = "auto-imagegen"
TARGET_DIR = os.path.join(os.path.expanduser("~"), ".agents", "skills", SKILL_NAME)


def check_codex():
    import shutil
    codex_path = shutil.which("codex")
    if codex_path:
        try:
            import subprocess
            r = subprocess.run([codex_path, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return r.stdout.strip().split()[-1], codex_path
        except Exception:
            pass
        return "installed", codex_path
    return None, None


def main():
    print("=== auto-imagegen Setup ===\n")

    # [1/4] Codex CLI
    print("[1/4] Checking Codex CLI...")
    version, codex_path = check_codex()
    if version:
        print(f"  [OK] Codex CLI {version} ({codex_path})")
    else:
        print("  [FAIL] Codex CLI not found")
        print("  [INFO] Install with: npm install -g @openai/codex")
        return False

    # [2/4] Copy skill files
    print("[2/4] Setting up skill files...")
    if os.path.exists(TARGET_DIR):
        print(f"  [SKIP] Already exists: {TARGET_DIR}")
    else:
        parent = os.path.dirname(TARGET_DIR)
        os.makedirs(parent, exist_ok=True)
        import shutil
        shutil.copytree(SKILL_DIR, TARGET_DIR, dirs_exist_ok=True)
        print(f"  [OK] Copied to {TARGET_DIR}")

    # [3/4] Run --init on image_gen.py (discovers providers, writes providers.json, disables view_image)
    print("[3/4] Running initialization checks...")
    script = os.path.join(SKILL_DIR, "scripts", "image_gen.py")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, script, "--init"],
            capture_output=True, text=True, timeout=30,
        )
        print(r.stderr)
        if r.returncode != 0:
            print("  [FAIL] Initialization failed")
            return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False

    # [4/4] Test providers
    print("[4/4] Testing providers...")
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, script, "--inspect"],
            capture_output=True, text=True, timeout=30,
        )
        print(r.stderr)
    except Exception as e:
        print(f"  [WARN] inspect failed: {e}")

    print("\n=== Setup Complete ===")
    print(f'\nYou can now generate images with:')
    print(f'  python "{TARGET_DIR}\\\\scripts\\\\image_gen.py" "your prompt"')
    print(f'\nOr run --inspect anytime to see available models:')
    print(f'  python "{TARGET_DIR}\\\\scripts\\\\image_gen.py" --inspect')
    return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
