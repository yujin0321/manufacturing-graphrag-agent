"""문서 안 일대일 할당. 유효 매칭 수 최대화 -> 같으면 유효 쌍의 유사도 합 최대화. 클래스는 보지 않는다."""
import numpy as np
from scipy.optimize import linear_sum_assignment

# 부동소수 반올림 때문에 정확히 임계값인 쌍이 탈락하는 일을 막는 허용 오차
EPS = 1e-9


def cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """정규화된 행렬끼리의 내적(= 코사인). float64."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float64)
    return np.asarray(a, dtype=np.float64) @ np.asarray(b, dtype=np.float64).T


def assign(sim: np.ndarray, threshold: float) -> list[tuple[int, int, float]]:
    """유효(코사인 >= 임계값)한 쌍만 (예측 i, 정답 j, 유사도)로 돌려준다."""
    n, m = sim.shape
    if n == 0 or m == 0:
        return []
    valid = sim >= (threshold - EPS)
    big = 10.0 * (max(n, m) + 1)  # 유효 쌍 유사도 합(<= min(n,m))보다 확실히 크다
    # 무효한 쌍은 기여 0. 유효한 쌍은 (큰 상수 + 유사도): 유효 수 최대화 -> 유효 쌍 유사도 합 최대화
    cost = -np.where(valid, big + sim, 0.0)
    rows, cols = linear_sum_assignment(cost)
    return [(int(i), int(j), float(sim[i, j])) for i, j in zip(rows, cols) if valid[i, j]]
