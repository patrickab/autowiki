#!/usr/bin/env bash
set -e

echo "Syncing installed Ollama models to DeepTutor..."

if ! command -v docker &>/dev/null; then
    echo "Error: Docker is not running or not installed."
    exit 1
fi

if ! command -v ollama &>/dev/null; then
    echo "Error: Ollama not found."
    exit 1
fi

MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -v 'embed' || true)

if [ -z "$MODELS" ]; then
    echo "No chat models found in Ollama."
    exit 0
fi

# Pass models directly into python script run inside docker
docker exec -i deeptutor python3 -c '
import sys, json, uuid
path = "/app/data/user/settings/model_catalog.json"
try:
    with open(path, "r") as f:
        catalog = json.load(f)
except Exception as e:
    print("Could not read catalog:", e)
    sys.exit(1)

models = sys.stdin.read().strip().split("\n")
models = [m.strip() for m in models if m.strip()]

llm_svc = catalog.get("services", {}).get("llm", {})
if not llm_svc.get("profiles"):
    print("No LLM profiles found in catalog.")
    sys.exit(1)

profile = llm_svc["profiles"][0]
profile["name"] = "Ollama (Local)"

# Ensure we use a custom profile ID so DeepTutor stops overriding it with .env on startup
if "default" in profile["id"]:
    new_id = "llm-profile-custom-" + uuid.uuid4().hex[:8]
    profile["id"] = new_id
    llm_svc["active_profile_id"] = new_id

existing_models = profile.get("models", [])
existing_map = {m.get("model", ""): m for m in existing_models}

new_models = []
# Keep the exact same model ID if it already exists, create new if it does not
for m in models:
    if m in existing_map:
        new_models.append(existing_map[m])
    else:
        new_models.append({
            "id": "llm-model-" + uuid.uuid4().hex[:8],
            "name": m,
            "model": m
        })

profile["models"] = new_models

# Make sure an active model is set, preserving it if it still exists
current_active = llm_svc.get("active_model_id")
active_still_exists = any(m["id"] == current_active for m in new_models)

if not active_still_exists and new_models:
    # Fallback to the first model if the previous active one was deleted
    llm_svc["active_model_id"] = new_models[0]["id"]

with open(path, "w") as f:
    json.dump(catalog, f, indent=2)

print(f"Successfully synced models to DeepTutor.")
' <<< "$MODELS"

echo "Note: You may need to refresh the DeepTutor web page to see the changes."
