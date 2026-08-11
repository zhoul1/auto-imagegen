import sys, os, re, json, time, base64, urllib.request, urllib.error, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

IMAGE_MODEL_KEYWORDS = ["gpt-image", "dall", "flux", "stable", "image", "midjourney", "imagen"]
DEFAULT_PROVIDERS_PATH = os.path.join(os.path.expanduser("~"), ".codex", "auto-imagegen", "providers.json")
DEFAULT_IMG_DIR = os.path.join(os.path.expanduser("~"), ".codex", "generated_images")
SKIP_PORT = "57321"  # Codex++ aggregate relay port - never call it directly


# ---------- small helpers ----------

def strip_v1(base):
    base = base.strip().rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def is_local_aggregate(base):
    return SKIP_PORT in base


def mask_key(key):
    if not key:
        return "(none)"
    if len(key) <= 10:
        return "***"
    return key[:6] + "***" + key[-4:]


def default_img_dir():
    """Output dir: <cwd>/generated_images, falling back to ~/.codex/generated_images when cwd is not writable."""
    try:
        d = os.path.join(os.getcwd(), "generated_images")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return DEFAULT_IMG_DIR


def model_ids(models):
    return [m["id"] if isinstance(m, dict) else m for m in models]


def pick_best_model(image_models):
    ids = model_ids(image_models)
    if not ids:
        return None
    for kw in IMAGE_MODEL_KEYWORDS:
        for m in ids:
            if kw in m.lower():
                return m
    return ids[0]


# ---------- provider discovery (all machine-specific sources) ----------

def read_config_providers():
    """Parse [model_providers.*] sections from ~/.codex/config.toml."""
    home = os.path.expanduser("~")
    for config_path in [
        os.path.join(home, ".codex", "config.toml"),
        os.path.join(os.environ.get("CODEX_HOME", home), "config.toml"),
    ]:
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, encoding="utf-8-sig") as f:
                content = f.read()
            out = []
            for m in re.finditer(r"\[model_providers\.([\w.\-]+)\]([\s\S]*?)(?=\n\[|\Z)", content):
                name, body = m.group(1), m.group(2)
                base = ""
                bm = re.search(r"base_url\s*=\s*[\"']([^\"']+)[\"']", body)
                if bm:
                    base = bm.group(1)
                key = ""
                km = re.search(r"experimental_bearer_token\s*=\s*[\"']([^\"']+)[\"']", body)
                if km:
                    key = km.group(1)
                if base:
                    out.append({"name": name, "base_url": base, "api_key": key})
            if not out:
                m = re.search(r"^openai_base_url\s*=\s*[\"']([^\"']+)[\"']", content, re.M)
                if m:
                    out.append({"name": "default", "base_url": m.group(1), "api_key": ""})
            if out:
                return out
        except Exception:
            continue
    return []


