"""PersistBench V4 Ablation and Observability infrastructure.

Provides:
  - MetricWeightAblation: sweep composite score weights (alpha, beta, gamma)
  - DefenseThresholdSweep: sweep defense hyperparameter thresholds
  - AnomalyDetector: flag statistically anomalous metric values
  - PersistenceHeatmap: session × fragment persistence matrices

Design ref: DESIGN_DOC.md §38 (Ablation), §39 (Observability)
"""
from persistbench.ablation.weight_ablation import MetricWeightAblation
from persistbench.ablation.threshold_sweep import DefenseThresholdSweep
from persistbench.ablation.anomaly import AnomalyDetector

__all__ = ["MetricWeightAblation", "DefenseThresholdSweep", "AnomalyDetector"]
