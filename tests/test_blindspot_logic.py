from fuzzy_engine import evaluate_urgency, StatusStabilizer
from tracker import SimpleTracker


def test_distance_far_is_aman():
    score, label = evaluate_urgency(12.0, 1.0)
    assert label == "aman"
    assert score < 33


def test_distance_near_is_bahaya():
    score, label = evaluate_urgency(1.5, 1.0)
    assert label == "bahaya"
    assert score >= 66


def test_status_stabilizer_requires_multiple_confirmations():
    stabilizer = StatusStabilizer()
    assert stabilizer.update("bahaya") == "aman"
    assert stabilizer.update("bahaya") == "bahaya"
    assert stabilizer.update("aman") == "bahaya"
    assert stabilizer.update("aman") == "bahaya"
    assert stabilizer.update("aman") == "aman"


def test_tracker_keeps_same_person_id_across_close_boxes():
    tracker = SimpleTracker()
    first = tracker.update([
        {"x1": 10, "y1": 20, "x2": 30, "y2": 100},
        {"x1": 40, "y1": 25, "x2": 60, "y2": 120},
    ])
    second = tracker.update([
        {"x1": 12, "y1": 22, "x2": 32, "y2": 105},
    ])

    assert first[0]["id"] == 0
    assert len(first) == 2
    assert second[0]["id"] == 0
    assert second[0]["y2"] == 105