def read_codex_plus_providers():
    """Read Codex++ relay providers from ~/.codex-session-delete/settings.json."""
    candidates = [
        os.path.join(os.path.expanduser("~"), ".codex-session-delete", "settings.json"),
        os.path.join(os.path.expanduser("~"), ".codex", "settings.json"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            providers = []
            for prof in data.get("relayProfiles", []) or []:
                name = (prof.get("name") or "").strip()
                base = (prof.get("upstreamBaseUrl") or "").strip()
                if not name or not base:
                    continue
                key = ""
                cc = prof.get("configContents") or ""
                m = re.search(r"experimental_bearer_token\s*=\s*[\"']([^\"']+)[\"']", cc)
                if m:
                    key = m.group(1).strip()
                providers.append({"name": name, "base_url": strip_v1(base), "api_key": key})
            if providers:
                return providers
        except Exception:
            continue
    return []


def read_auth_json():
    """Read Codex auth.json (OpenAI login / API key)."""
    home = os.path.expanduser("~")
    for path in [
        os.path.join(home, ".codex", "auth.json"),
        os.path.join(home, ".config", "codex", "auth.json"),
    ]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out = {}
            key = (data.get("OPENAI_API_KEY") or "").strip()
            if key:
                out["api_key"] = key
            tokens = data.get("tokens") or {}
            access = (tokens.get("access_token") or "").strip()
            if access:
                out["access_token"] = access
            if out:
                out["auth_mode"] = data.get("auth_mode", "")
                return out
        except Exception:
            continue
    return None


def env_candidates():
    """Environment variable candidates. Requires both key and base URL."""
    out = []
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        out.append({"name": "env:openai", "source": "env", "base_url": strip_v1(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")), "api_key": openai_key})
    agent_key = os.environ.get("AGENT_API_KEY", "").strip()
    agent_base = os.environ.get("AGENT_BASE_URL", "").strip()
    if agent_key and agent_base:
        out.append({"name": "env:agent", "source": "env", "base_url": strip_v1(agent_base), "api_key": agent_key})
    clip_key = os.environ.get("CLIPROXY_API_KEY", "").strip()
    clip_base = os.environ.get("CLIPROXY_BASE_URL", "").strip()
    if clip_key and clip_base:
        out.append({"name": "env:cliproxy", "source": "env", "base_url": strip_v1(clip_base), "api_key": clip_key})
    return out


def env_keys_without_base():
    """Env vars that have a key but no base URL (these are skipped, tell the user why)."""
    out = []
    for key_env, base_env, label in [
        ("AGENT_API_KEY", "AGENT_BASE_URL", "AGENT"),
        ("CLIPROXY_API_KEY", "CLIPROXY_BASE_URL", "CLIPROXY"),
    ]:
        if os.environ.get(key_env, "").strip() and not os.environ.get(base_env, "").strip():
            out.append(label)
    return out


def discover_candidates():
    """Collect provider candidates from every machine-specific source."""
    cands = []
    seen = set()

    def add(name, source, base, key):
        base = strip_v1(base)
        if not base or not key:
            return
        if is_local_aggregate(base):
            return
        if base in seen:
            return
        seen.add(base)
        cands.append({"name": name, "source": source, "base_url": base, "api_key": key})

    for p in read_codex_plus_providers():
        add(p["name"], "codex++", p["base_url"], p["api_key"])
    for p in read_config_providers():
        add("config:" + p["name"], "config.toml", p["base_url"], p["api_key"])
    auth = read_auth_json()
    if auth:
        key = auth.get("api_key") or auth.get("access_token") or ""
        if key:
            add("openai", "auth.json", "https://api.openai.com", key)
    for e in env_candidates():
        add(e["name"], e["source"], e["base_url"], e["api_key"])
    return cands


# ---------- providers.json ----------

def load_providers(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_providers(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_summary(data):
    print("=== Provider Summary ===")
    for p in data.get("providers", []):
        models = p.get("image_models") or []
        line = "[%s] (%s) base=%s key=%s status=%s" % (p["name"], p.get("source", ""), p.get("base_url", ""), mask_key(p.get("api_key")), p.get("status", ""))
        if models:
            descs = [(m["id"] + "(" + m.get("image_api", "?") + ")") if isinstance(m, dict) else m for m in models]
            line += " models=" + ", ".join(descs)
        print(line)
    print("default_provider:", data.get("default_provider"))
    print("default_model:", data.get("default_model"))
    print("providers.json:", DEFAULT_PROVIDERS_PATH)


# ---------- probing ----------

def fetch_models(endpoint, api_key, timeout=10):
    """Returns (image_models, all_models, http_code). code=0 means no HTTP error (success/network)."""
    req = urllib.request.Request(
        endpoint,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            all_models = [m["id"] for m in data.get("data", [])]
            image_models = [m for m in all_models if any(kw in m.lower() for kw in IMAGE_MODEL_KEYWORDS)]
            return image_models, all_models, 0
    except urllib.error.HTTPError as e:
        return [], None, e.code
    except Exception:
        return [], None, 0


def probe_candidate(cand):
    image_models, all_models, code = fetch_models(cand["base_url"] + "/v1/models", cand["api_key"])
    if code in (401, 403):
        cand["status"] = "auth_failed"
    elif code == 404:
        cand["status"] = "no_models_endpoint"
    elif code:
        cand["status"] = "unreachable"
    elif image_models:
        cand["status"] = "ok"
        with ThreadPoolExecutor(max_workers=4) as ex:
            cand["image_models"] = list(ex.map(lambda m: probe_model_entry(cand, m), image_models[:6]))
    else:
        cand["status"] = "no_image_models"
    return cand


def probe_image_api(base_url, api_key, model):
    """Probe which API style serves this image model (POST with model only; missing prompt always errors, no image is generated).
    Returns (api_style, note). api_style is 'images' or 'chat'; editable in providers.json."""
    endpoint = base_url + "/v1/images/generations"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({"model": model}).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "images", "images endpoint accepted probe (HTTP 200)"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        low = (body + " " + str(e.reason)).lower()
        if any(k in low for k in ["not supported", "unsupported", "does not support", "images/edits", "only supports"]):
            return "chat", "images endpoint rejects this model: " + body[:120]
        if e.code == 404:
            return "chat", "no images endpoint (HTTP 404)"
        if "prompt" in low or "missing" in low or "parameter" in low:
            return "images", "images endpoint exists, missing prompt (HTTP %d)" % e.code
        if e.code in (401, 403):
            return "images", "auth error (HTTP %d), assume images" % e.code
        if e.code == 429:
            return "images", "rate limited (HTTP 429), assume images - edit providers.json if wrong"
        return "images", "images endpoint responded HTTP %d" % e.code
    except Exception:
        return "images", "images endpoint unreachable"


def probe_model_entry(cand, model):
    api, note = probe_image_api(cand["base_url"], cand["api_key"], model)
    if api == "chat":
        note += " | " + probe_chat_endpoint(cand["base_url"], cand["api_key"], model)
        suffix = "/v1/chat/completions"
    else:
        suffix = "/v1/images/generations"
    return {"id": model, "image_api": api, "image_endpoint": cand["base_url"] + suffix, "probe_note": note}


def probe_chat_endpoint(base_url, api_key, model):
    """Verify chat completions endpoint exists (POST with model only; missing messages always errors, nothing is sent)."""
    endpoint = base_url + "/v1/chat/completions"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({"model": model}).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "chat endpoint accepted probe (HTTP 200)"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        if e.code == 404:
            return "chat endpoint missing (HTTP 404) - generation will fail, check base_url"
        if e.code == 429:
            return "chat endpoint rate limited (HTTP 429)"
        if e.code in (401, 403):
            return "chat endpoint auth error (HTTP %d)" % e.code
        return "chat endpoint exists (HTTP %d)" % e.code
    except Exception:
        return "chat endpoint unreachable"


# ---------- init ----------

def run_init(no_ping=False):
    print("[1/4] Checking Codex CLI...")
    import shutil, subprocess
    codex_path = shutil.which("codex")
    if codex_path:
        try:
            r = subprocess.run([codex_path, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                print("  [OK] Codex CLI " + r.stdout.strip().split()[-1])
            else:
                print("  [WARN] Codex CLI --version failed")
        except Exception:
            print("  [WARN] Codex CLI check failed")
    else:
        print("  [WARN] Codex CLI not found (continuing anyway)")

    print("[2/4] Discovering providers (Codex++ / config.toml / auth.json / env)...")
    cands = discover_candidates()
    if not cands:
        print("  [WARN] No providers discovered. Log in with `codex login`, set OPENAI_API_KEY + OPENAI_BASE_URL env vars, or check Codex++ provider config.")
    for label in env_keys_without_base():
        print("  [INFO] Found " + label + "_API_KEY env var but no " + label + "_BASE_URL - skipped. Set both to use this provider.")
    for c in cands:
        c.setdefault("status", "no_key" if not c.get("api_key") else "unknown")
        c["image_models"] = []

    if not no_ping:
        print("[3/4] Probing providers (parallel, 10s timeout each)...")
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(probe_candidate, c): c for c in cands}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    futures[fut]["status"] = "error"
    else:
        print("[3/4] Skipping network probing (--no-ping)")

    old_defaults = {}
    if os.path.exists(DEFAULT_PROVIDERS_PATH):
        try:
            old = load_providers(DEFAULT_PROVIDERS_PATH)
            old_defaults = {"provider": old.get("default_provider"), "model": old.get("default_model")}
        except Exception:
            pass

    ok = [c for c in cands if c.get("status") == "ok"]
    default_provider = ""
    default_model = ""
    if ok:
        if old_defaults.get("provider") in [c["name"] for c in ok]:
            default_provider = old_defaults["provider"]
        else:
            default_provider = ok[0]["name"]
        chosen = next((c for c in ok if c["name"] == default_provider), ok[0])
        ids = model_ids(chosen.get("image_models") or [])
        if old_defaults.get("model") and old_defaults["model"] in ids:
            default_model = old_defaults["model"]
        elif ids:
            default_model = pick_best_model(ids)
    elif cands:
        first = next((c for c in cands if c.get("api_key")), cands[0])
        default_provider = first["name"]

    data = {
        "default_provider": default_provider,
        "default_model": default_model,
        "providers": cands,
    }
    save_providers(DEFAULT_PROVIDERS_PATH, data)
    print("  [OK] providers.json saved: " + DEFAULT_PROVIDERS_PATH)

    print("[4/4] Ensuring view_image is disabled...")
    ensure_view_image_disabled()
    print("  [OK] view_image = false")
    print()
    print_summary(data)
    return True


def ensure_view_image_disabled():
    home = os.path.expanduser("~")
    config_path = os.path.join(home, ".codex", "config.toml")
    if os.environ.get("CODEX_HOME"):
        config_path = os.path.join(os.environ["CODEX_HOME"], "config.toml")
    if not os.path.exists(config_path):
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8-sig") as f:
            f.write("[features]\nview_image = false\n")
        return
    with open(config_path, encoding="utf-8-sig") as f:
        content = f.read()
    if "view_image" not in content:
        if "[features]" in content:
            content = content.replace("[features]", "[features]\nview_image = false")
        else:
            content = "[features]\nview_image = false\n\n" + content
        with open(config_path, "w", encoding="utf-8-sig") as f:
            f.write(content)


# ---------- inspect ----------

def inspect_providers(path):
    if not os.path.exists(path):
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=providers.json not found at " + path + ". Run --init first.", file=sys.stdout)
        sys.exit(1)
    print_summary(load_providers(path))


# ---------- image saving ----------

def save_image_bytes(data_bytes, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data_bytes)
    return out_path


def download_images(urls, default_out):
    saved = []
    for idx, url in enumerate(urls):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                img_data = resp.read()
            ext = infer_extension(resp.headers)
            base, orig_ext = os.path.splitext(default_out)
            target_ext = orig_ext.lstrip(".") or ext
            fname = default_out if (len(urls) == 1 and not os.path.isdir(default_out)) else base + "_" + str(idx + 1) + "." + target_ext
            saved.append(save_image_bytes(img_data, fname))
        except Exception as e:
            print("[Warning] Failed to download image from " + url + ": " + str(e), file=sys.stderr)
    return saved


def extract_strings_from_obj(obj, results=None):
    if results is None:
        results = []
    if isinstance(obj, str):
        if obj.startswith(("http://", "https://")) or obj.startswith("data:image/"):
            results.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            extract_strings_from_obj(v, results)
    elif isinstance(obj, list):
        for item in obj:
            extract_strings_from_obj(item, results)
    return results


def infer_extension(headers):
    ct = headers.get("Content-Type", "")
    for ext, mime in [("png", "png"), ("jpg", "jpeg"), ("webp", "webp"), ("gif", "gif")]:
        if ext in ct:
            return ext
    return "png"


def extract_and_save_images(content, default_out):
    urls = extract_strings_from_obj(content)
    if not urls:
        return []
    b64_urls = [u for u in urls if u.startswith("data:image/")]
    http_urls = [u for u in urls if u.startswith(("http://", "https://"))]
    saved = []
    for b64_url in b64_urls:
        _, data = b64_url.split(",", 1)
        saved.append(save_image_bytes(base64.b64decode(data), default_out))
    if http_urls:
        saved.extend(download_images(http_urls, default_out))
    return saved


def make_request(endpoint, payload, headers, timeout=30):
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_content(res):
    content = ""
    if isinstance(res, dict):
        if "choices" in res and res["choices"]:
            msg = res["choices"][0].get("message", {})
            content = msg.get("content", "")
            if not content and "images" in msg:
                content = msg["images"]
        elif "data" in res and res["data"]:
            item = res["data"][0]
            if "url" in item:
                content = item["url"]
            elif "b64_json" in item:
                content = "data:image/png;base64," + item["b64_json"]
            elif "revision" in item:
                content = item.get("url", "")
        elif "images" in res:
            content = res["images"]
    return content


# ---------- provider selection ----------

def select_provider(sel, provs, default_name):
    if not sel or sel == "auto":
        sel = default_name or ""
    if not sel:
        return provs[0] if provs else None
    sel_l = sel.lower()
    for p in provs:
        if p["name"].lower() == sel_l or p.get("source", "").lower() == sel_l:
            return p
    for p in provs:
        if sel_l in p["name"].lower() or sel_l in p["base_url"].lower():
            return p
    return None


# ---------- CLI ----------

def parse_args():
    parser = argparse.ArgumentParser(description="Universal image generation via providers.json (run --init once per machine)")
    parser.add_argument("prompt", help="Text prompt for image generation", nargs="?", default=None)
    parser.add_argument("--providers", default=None, help="Path to providers.json (default: ~/.codex/auto-imagegen/providers.json)")
    parser.add_argument("--provider", default="auto", help="Provider name/source from providers.json (default: auto = default_provider)")
    parser.add_argument("--model", default=None, help="Model ID override")
    parser.add_argument("--api-key", default=None, help="API key override")
    parser.add_argument("--size", default="1024x1024", help="Image size (default: 1024x1024)")
    parser.add_argument("--image-api", choices=["images", "chat"], default=None, help="API style: 'images' (OpenAI images/generations) or 'chat' (chat completions returning images). Default from providers.json / images.")
    parser.add_argument("--out", "-o", help="Output file path or directory (default: ~/.codex/generated_images/)")
    parser.add_argument("--img-dir", default=None, help="Output directory for images (default: ~/.codex/generated_images/)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the generated image (default: opens in default viewer)")
    parser.add_argument("--timeout", type=int, default=120, help="Request timeout in seconds (default: 120)")
    parser.add_argument("--init", action="store_true", help="Discover this machine and generate providers.json")
    parser.add_argument("--no-ping", action="store_true", help="With --init: discover only, skip network probing")
    parser.add_argument("--inspect", "-I", action="store_true", help="List providers/models from providers.json")
    return parser.parse_args()


def main():
    args = parse_args()
    p_path = args.providers or DEFAULT_PROVIDERS_PATH

    if args.init:
        ok = run_init(no_ping=args.no_ping)
        sys.exit(0 if ok else 1)

    if args.inspect:
        inspect_providers(p_path)
        sys.exit(0)

    if args.prompt is None:
        print("[Error] Missing prompt. Run --init first, then pass a prompt. Use --inspect to list providers.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(p_path):
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=providers.json not found at " + p_path + ". Run --init first.", file=sys.stdout)
        sys.exit(1)

    data = load_providers(p_path)
    provs = data.get("providers", [])
    provider = select_provider(args.provider, provs, data.get("default_provider"))
    if provider is None:
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=No matching provider. Run --inspect to list providers, or --init to regenerate providers.json.", file=sys.stdout)
        sys.exit(1)

    model = args.model or data.get("default_model") or pick_best_model(provider.get("image_models") or [])
    if not model:
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=No image model known for provider '" + provider["name"] + "'. Run online --init or pass --model.", file=sys.stdout)
        sys.exit(1)

    api_key = args.api_key or provider.get("api_key", "")
    if not api_key:
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=Provider '" + provider["name"] + "' has no api_key in providers.json. Run --init again.", file=sys.stdout)
        sys.exit(1)

    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    model_entry = None
    for m in provider.get("image_models") or []:
        if isinstance(m, dict) and m.get("id") == model:
            model_entry = m
            break
    image_api = args.image_api or (model_entry or {}).get("image_api") or provider.get("image_api") or "images"
    if model_entry and model_entry.get("image_endpoint"):
        endpoint = model_entry["image_endpoint"]
        payload = {"model": model, "prompt": args.prompt, "n": 1, "size": args.size} if image_api == "images" else {"model": model, "messages": [{"role": "user", "content": args.prompt}]}
    elif image_api == "chat":
        endpoint = provider["base_url"] + "/v1/chat/completions"
        payload = {"model": model, "messages": [{"role": "user", "content": args.prompt}]}
    else:
        endpoint = provider["base_url"] + "/v1/images/generations"
        payload = {"model": model, "prompt": args.prompt, "n": 1, "size": args.size}

    if args.out:
        if os.path.isdir(args.out) or args.out.endswith(("\\", "/")):
            out_dir = args.out
            filename = "image_" + str(int(time.time())) + ".png"
            target_path = os.path.join(out_dir, filename)
        else:
            target_path = args.out
            exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
            if not target_path.lower().endswith(exts):
                target_path += ".png"
    else:
        out_dir = args.img_dir or default_img_dir()
        os.makedirs(out_dir, exist_ok=True)
        filename = "image_" + str(int(time.time())) + ".png"
        target_path = os.path.join(out_dir, filename)

    print("Provider: " + provider["name"] + " | Model: " + model + " | Endpoint: " + endpoint, file=sys.stderr)
    print("IMG_DIR=" + (args.img_dir or default_img_dir()), file=sys.stdout)
    print("Model: " + model, file=sys.stderr)
    print("STATUS=STARTED", file=sys.stdout)
    try:
        res = make_request(endpoint, payload, headers, timeout=args.timeout)
        content = extract_content(res)
        saved_paths = extract_and_save_images(content, target_path)
        if saved_paths:
            for p in saved_paths:
                print("STATUS=SUCCESS", file=sys.stdout)
                print("MODEL=" + model, file=sys.stdout)
                print("IMG_PATH=" + p, file=sys.stdout)
                if not args.no_open:
                    try:
                        os.startfile(p)
                    except Exception:
                        pass
        else:
            print("STATUS=FAILURE", file=sys.stdout)
            print("REASON=No image data in response", file=sys.stdout)
            print("Raw content: " + str(content)[:500], file=sys.stderr)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print("STATUS=FAILURE", file=sys.stdout)
        reason = "HTTP " + str(e.code) + " " + e.reason
        print("REASON=" + reason, file=sys.stdout)
        print("[Error] " + reason, file=sys.stderr)
        try:
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body)[:500]
            if image_api == "images" and re.search(r"not supported on /v1/images|images/edits", err_msg, re.I):
                print("HINT=This provider needs chat-based image API. Retry with --image-api chat (or set \"image_api\": \"chat\" for this provider in providers.json).", file=sys.stderr)
            print("ERROR_DETAIL=" + err_msg, file=sys.stderr)
        except Exception:
            print("ERROR_DETAIL=" + err_body[:500], file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("STATUS=FAILURE", file=sys.stdout)
        print("REASON=" + str(e)[:500], file=sys.stdout)
        print("[Error] Failed request: " + str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
