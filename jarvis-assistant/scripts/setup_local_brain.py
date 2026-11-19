import os
import sys
import urllib.request
import zipfile

GGUF_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
RUNNER_URL = "https://github.com/ggerganov/llama.cpp/releases/download/b4540/llama-b4540-bin-win-avx2-x64.zip"


def _download_file(url: str, dest_path: str) -> None:
    if os.path.exists(dest_path):
        return
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    temp_path = dest_path + ".tmp"
    urllib.request.urlretrieve(url, temp_path)
    os.replace(temp_path, dest_path)


def setup() -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(base_dir, "models")
    bin_dir = os.path.join(base_dir, "tools", "bin")
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    runner_exe = os.path.join(bin_dir, "llama-server.exe")
    if not os.path.exists(runner_exe):
        zip_path = os.path.join(bin_dir, "llama_win.zip")
        try:
            _download_file(RUNNER_URL, zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith(("llama-server.exe", ".dll")):
                        zf.extract(member, bin_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass

    model_dest = os.path.join(models_dir, "qwen2.5-1.5b-instruct-q4_k_m.gguf")
    if not os.path.exists(model_dest):
        try:
            _download_file(GGUF_URL, model_dest)
        except Exception:
            pass


if __name__ == "__main__":
    setup()
