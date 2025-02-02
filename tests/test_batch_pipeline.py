import copy
import logging
import time
import traceback

import pytest

from smartpipeline.error.handling import ErrorManager
from smartpipeline.pipeline import Pipeline
from tests.utils import (
    RandomTextSource,
    TextDuplicator,
    TextReverser,
    ErrorStage,
    ExceptionStage,
    BatchTextReverser,
    BatchTextDuplicator,
    BatchExceptionStage,
    BatchErrorStage,
    TimeWaster,
)

__author__ = "Giacomo Berardi <giacbrd.com>"

logger = logging.getLogger(__name__)


def _pipeline(*args, **kwargs):
    return Pipeline(*args, **kwargs).set_error_manager(
        ErrorManager().raise_on_critical_error()
    )


def test_run():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(35))
        .append_stage("reverser", BatchTextReverser())
        .append_stage("duplicator", TextDuplicator())
        .append_stage("batch_duplicator", BatchTextDuplicator())
        .build()
    )
    for item in pipeline.run():
        assert len([x for x in item.payload.keys() if x.startswith("text")]) == 3
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
    assert pipeline.count == 35
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(40))
        .append_stage("reverser", TextReverser())
        .append_stage("duplicator", TextDuplicator())
        .append_stage("batch_duplicator", BatchTextDuplicator(check_batch=True))
        .build()
    )
    for _ in pipeline.run():
        pass
    assert pipeline.count == 40


def test_run_different_sizes():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(2))
        .append_stage("reverser", BatchTextReverser(size=4))
        .append_stage("duplicator", BatchTextDuplicator(size=20))
        .build()
    )
    n = 0
    for n, item in enumerate(pipeline.run()):
        assert len([x for x in item.payload.keys() if x.startswith("text")]) == 2
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
    assert n == 1 == pipeline.count - 1
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(6))
        .append_stage("reverser", BatchTextReverser(size=1))
        .append_stage("duplicator", BatchTextDuplicator(size=20))
        .build()
    )
    for n, item in enumerate(pipeline.run()):
        assert len([x for x in item.payload.keys() if x.startswith("text")]) == 2
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
    assert n == 5 == pipeline.count - 1


def test_errors(caplog):
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(22))
        .append_stage("reverser", BatchTextReverser(size=5))
        .append_stage("error", ErrorStage())
        .build()
    )
    for item in pipeline.run():
        assert item.has_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("error")
        error = next(item.soft_errors())
        assert error.get_exception() is None
        assert str(error) == "test pipeline error"
    assert pipeline.count == 22
    assert all(
        "stage error has generated an error" in record.msg.lower()
        for record in caplog.records
        if record.levelno == logging.ERROR
    )
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(28))
        .append_stage("reverser", BatchTextReverser(size=8))
        .append_stage("error", ErrorStage())
        .append_stage("duplicator", BatchTextDuplicator(size=5))
        .build()
    )
    caplog.clear()
    for item in pipeline.run():
        assert item.has_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
        assert any(k.startswith("text_") for k in item.payload.keys())
        assert item.get_timing("error")
        error = next(item.soft_errors())
        assert error.get_exception() is None
        assert str(error) == "test pipeline error"
    assert pipeline.count == 28
    assert any(caplog.records)
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(10))
        .append_stage("reverser", BatchTextReverser(size=3))
        .append_stage("error1", ExceptionStage())
        .append_stage("error2", ErrorStage())
        .build()
    )
    caplog.clear()
    for item in pipeline.run():
        assert item.has_critical_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("error1") >= 0.0003
        assert not item.get_timing("error2")
        for error in item.critical_errors():
            assert isinstance(error.get_exception(), Exception)
            assert (
                str(error.get_exception()) == "test exception"
                and str(error) != "test pipeline error"
            )
    assert pipeline.count == 10
    assert any(caplog.records)
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(10))
            .append_stage("reverser", BatchTextReverser(size=4))
            .append_stage("error", ExceptionStage())
            .build()
        )
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager().no_skip_on_critical_error())
        .set_source(RandomTextSource(10))
        .append_stage("reverser1", BatchTextReverser(size=1))
        .append_stage("error", ExceptionStage())
        .append_stage("reverser2", BatchTextReverser(size=4))
        .build()
    )
    for item in pipeline.run():
        assert item.get_timing("reverser1")
        assert item.get_timing("error")
        assert item.get_timing("reverser2")
    assert pipeline.count == 10


