def class_folder(index: int, class_name: str) -> str:
    """버킷 폴더명, 인덱스 순서 정렬, 예 001_PUSHUP"""
    return f"{index:03d}_{class_name}"
