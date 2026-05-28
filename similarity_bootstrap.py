#!/usr/bin/env python3
"""Lazy CNN / similarity module loading for fast startup."""

_CNNImageSimilaritySorter = None
_CNNSimilarityUIHelper = None


def _import_cnn_modules():
    """Lazy import CNN similarity sorter modules"""
    global _CNNImageSimilaritySorter, _CNNSimilarityUIHelper
    if _CNNImageSimilaritySorter is None:
        from cnn_image_similarity_sorter import CNNImageSimilaritySorter, CNNSimilarityUIHelper
        _CNNImageSimilaritySorter = CNNImageSimilaritySorter
        _CNNSimilarityUIHelper = CNNSimilarityUIHelper
    return _CNNImageSimilaritySorter, _CNNSimilarityUIHelper