def test_batch_errors(caplog):
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(22))
        .append_stage("reverser", BatchTextReverser(size=5))
        .append_stage("error", BatchErrorStage(size=3))
        .build()
    )
    for item in pipeline.run():
        assert item.has_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("error")
        error = next(item.soft_errors())
        assert error.get_exception() is None
        assert str(error) == "test pipeline error"
    assert pipeline.count == 22
    assert any(caplog.records)
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(28))
        .append_stage("reverser", BatchTextReverser(size=8))
        .append_stage("error", BatchErrorStage(size=7))
        .append_stage("duplicator", BatchTextDuplicator(size=5))
        .build()
    )
    for item in pipeline.run():
        assert item.has_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
        assert any(k.startswith("text_") for k in item.payload.keys())
        assert item.get_timing("error")
        error = next(item.soft_errors())
        assert error.get_exception() is None
        assert str(error) == "test pipeline error"
    assert pipeline.count == 28
    assert any(caplog.records)
    pipeline = (
        _pipeline()
        .set_error_manager(ErrorManager())
        .set_source(RandomTextSource(10))
        .append_stage("reverser", BatchTextReverser(size=3))
        .append_stage("error1", BatchExceptionStage(size=7))
        .append_stage("error2", BatchErrorStage(size=1))
        .build()
    )
    for item in pipeline.run():
        assert item.has_critical_errors()
        assert item.get_timing("reverser")
        assert item.get_timing("error1") >= 0.0003
        assert not item.get_timing("error2")
        for error in item.critical_errors():
            assert isinstance(error.get_exception(), Exception)
            assert (
                str(error.get_exception()) == "test exception"
                and str(error) != "test pipeline error"
            )
    assert pipeline.count == 10
    assert any(caplog.records)
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(10))
            .append_stage("reverser", BatchTextReverser(size=4))
            .append_stage("error", BatchExceptionStage(size=3))
            .build()
        )
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1


def _check(items, num, pipeline=None):
    diff = frozenset(range(1, num + 1)).difference(
        item.payload["count"] for item in items
    )
    assert not diff, "Not found items: {}".format(", ".join(str(x) for x in diff))
    if pipeline:
        assert len(items) == num == pipeline.count


def test_concurrent_run():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(96))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2)
        .append_stage("reverser1", BatchTextReverser(), concurrency=0)
        .append_stage("reverser2", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 96, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(81))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser2", BatchTextReverser(), concurrency=0)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 81, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(92))
        .append_stage("reverser0", BatchTextReverser(), concurrency=0)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=0)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 92, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(83))
        .append_stage("reverser0", BatchTextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1, parallel=False)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=1, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 83, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(101))
        .append_stage("duplicator0", BatchTextDuplicator(), concurrency=0)
        .append_stage("reverser", BatchTextReverser(), concurrency=0)
        .append_stage("duplicator1", BatchTextDuplicator(), concurrency=0)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 101, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage("reverser", BatchTextReverser(), concurrency=0)
        .append_stage("duplicator0", BatchTextDuplicator(), concurrency=0)
        .append_stage(
            "duplicator1", BatchTextDuplicator(check_batch=True), concurrency=1
        )
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)


