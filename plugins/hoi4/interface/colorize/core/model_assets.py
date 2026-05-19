from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from typing import Callable

MIN_MODEL_FILE_SIZE = 1000

ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ModelAssetStatus:
    model_dir: str
    missing_files: list[str]
    updated_files: list[str]


def inspect_model_assets(model, models_dir: str) -> ModelAssetStatus:
    model_dir = model_asset_dir(model, models_dir)
    os.makedirs(model_dir, exist_ok=True)

    files = model.get_file_entries()
    missing_files = []
    updated_files = []

    for file_id, entry in files.items():
        path = os.path.join(model_dir, entry["path"])
        min_size = int(entry.get("min_size", MIN_MODEL_FILE_SIZE))
        if not os.path.exists(path) or os.path.getsize(path) < min_size:
            missing_files.append(file_id)

    for file_id, entry in files.items():
        if file_id not in missing_files and has_remote_update(model_dir, entry):
            updated_files.append(file_id)

    return ModelAssetStatus(model_dir, missing_files, updated_files)


def model_asset_dir(model, models_dir: str) -> str:
    return os.path.join(models_dir, model.get_asset_dir_name())


def has_remote_update(model_dir: str, entry: dict) -> bool:
    url = entry.get("url")
    if not url:
        return False

    path = os.path.join(model_dir, entry["path"])
    if not os.path.exists(path):
        return False

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=3.0) as response:
            server_size = int(response.info().get("Content-Length", 0))
            local_size = os.path.getsize(path)
            return server_size > 0 and local_size != server_size
    except Exception:
        return False


def download_model_assets(model, models_dir: str, filenames: list[str], progress: ProgressCallback | None = None) -> None:
    model_dir = model_asset_dir(model, models_dir)
    os.makedirs(model_dir, exist_ok=True)
    files = model.get_file_entries()

    for file_id in filenames:
        entry = files[file_id]
        path = os.path.join(model_dir, entry["path"])
        urls_to_try = entry.get("mirrors") or [entry["url"]]
        last_err = None

        if progress:
            progress(entry["path"], 0, 0)

        for url in urls_to_try:
            try:
                _download_file(url, path, entry["path"], progress)
                last_err = None
                break
            except Exception as e:
                last_err = e
                _remove_paths([path])

        if last_err is not None:
            raise last_err


def remove_model_asset_ids(model, models_dir: str, file_ids: list[str]) -> None:
    model_dir = model_asset_dir(model, models_dir)
    files = model.get_file_entries()
    paths = [os.path.join(model_dir, files[file_id]["path"]) for file_id in file_ids if file_id in files]
    _remove_paths(paths)


def _remove_paths(paths: list[str]) -> None:
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _download_file(url: str, path: str, filename: str, progress: ProgressCallback | None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(path, "wb") as out_file:
        total_size = int(response.info().get("Content-Length", 0))
        block_size = 8192
        downloaded = 0

        while True:
            block = response.read(block_size)
            if not block:
                break
            out_file.write(block)
            downloaded += len(block)
            if progress:
                progress(filename, downloaded, total_size)
