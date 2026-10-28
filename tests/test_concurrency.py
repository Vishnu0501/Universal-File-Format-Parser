import pytest
from typing import List, Tuple, Any
from parser.record import Record, RecordType, Severity
from parser.concurrency.pool_executor import parallel_ordered_stream
#python -m pytest tests/ -v --deselect tests/test_concurrency.py::test_hung_worker_times_out


# ── Top-level worker functions (must be module-level to be picklable) ──────────

def _worker_identity(index: int, payload: Any) -> List[Record]:    return [Record(type=RecordType.DATA, format="test", content=payload, metadata={"index": index})]


def _worker_always_fails(index: int, payload: Any) -> List[Record]:
    raise ValueError(f"deliberate failure at unit {index}")


def _worker_slow_first(index: int, payload: Any) -> List[Record]:
    import time
    if index == 0:
        time.sleep(0.3)
    return [Record(type=RecordType.DATA, format="test", content=index, metadata={"index": index})]


def _worker_multi_record(index: int, payload: Any) -> List[Record]:
    return [
        Record(type=RecordType.DATA, format="test", content=f"{index}-a", metadata={"index": index}),
        Record(type=RecordType.DATA, format="test", content=f"{index}-b", metadata={"index": index}),
    ]


def _hung_worker(index: int, payload: Any) -> List[Record]:
    import time
    time.sleep(999)
    return []


# ── Ordering tests ─────────────────────────────────────────────────────────────

def test_output_ordered_despite_slow_first():
    """Unit 0 sleeps longer than others — output must still come out 0,1,2,..."""
    units = [(i, i) for i in range(5)]
    results = list(parallel_ordered_stream(units, _worker_slow_first, max_workers=4))
    indices = [r.metadata["index"] for r in results]
    assert indices == list(range(5))


def test_output_ordered_20_units():
    """20 units processed in parallel must emit in index order."""
    units = [(i, f"payload-{i}") for i in range(20)]
    results = list(parallel_ordered_stream(units, _worker_identity, max_workers=4))
    assert len(results) == 20
    contents = [r.content for r in results]
    assert contents == [f"payload-{i}" for i in range(20)]


def test_multi_record_per_unit_ordered():
    """Workers returning multiple Records — all must be in order."""
    units = [(i, i) for i in range(4)]
    results = list(parallel_ordered_stream(units, _worker_multi_record, max_workers=4))
    assert len(results) == 8
    assert results[0].content == "0-a"
    assert results[1].content == "0-b"
    assert results[2].content == "1-a"


# ── Failure resilience tests ───────────────────────────────────────────────────

def test_failing_worker_emits_error_record():
    """A worker that raises must produce an error Record, not crash the stream."""
    units = [(i, i) for i in range(3)]
    results = list(parallel_ordered_stream(units, _worker_always_fails, max_workers=2))
    assert len(results) == 3
    assert all(r.type == RecordType.ERROR for r in results)


def test_failing_worker_does_not_break_stream():
    """One failing worker must not prevent other units from emitting."""
    def _mixed_worker(index: int, payload: Any) -> List[Record]:
        if index == 2:
            raise RuntimeError("unit 2 broken")
        return [Record(type=RecordType.DATA, format="test", content=index, metadata={"index": index})]

    units = [(i, i) for i in range(5)]
    results = list(parallel_ordered_stream(units, _mixed_worker, max_workers=4))
    assert len(results) == 5
    types = [r.type for r in results]
    assert RecordType.ERROR in types
    data_indices = [r.metadata.get("index") for r in results if r.type == RecordType.DATA]
    assert 2 not in data_indices


def test_empty_units_yields_nothing():
    results = list(parallel_ordered_stream([], _worker_identity))
    assert results == []


def test_single_unit():
    units = [(0, "hello")]
    results = list(parallel_ordered_stream(units, _worker_identity))
    assert len(results) == 1
    assert results[0].content == "hello"


# ── Timeout test ───────────────────────────────────────────────────────────────

def test_hung_worker_times_out():
    """A worker that sleeps past the timeout must produce an error Record."""
    units = [(0, "hang")]
    results = list(parallel_ordered_stream(units, _hung_worker, max_workers=1, timeout=2))
    assert len(results) == 1
    assert results[0].type == RecordType.ERROR
    assert "timed out" in results[0].reason.lower()