def test_queue_sizes():
    pipeline = (
        _pipeline(max_queues_size=1)
        .set_source(RandomTextSource(93))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2)
        .append_stage("reverser1", BatchTextReverser(), concurrency=0)
        .append_stage("reverser2", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 93, pipeline)
    pipeline = (
        _pipeline(max_queues_size=1)
        .set_source(RandomTextSource(79))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser2", BatchTextReverser(), concurrency=0)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 79, pipeline)
    pipeline = (
        _pipeline(max_queues_size=2)
        .set_source(RandomTextSource(131))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2, parallel=True)
        .append_stage("waster1", TimeWaster(0.02), concurrency=2, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=0)
        .append_stage("waster2", TimeWaster(0.03), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 131, pipeline)
    pipeline = (
        _pipeline(max_queues_size=0)
        .set_source(RandomTextSource(4))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2)
        .append_stage("reverser1", BatchTextReverser(), concurrency=0)
        .append_stage("reverser2", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 4, pipeline)
    pipeline = (
        _pipeline(max_queues_size=0)
        .set_source(RandomTextSource(11))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser2", BatchTextReverser(), concurrency=0)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 11, pipeline)


def test_mixed_concurrent_run():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(96))
        .append_stage("reverser0", TextReverser(), concurrency=2)
        .append_stage("reverser1", BatchTextReverser(), concurrency=0)
        .append_stage("reverser2", TextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 96, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(81))
        .append_stage("reverser0", BatchTextReverser(), concurrency=2, parallel=True)
        .append_stage("reverser1", TextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser2", TextReverser(), concurrency=0)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 81, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(92))
        .append_stage("reverser0", BatchTextReverser(), concurrency=0)
        .append_stage("reverser1", TextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=0)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 92, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(83))
        .append_stage("reverser0", BatchTextReverser(), concurrency=1, parallel=True)
        .append_stage("reverser1", BatchTextReverser(), concurrency=1, parallel=False)
        .append_stage("duplicator", TextDuplicator(), concurrency=1, parallel=True)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 83, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage("duplicator0", TextDuplicator(), concurrency=0)
        .append_stage("reverser", TextReverser(), concurrency=0)
        .append_stage(
            "duplicator1", BatchTextDuplicator(check_batch=True), concurrency=0
        )
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage("duplicator0", TextDuplicator(), concurrency=2)
        .append_stage("reverser", TextReverser(), concurrency=2)
        .append_stage("duplicator1", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)


def test_concurrency_errors():
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(29))
            .append_stage("reverser", BatchTextReverser(size=7), concurrency=1)
            .append_stage("error", ExceptionStage(), concurrency=1)
            .build()
        )
        try:
            for _ in pipeline.run():
                pass
        except Exception:
            tb = traceback.format_exc()
            assert 'Exception("test exception")' in tb
            assert "CriticalError" in tb
            raise
        assert pipeline.count == 1
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(10))
            .append_stage(
                "reverser", BatchTextReverser(size=3), concurrency=1, parallel=True
            )
            .append_stage("error", ExceptionStage(), concurrency=1, parallel=True)
            .build()
        )
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(29))
        .append_stage("reverser", BatchTextReverser(size=3), concurrency=3)
        .append_stage("error", ErrorStage(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(size=7), concurrency=2)
        .build()
    )
    for item in pipeline.run():
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
        assert any(k.startswith("text_") for k in item.payload.keys())
        assert item.get_timing("error")
    assert pipeline.count == 29
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(29))
            .append_stage("reverser", BatchTextReverser(size=7), concurrency=1)
            .append_stage("error", BatchExceptionStage(size=3), concurrency=1)
            .build()
        )
        try:
            for _ in pipeline.run():
                pass
        except Exception:
            tb = traceback.format_exc()
            assert 'Exception("test exception")' in tb
            assert "CriticalError" in tb
            raise
        assert pipeline.count == 1
    with pytest.raises(Exception):
        pipeline = (
            _pipeline()
            .set_source(RandomTextSource(10))
            .append_stage(
                "reverser", BatchTextReverser(size=3), concurrency=1, parallel=True
            )
            .append_stage(
                "error", BatchExceptionStage(size=1), concurrency=1, parallel=True
            )
            .build()
        )
        try:
            for _ in pipeline.run():
                pass
        except Exception:
            tb = traceback.format_exc()
            assert 'Exception("test exception")' in tb
            assert "CriticalError" in tb
            raise
        assert pipeline.count == 1
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(29))
        .append_stage("reverser", BatchTextReverser(size=3), concurrency=3)
        .append_stage("error", BatchErrorStage(size=13), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(size=7), concurrency=2)
        .build()
    )
    for item in pipeline.run():
        assert item.get_timing("reverser")
        assert item.get_timing("duplicator")
        assert any(k.startswith("text_") for k in item.payload.keys())
        assert item.get_timing("error")
    assert pipeline.count == 29


