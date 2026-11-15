"""Metrics operate on a single, explicitly labeled candidate pool."""
import math


def ranking_metrics(ordered_ids, labels, k=3):
    if k < 1:
        raise ValueError('k must be positive')
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError('Candidate IDs must be unique')
    if any(identifier not in labels for identifier in ordered_ids):
        raise ValueError('Every candidate needs a relevance label')
    if any(type(value) is not int or not 0 <= value <= 3 for value in labels.values()):
        raise ValueError('Relevance labels must be integers from zero to three')
    size = min(k, len(ordered_ids))
    if not size:
        return {'k': 0, 'precision': None, 'ndcg': None}
    grades = [labels[identifier] for identifier in ordered_ids[:size]]
    ideal = sorted((labels[identifier] for identifier in ordered_ids), reverse=True)[:size]
    def dcg(values):
        return sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(values))
    maximum = dcg(ideal)
    return {'k': size, 'precision': sum(grade > 0 for grade in grades) / size,
            'ndcg': dcg(grades) / maximum if maximum else None}
