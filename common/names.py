def batch_package_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.strip())
    cleaned = cleaned.strip("_") or "batch"
    if cleaned[0].isdigit():
        cleaned = "i_" + cleaned
    if not cleaned.startswith("i_"):
        cleaned = "i_" + cleaned
    return cleaned