def test_concurrent_initialization():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, kwargs={"cycles": 3}, concurrency=2
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[5], concurrency=0
        )
        .append_stage("reverser2", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, concurrency=2, parallel=True
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[10], concurrency=1, parallel=True
        )
        .append_stage_concurrently("reverser2", BatchTextReverser, concurrency=0)
        .append_stage_concurrently(
            "duplicator", BatchTextDuplicator, args=[10], concurrency=2, parallel=True,
        )
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage("reverser0", BatchTextReverser(), concurrency=0)
        .append_stage_concurrently("reverser1", BatchTextReverser, concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(10), concurrency=0)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage_concurrently("duplicator0", BatchTextDuplicator, concurrency=0)
        .append_stage("reverser", BatchTextReverser(), concurrency=0)
        .append_stage_concurrently("duplicator1", BatchTextDuplicator, concurrency=0)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage("reverser", BatchTextReverser(12), concurrency=0)
        .append_stage_concurrently("duplicator0", BatchTextDuplicator, concurrency=0)
        .append_stage("duplicator1", BatchTextDuplicator(), concurrency=1)
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline(max_init_workers=1)
        .set_source(RandomTextSource(100))
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, args=[20], concurrency=1, parallel=True
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[20], concurrency=1, parallel=False
        )
        .append_stage_concurrently(
            "duplicator", BatchTextDuplicator, args=[20], concurrency=1, parallel=True,
        )
        .build()
    )
    items = list(pipeline.run())
    _check(items, 100, pipeline)


def test_huge_run():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(200))
        .append_stage(
            "reverser0", BatchTextReverser(10000), concurrency=2, parallel=True
        )
        .append_stage(
            "reverser1", BatchTextReverser(10000), concurrency=3, parallel=True
        )
        .append_stage(
            "reverser2", BatchTextReverser(10000), concurrency=1, parallel=True
        )
        .append_stage(
            "duplicator", BatchTextDuplicator(10000), concurrency=2, parallel=True
        )
        .build()
    )
    start_time = time.time()
    items = list(pipeline.run())
    elapsed1 = time.time() - start_time
    logger.debug("Time for parallel: {}".format(elapsed1))
    _check(items, 200)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(200))
        .append_stage("reverser0", BatchTextReverser(10000), concurrency=0)
        .append_stage("reverser1", BatchTextReverser(10000), concurrency=0)
        .append_stage("reverser2", BatchTextReverser(10000), concurrency=0)
        .append_stage("duplicator", BatchTextDuplicator(10000), concurrency=0)
        .build()
    )
    start_time = time.time()
    items = list(pipeline.run())
    elapsed2 = time.time() - start_time
    logger.debug("Time for sequential: {}".format(elapsed2))
    _check(items, 200)
    assert elapsed2 > elapsed1


def test_timeouts():
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage(
            "reverser0", BatchTextReverser(timeout=1, size=120), concurrency=0
        )
        .append_stage(
            "reverser1", BatchTextReverser(timeout=1, size=120), concurrency=0
        )
        .append_stage(
            "reverser2", BatchTextReverser(timeout=0, size=120), concurrency=0
        )
        .append_stage(
            "duplicator", BatchTextDuplicator(timeout=1, size=120), concurrency=0
        )
        .build()
    )
    start_time = time.time()
    items = list(pipeline.run())
    elapsed = time.time() - start_time
    assert 3 <= round(elapsed)
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage(
            "reverser0", BatchTextReverser(timeout=1, size=120), concurrency=1
        )
        .append_stage(
            "reverser1", BatchTextReverser(timeout=2, size=120), concurrency=1
        )
        .append_stage(
            "reverser2", BatchTextReverser(timeout=0, size=120), concurrency=1
        )
        .append_stage(
            "duplicator", BatchTextDuplicator(timeout=1, size=120), concurrency=1
        )
        .build()
    )
    start_time = time.time()
    items = list(pipeline.run())
    elapsed = time.time() - start_time
    assert 4 <= round(elapsed)
    _check(items, 100, pipeline)
    pipeline = (
        _pipeline()
        .set_source(RandomTextSource(100))
        .append_stage(
            "reverser0",
            BatchTextReverser(timeout=1, size=120),
            concurrency=1,
            parallel=True,
        )
        .append_stage(
            "reverser1",
            BatchTextReverser(timeout=0, size=120),
            concurrency=1,
            parallel=True,
        )
        .append_stage(
            "reverser2",
            BatchTextReverser(timeout=1, size=120),
            concurrency=1,
            parallel=True,
        )
        .append_stage(
            "duplicator",
            BatchTextDuplicator(timeout=0, size=120),
            concurrency=1,
            parallel=True,
        )
        .build()
    )
    start_time = time.time()
    items = list(pipeline.run())
    elapsed = time.time() - start_time
    assert 2 <= round(elapsed)
    _check(items, 100, pipeline)


