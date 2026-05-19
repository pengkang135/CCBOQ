"""
BGE 嵌入模型封装
使用 BAAI/bge-large-zh-v1.5 生成语义向量
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np


_MODEL: Optional[object] = None
_LOCK = threading.Lock()
_DIM = 512


def _get_model():
    global _MODEL
    if _MODEL is None:
        with _LOCK:
            if _MODEL is None:
                from sentence_transformers import SentenceTransformer
                _MODEL = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    return _MODEL


def encode(text: str) -> list[float]:
    """将文本转换为语义向量（512 维，L2 归一化）"""
    model = _get_model()
    embeddings = model.encode(
        [text],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings[0].tolist()


def encode_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """批量编码"""
    model = _get_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=batch_size,
    )
    return embeddings.tolist()


def dim() -> int:
    return _DIM


def preload() -> bool:
    """启动时预加载模型，避免首次写入因模型加载超时。"""
    _get_model()
    return True


def is_loaded() -> bool:
    return _MODEL is not None
