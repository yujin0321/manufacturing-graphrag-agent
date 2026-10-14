"""평가기에 주는 가짜 임베더: 같은 문장이면 같은 단위 벡터, 다른 문장이면 서로 직교(코사인 0)."""
import numpy as np


class FakeEmbedder:
    model_name = "fake-model"
    revision = "fake-rev"

    def __init__(self, dim=512):
        self.dim = dim
        self.index = {}

    def encode(self, texts):
        out = np.zeros((len(texts), self.dim))
        for i, t in enumerate(texts):
            k = self.index.setdefault(t, len(self.index))
            out[i, k % self.dim] = 1.0
        return out

    def loaded_revision(self):
        return None
