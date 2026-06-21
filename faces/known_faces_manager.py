#!/usr/bin/env python3
"""
Known Faces Manager
Load/save known faces (names + face samples with embeddings) from ~/.prowser/data/known_faces.json.
Enforces unique names and max 4 samples per subject. Thread-safe for file I/O.
Face samples are persisted by embedding; path is optional metadata. Samples remain valid even if
the original source image is deleted.
"""

import json
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Mapping

MAX_SAMPLES_PER_SUBJECT = 4
_MAX_SAMPLES_PER_SUBJECT = MAX_SAMPLES_PER_SUBJECT


def _get_known_faces_path() -> Path:
    from config import get_config
    return get_config().data_dir / "known_faces.json"


_lock = threading.Lock()


def load() -> List[Dict[str, Any]]:
    """Load known faces from disk. Returns list of subjects; each has id, name, samples (path + embedding)."""
    path = _get_known_faces_path()
    with _lock:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        subjects = data.get("subjects", [])
        if not isinstance(subjects, list):
            return []
        # Ensure each subject has id, name, samples
        out = []
        for s in subjects:
            if not isinstance(s, dict):
                continue
            sid = s.get("id") or str(uuid.uuid4())
            name = s.get("name") or ""
            samples = s.get("samples")
            if not isinstance(samples, list):
                samples = []
            # Embedding is required; path is optional (samples persist when source image is deleted)
            samples = [x for x in samples if isinstance(x, dict) and "embedding" in x][:_MAX_SAMPLES_PER_SUBJECT]
            for x in samples:
                if "path" not in x:
                    x["path"] = ""
            out.append({"id": sid, "name": name.strip(), "samples": samples})
        return out


def save(subjects: List[Dict[str, Any]]) -> None:
    """Save known faces to disk. Caller must pass full list (e.g. from load(), then modified)."""
    path = _get_known_faces_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"subjects": subjects}, f, indent=2)


def name_exists(name: str, exclude_id: Optional[str] = None) -> bool:
    """Return True if a subject with this name already exists (case-insensitive). Optionally exclude one id (for rename)."""
    name_clean = (name or "").strip().lower()
    if not name_clean:
        return False
    for s in load():
        if exclude_id and s.get("id") == exclude_id:
            continue
        if (s.get("name") or "").strip().lower() == name_clean:
            return True
    return False


def add_subject(name: str) -> Optional[str]:
    """Add a new subject with the given name. Returns id if name is unique and non-empty, else None."""
    name_clean = (name or "").strip()
    if not name_clean or name_exists(name_clean):
        return None
    subjects = load()
    sid = str(uuid.uuid4())
    subjects.append({"id": sid, "name": name_clean, "samples": []})
    save(subjects)
    return sid


def remove_subject(subject_id: str) -> bool:
    """Remove subject by id. Returns True if found and removed."""
    subjects = load()
    new_list = [s for s in subjects if s.get("id") != subject_id]
    if len(new_list) == len(subjects):
        return False
    save(new_list)
    return True


def update_name(subject_id: str, new_name: str) -> bool:
    """Update subject name. Returns False if duplicate name or not found."""
    name_clean = (new_name or "").strip()
    if not name_clean or name_exists(name_clean, exclude_id=subject_id):
        return False
    subjects = load()
    for s in subjects:
        if s.get("id") == subject_id:
            s["name"] = name_clean
            save(subjects)
            return True
    return False


def add_sample(subject_id: str, image_path: str, embedding: List[float]) -> bool:
    """Add a sample (path + embedding) to subject. Returns False if subject not found or already at sample cap."""
    if not image_path or not embedding or len(embedding) != 128:
        return False
    subjects = load()
    for s in subjects:
        if s.get("id") != subject_id:
            continue
        samples = s.get("samples") or []
        if len(samples) >= _MAX_SAMPLES_PER_SUBJECT:
            return False
        samples.append({"path": image_path, "embedding": list(embedding)})
        s["samples"] = samples
        save(subjects)
        return True
    return False


def remove_sample(subject_id: str, sample_index: int) -> bool:
    """Remove sample at index from subject. Returns True if found and removed."""
    subjects = load()
    for s in subjects:
        if s.get("id") != subject_id:
            continue
        samples = s.get("samples") or []
        if sample_index < 0 or sample_index >= len(samples):
            return False
        samples.pop(sample_index)
        s["samples"] = samples
        save(subjects)
        return True
    return False


def get_subject(subject_id: str) -> Optional[Dict[str, Any]]:
    """Return subject dict by id, or None."""
    for s in load():
        if s.get("id") == subject_id:
            return s
    return None


def list_subjects() -> List[Dict[str, Any]]:
    """Return all subjects (id, name, samples)."""
    return load()


def update_sample_paths_for_rename(rename_map: Mapping[str, str]) -> int:
    """
    Update sample path strings when image files were renamed (e.g. mass rename).
    Keys/values are matched after normalizing with face_cache path rules.
    Returns the number of sample paths updated.
    """
    from faces.face_cache import normalize_path_for_face_cache

    norm_map: Dict[str, str] = {}
    for old_p, new_p in rename_map.items():
        if not old_p or not new_p or old_p == new_p:
            continue
        try:
            ko = normalize_path_for_face_cache(old_p)
            kn = normalize_path_for_face_cache(new_p)
        except Exception:
            continue
        norm_map[ko] = kn
    if not norm_map:
        return 0
    subjects = load()
    updated = 0
    for s in subjects:
        samples = s.get("samples")
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            p = sample.get("path") or ""
            if not p:
                continue
            try:
                nk = normalize_path_for_face_cache(p)
            except Exception:
                continue
            if nk in norm_map:
                sample["path"] = norm_map[nk]
                updated += 1
    if updated:
        save(subjects)
    return updated
