"""Portfolio allocation algorithms: Hierarchical Risk Parity (HRP), Inverse Variance, and Equal Risk Contribution.

Implements Marcos López de Prado's (2016) Hierarchical Risk Parity algorithm:
  1. Tree clustering (hierarchical correlation distance clustering)
  2. Quasi-diagonalization (matrix sorting based on linkage dendrogram)
  3. Recursive bisection (allocating inverse variance weights across clustered tree partitions)
"""



import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage

__all__ = [
    "correlation_distance",
    "inverse_variance_weights",
    "hierarchical_risk_parity",
    "quasi_diagonalize",
]


def correlation_distance(corr: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Calculate distance matrix d_{i,j} = sqrt(0.5 * (1 - rho_{i,j})).

    Args:
        corr: Correlation matrix in [-1, 1] with ones on the diagonal.

    Returns:
        Square symmetric distance matrix with zero diagonal.
    """
    c = np.asarray(corr, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1]:
        raise ValueError("Correlation matrix must be square 2-D")
    # Clip numerical epsilon
    c = np.clip(c, -1.0, 1.0)
    dist = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - c)))
    np.fill_diagonal(dist, 0.0)
    return dist


def quasi_diagonalize(linkage_matrix: np.ndarray) -> list[int]:
    """Quasi-diagonalize the clusters: sort cluster indices by hierarchical tree structure.

    Args:
        linkage_matrix: Linkage matrix produced by scipy.cluster.hierarchy.linkage.

    Returns:
        Ordered list of leaf indices.
    """
    n = int(linkage_matrix[-1, 3])  # Total number of original observations
    sorted_indices = [int(linkage_matrix[-1, 0]), int(linkage_matrix[-1, 1])]

    while True:
        expanded = []
        has_cluster = False
        for idx in sorted_indices:
            if idx >= n:
                has_cluster = True
                cluster_idx = idx - n
                left = int(linkage_matrix[cluster_idx, 0])
                right = int(linkage_matrix[cluster_idx, 1])
                expanded.extend([left, right])
            else:
                expanded.append(idx)
        sorted_indices = expanded
        if not has_cluster:
            break

    return sorted_indices


def inverse_variance_weights(cov: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Calculate inverse-variance weights w_i = (1/sigma_i^2) / sum(1/sigma_k^2).

    Args:
        cov: Covariance matrix.

    Returns:
        Normalized non-negative 1-D weight array summing to 1.0.
    """
    c = np.asarray(cov, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1]:
        raise ValueError("Covariance matrix must be square 2-D")
    variances = np.diag(c)
    if np.any(variances <= 0.0):
        raise ValueError("All asset variances on the diagonal must be strictly positive")
    inv_var = 1.0 / variances
    return inv_var / np.sum(inv_var)


def _cluster_variance(cov: np.ndarray, cluster_indices: list[int]) -> float:
    """Calculate the variance of an inverse-variance weighted sub-cluster."""
    sub_cov = cov[np.ix_(cluster_indices, cluster_indices)]
    w = inverse_variance_weights(sub_cov)
    return float(w @ sub_cov @ w)


def hierarchical_risk_parity(
    cov: pd.DataFrame | np.ndarray,
    corr: pd.DataFrame | np.ndarray | None = None,
    method: str = "single",
) -> pd.Series | np.ndarray:
    """Allocate portfolio weights using Hierarchical Risk Parity (López de Prado 2016).

    Args:
        cov: Asset covariance matrix (N x N).
        corr: Asset correlation matrix (N x N). If None, derived from ``cov``.
        method: Hierarchical clustering linkage method ('single', 'complete', 'average', 'ward').

    Returns:
        Series (if ``cov`` is a DataFrame) or 1-D ndarray of optimal weights summing to 1.0.

    Raises:
        ValueError: If matrix dimensions mismatch or covariance has non-positive variance.
    """
    is_df = isinstance(cov, pd.DataFrame)
    labels = cov.columns.tolist() if is_df else None

    cov_mat = np.asarray(cov, dtype=float)
    if cov_mat.ndim != 2 or cov_mat.shape[0] != cov_mat.shape[1]:
        raise ValueError("Covariance matrix must be square 2-D")
    n = cov_mat.shape[0]
    if n == 0:
        raise ValueError("Covariance matrix cannot be empty")
    if n == 1:
        return pd.Series([1.0], index=labels) if is_df else np.array([1.0])

    diag = np.diag(cov_mat)
    if np.any(diag <= 0.0):
        raise ValueError("Diagonal variances must be strictly positive")

    if corr is None:
        std = np.sqrt(diag)
        corr_mat = cov_mat / np.outer(std, std)
    else:
        corr_mat = np.asarray(corr, dtype=float)

    dist = correlation_distance(corr_mat)
    # Scipy linkage expects condensed distance or observation matrix
    from scipy.spatial.distance import squareform

    condensed_dist = squareform(dist, checks=False)
    link = linkage(condensed_dist, method=method)

    ordered_indices = quasi_diagonalize(link)

    # Recursive bisection
    weights = np.ones(n, dtype=float)
    clusters = [ordered_indices]

    while clusters:
        next_clusters = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split_point = len(cluster) // 2
            left_cluster = cluster[:split_point]
            right_cluster = cluster[split_point:]

            var_left = _cluster_variance(cov_mat, left_cluster)
            var_right = _cluster_variance(cov_mat, right_cluster)

            # Alpha allocation factor
            alpha = 1.0 - var_left / (var_left + var_right) if (var_left + var_right) > 0 else 0.5

            weights[left_cluster] *= alpha
            weights[right_cluster] *= (1.0 - alpha)

            if len(left_cluster) > 1:
                next_clusters.append(left_cluster)
            if len(right_cluster) > 1:
                next_clusters.append(right_cluster)

        clusters = next_clusters

    weights = weights / np.sum(weights)

    if is_df:
        return pd.Series(weights, index=labels, name="weight")
    return weights