def test_single_items(items_generator_fx):
    pipeline = (
        _pipeline()
        .append_stage("reverser0", BatchTextReverser())
        .append_stage("reverser1", BatchTextReverser())
        .append_stage("reverser2", BatchTextReverser())
        .append_stage("duplicator", BatchTextDuplicator())
        .build()
    )
    item = next(items_generator_fx)
    for _ in range(88):
        pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, kwargs={"cycles": 3}, concurrency=2
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[5], concurrency=0
        )
        .append_stage("reverser2", BatchTextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, concurrency=2, parallel=True
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[9], concurrency=1, parallel=True
        )
        .append_stage_concurrently("reverser2", BatchTextReverser, concurrency=0)
        .append_stage_concurrently(
            "duplicator", BatchTextDuplicator, args=[10], concurrency=2, parallel=True,
        )
        .build()
    )
    item = next(items_generator_fx)
    for _ in range(88):
        pipeline.process_async(item)
    for _ in range(88):
        result = pipeline.get_item()
        assert result.id == item.id
        assert result.payload["text"]
        assert result.payload["text"] != item.payload["text"]
    pipeline.stop()

    pipeline = (
        _pipeline()
        .append_stage("reverser0", BatchTextReverser(), concurrency=0)
        .append_stage_concurrently("reverser1", BatchTextReverser, concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(10), concurrency=0)
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] == item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage_concurrently("duplicator0", BatchTextDuplicator)
        .append_stage("reverser", BatchTextReverser())
        .append_stage_concurrently("duplicator1", BatchTextDuplicator)
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage("reverser", BatchTextReverser(11), concurrency=0)
        .append_stage_concurrently("duplicator0", BatchTextDuplicator, concurrency=0)
        .append_stage("duplicator1", BatchTextDuplicator(), concurrency=1)
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline(max_init_workers=1)
        .append_stage_concurrently(
            "reverser0", BatchTextReverser, args=[20], concurrency=1, parallel=True
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[20], concurrency=1, parallel=False
        )
        .append_stage_concurrently(
            "duplicator", BatchTextDuplicator, args=[20], concurrency=1, parallel=True,
        )
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(item)
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] == item.payload["text"]
    assert len(result.payload.keys()) > len(item.payload.keys())


def test_mixed_single_items(items_generator_fx):
    pipeline = (
        _pipeline()
        .append_stage("reverser0", BatchTextReverser())
        .append_stage("reverser1", TextReverser())
        .append_stage("reverser2", BatchTextReverser())
        .append_stage("duplicator", TextDuplicator())
        .build()
    )
    item = next(items_generator_fx)
    for _ in range(88):
        pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage_concurrently(
            "reverser0", TextReverser, kwargs={"cycles": 3}, concurrency=2
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[5], concurrency=0
        )
        .append_stage("reverser2", TextReverser(), concurrency=1)
        .append_stage("duplicator", BatchTextDuplicator(), concurrency=2)
        .build()
    )
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload["text"] != item.payload["text"]

    pipeline = (
        _pipeline()
        .append_stage_concurrently(
            "reverser0", TextReverser, concurrency=2, parallel=True
        )
        .append_stage_concurrently(
            "reverser1", BatchTextReverser, args=[9], concurrency=1, parallel=True
        )
        .append_stage_concurrently("reverser2", TextReverser, concurrency=0)
        .append_stage_concurrently(
            "duplicator", BatchTextDuplicator, args=[10], concurrency=2, parallel=True,
        )
        .build()
    )
    item = next(items_generator_fx)
    for _ in range(88):
        pipeline.process_async(item)
    for _ in range(88):
        result = pipeline.get_item()
        assert result.id == item.id
        assert result.payload["text"]
        assert result.payload["text"] != item.payload["text"]
    pipeline.stop()
