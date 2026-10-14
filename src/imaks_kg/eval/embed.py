"""임베더. encode(texts) -> 정규화된 float 행렬 (행 = 문장). 모델은 처음 쓸 때 불러온다."""
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


class Embedder(Protocol):
    model_name: str
    revision: str

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...

    def loaded_revision(self) -> str | None: ...


class SbertEmbedder:
    """sentence-transformers 지연 로딩. CPU 고정."""

    def __init__(self, model_name: str = MODEL_NAME, revision: str = DEFAULT_REVISION):
        self.model_name = model_name
        self.revision = revision
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, revision=self.revision, device="cpu")
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        model = self._load()
        if len(texts) == 0:
            return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float64)
        emb = model.encode(list(texts), batch_size=32, convert_to_numpy=True,
                           normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(emb, dtype=np.float64)

    def loaded_revision(self) -> str | None:
        """로컬 Hub 캐시에서 (모델, 요청 revision)이 가리키는 스냅샷 폴더 이름(= 커밋 해시).

        로드된 가중치 객체에서 직접 읽는 값이 아니라, 같은 캐시를 조회한 간접 확인이다.
        확인할 수 없으면 None(미확인).
        """
        if self._model is None:
            return None
        try:
            from huggingface_hub import snapshot_download
            return Path(snapshot_download(self.model_name, revision=self.revision, local_files_only=True)).name
        except Exception:
            return None
