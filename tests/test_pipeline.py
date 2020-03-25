import copy
import logging
import time

import pytest

from smartpipeline.error.handling import ErrorManager
from smartpipeline.pipeline import Pipeline
from tests.utils import FakeSource, TextDuplicator, TextReverser, ErrorStage, ExceptionStage, \
    TimeWaster, SerializableStage

__author__ = 'Giacomo Berardi <giacbrd.com>'

logger = logging.getLogger(__name__)


def _pipeline():
    return Pipeline().set_error_manager(ErrorManager().raise_on_critical_error())


def test_run():
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('reverser', TextReverser())
    pipeline.append_stage('duplicator', TextDuplicator())
    for item in pipeline.run():
        assert len([x for x in item.payload.keys() if x.startswith('text')]) == 2
        assert item.get_timing('reverser')
        assert item.get_timing('duplicator')
    assert pipeline.count == 10


def test_error(caplog):
    pipeline = _pipeline()
    pipeline.set_error_manager(ErrorManager())
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('reverser', TextReverser())
    pipeline.append_stage('error', ErrorStage())
    for item in pipeline.run():
        assert item.has_errors()
        assert item.get_timing('reverser')
        assert item.get_timing('error')
        error = next(item.errors())
        assert isinstance(error.get_exception(), Exception)
        assert str(error) == 'test pipeline error'
    assert any(caplog.records)
    assert pipeline.count == 10
    pipeline = _pipeline()
    pipeline.set_error_manager(ErrorManager())
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('reverser', TextReverser())
    pipeline.append_stage('error1', ExceptionStage())
    pipeline.append_stage('error2', ErrorStage())
    for item in pipeline.run():
        assert item.has_critical_errors()
        assert item.get_timing('reverser')
        assert item.get_timing('error1') >= 0.3
        assert not item.get_timing('error2')
        for error in item.critical_errors():
            assert isinstance(error.get_exception(), Exception)
            assert str(error) == 'test pipeline critical error' or str(error) == 'test exception'
    assert any(caplog.records)
    assert pipeline.count == 10
    with pytest.raises(Exception):
        pipeline = _pipeline()
        pipeline.set_source(FakeSource(10))
        pipeline.append_stage('reverser', TextReverser())
        pipeline.append_stage('error2', ExceptionStage())
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1


def _check(items, num, pipeline=None):
    diff = frozenset(range(1, num + 1)).difference(item.payload['count'] for item in items)
    assert not diff, 'Not found items: {}'.format(', '.join(str(x) for x in diff))
    assert len(items) == num
    if pipeline:
        assert num == pipeline.count


def test_concurrent_run():
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser0', TextReverser(), concurrency=2)
    pipeline.append_stage('reverser1', TextReverser(), concurrency=0)
    pipeline.append_stage('reverser2', TextReverser(), concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=2)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser0', TextReverser(), concurrency=2, use_threads=False)
    pipeline.append_stage('reverser1', TextReverser(), concurrency=1, use_threads=False)
    pipeline.append_stage('reverser2', TextReverser(), concurrency=0)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=2, use_threads=False)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser0', TextReverser(), concurrency=0)
    pipeline.append_stage('reverser1', TextReverser(), concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=0)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser0', TextReverser(), concurrency=1, use_threads=False)
    pipeline.append_stage('reverser1', TextReverser(), concurrency=1, use_threads=True)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=1, use_threads=False)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('duplicator0', TextDuplicator(), concurrency=0)
    pipeline.append_stage('reverser', TextReverser(), concurrency=0)
    pipeline.append_stage('duplicator1', TextDuplicator(), concurrency=0)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser', TextReverser(), concurrency=0)
    pipeline.append_stage('duplicator0', TextDuplicator(), concurrency=0)
    pipeline.append_stage('duplicator1', TextDuplicator(), concurrency=1)
    items = list(pipeline.run())
    _check(items, 100, pipeline)


def test_concurrency_errors():
    with pytest.raises(Exception):
        pipeline = _pipeline()
        pipeline.set_source(FakeSource(10))
        pipeline.append_stage('reverser', TextReverser(), concurrency=1)
        pipeline.append_stage('error', ExceptionStage(), concurrency=1)
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1
    with pytest.raises(Exception):
        pipeline = _pipeline()
        pipeline.set_source(FakeSource(10))
        pipeline.append_stage('reverser', TextReverser(), concurrency=1, use_threads=False)
        pipeline.append_stage('error', ExceptionStage(), concurrency=1, use_threads=False)
        for _ in pipeline.run():
            pass
        assert pipeline.count == 1


def test_concurrent_initializations():
    """test `on_fork` method"""
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('reverser1', TextReverser(), concurrency=1, use_threads=False)
    pipeline.append_stage('error', SerializableStage(), concurrency=2, use_threads=False)
    pipeline.append_stage('reverser2', TextReverser(), concurrency=1, use_threads=False)
    for item in pipeline.run():
        assert item.payload.get('file')
    assert pipeline.count == 10


def test_concurrent_initialization():
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage_concurrently('reverser0', TextReverser, kwargs={'cycles': 3}, concurrency=2)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[5], concurrency=0)
    pipeline.append_stage('reverser2', TextReverser(), concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=2)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage_concurrently('reverser0', TextReverser, concurrency=2, use_threads=False)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[10], concurrency=1, use_threads=False)
    pipeline.append_stage_concurrently('reverser2', TextReverser, concurrency=0)
    pipeline.append_stage_concurrently('duplicator', TextDuplicator, args=[10], concurrency=2, use_threads=False)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser0', TextReverser(), concurrency=0)
    pipeline.append_stage_concurrently('reverser1', TextReverser, concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(10), concurrency=0)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage_concurrently('duplicator0', TextDuplicator, concurrency=0)
    pipeline.append_stage('reverser', TextReverser(), concurrency=0)
    pipeline.append_stage_concurrently('duplicator1', TextDuplicator, concurrency=0)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage('reverser', TextReverser(12), concurrency=0)
    pipeline.append_stage_concurrently('duplicator0', TextDuplicator, concurrency=0)
    pipeline.append_stage('duplicator1', TextDuplicator(), concurrency=1)
    items = list(pipeline.run())
    _check(items, 100, pipeline)
    pipeline = _pipeline().set_max_init_workers(1)
    pipeline.set_source(FakeSource(100))
    pipeline.append_stage_concurrently('reverser0', TextReverser, args=[20], concurrency=1, use_threads=False)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[20], concurrency=1, use_threads=True)
    pipeline.append_stage_concurrently('duplicator', TextDuplicator, args=[20], concurrency=1, use_threads=False)
    items = list(pipeline.run())
    _check(items, 100, pipeline)


# one core machines can have problems with this test
def test_huge_run():
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(200))
    pipeline.append_stage('reverser0', TextReverser(15000), concurrency=4, use_threads=False)
    pipeline.append_stage('reverser1', TextReverser(15000), concurrency=4, use_threads=False)
    pipeline.append_stage('reverser2', TextReverser(15000), concurrency=4, use_threads=False)
    pipeline.append_stage('duplicator', TextDuplicator(15000), concurrency=4, use_threads=False)
    runner = pipeline.run()
    start_time = time.time()
    items = list(runner)
    elapsed1 = time.time() - start_time
    logger.debug('Time for strongly parallel: {}'.format(elapsed1))
    _check(items, 200)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(200))
    pipeline.append_stage('reverser0', TextReverser(15000), concurrency=2, use_threads=False)
    pipeline.append_stage('reverser1', TextReverser(15000), concurrency=2, use_threads=False)
    pipeline.append_stage('reverser2', TextReverser(15000), concurrency=2, use_threads=False)
    pipeline.append_stage('duplicator', TextDuplicator(15000), concurrency=2, use_threads=False)
    runner = pipeline.run()
    start_time = time.time()
    items = list(runner)
    elapsed2 = time.time() - start_time
    logger.debug('Time for mildly parallel: {}'.format(elapsed2))
    _check(items, 200)
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(200))
    pipeline.append_stage('reverser0', TextReverser(15000), concurrency=0)
    pipeline.append_stage('reverser1', TextReverser(15000), concurrency=0)
    pipeline.append_stage('reverser2', TextReverser(15000), concurrency=0)
    pipeline.append_stage('duplicator', TextDuplicator(15000), concurrency=0)
    runner = pipeline.run()
    start_time = time.time()
    items = list(runner)
    elapsed3 = time.time() - start_time
    logger.debug('Time for sequential: {}'.format(elapsed3))
    _check(items, 200)
    assert elapsed3 > elapsed2
    assert elapsed2 > elapsed1


def test_run_times():
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('waster0', TimeWaster(0.2), concurrency=1)
    pipeline.append_stage('waster1', TimeWaster(0.2), concurrency=1)
    pipeline.append_stage('waster2', TimeWaster(0.2), concurrency=1)
    pipeline.append_stage('waster3', TimeWaster(0.2), concurrency=1)
    start_time = time.time()
    items = list(pipeline.run())
    _check(items, 10)
    elapsed0 = time.time() - start_time
    logger.debug('Time for multi-threading: {}'.format(elapsed0))
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('waster0', TimeWaster(0.2), concurrency=1, use_threads=False)
    pipeline.append_stage('waster1', TimeWaster(0.2), concurrency=1, use_threads=False)
    pipeline.append_stage('waster2', TimeWaster(0.2), concurrency=1, use_threads=False)
    pipeline.append_stage('waster3', TimeWaster(0.2), concurrency=1, use_threads=False)
    start_time = time.time()
    items = list(pipeline.run())
    _check(items, 10)
    elapsed1 = time.time() - start_time
    logger.debug('Time for multi-process: {}'.format(elapsed1))
    pipeline = _pipeline()
    pipeline.set_source(FakeSource(10))
    pipeline.append_stage('waster0', TimeWaster(0.2), concurrency=0)
    pipeline.append_stage('waster1', TimeWaster(0.2), concurrency=0)
    pipeline.append_stage('waster2', TimeWaster(0.2), concurrency=0)
    pipeline.append_stage('waster3', TimeWaster(0.2), concurrency=0)
    start_time = time.time()
    items = list(pipeline.run())
    _check(items, 10)
    elapsed2 = time.time() - start_time
    logger.debug('Time for sequential: {}'.format(elapsed2))
    assert elapsed2 > elapsed0
    assert elapsed2 > elapsed1


def test_single_items(items_generator_fx):
    pipeline = _pipeline()
    pipeline.append_stage('reverser0', TextReverser())
    pipeline.append_stage('reverser1', TextReverser())
    pipeline.append_stage('reverser2', TextReverser())
    pipeline.append_stage('duplicator', TextDuplicator())
    item = next(items_generator_fx)
    result = pipeline.process(copy.deepcopy(item))
    assert result.id == item.id
    assert result.payload['text'] != item.payload['text']

    pipeline = _pipeline()
    pipeline.append_stage_concurrently('reverser0', TextReverser, kwargs={'cycles': 3}, concurrency=2)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[5], concurrency=0)
    pipeline.append_stage('reverser2', TextReverser(), concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(), concurrency=2)
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] != item.payload['text']

    pipeline = _pipeline()
    pipeline.append_stage_concurrently('reverser0', TextReverser, concurrency=2, use_threads=False)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[9], concurrency=1, use_threads=False)
    pipeline.append_stage_concurrently('reverser2', TextReverser, concurrency=0)
    pipeline.append_stage_concurrently('duplicator', TextDuplicator, args=[10], concurrency=2, use_threads=False)
    item = next(items_generator_fx)
    pipeline.process_async(item)
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] != item.payload['text']

    pipeline = _pipeline()
    pipeline.append_stage('reverser0', TextReverser(), concurrency=0)
    pipeline.append_stage_concurrently('reverser1', TextReverser, concurrency=1)
    pipeline.append_stage('duplicator', TextDuplicator(10), concurrency=0)
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] == item.payload['text']

    pipeline = _pipeline()
    pipeline.append_stage_concurrently('duplicator0', TextDuplicator)
    pipeline.append_stage('reverser', TextReverser())
    pipeline.append_stage_concurrently('duplicator1', TextDuplicator)
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] != item.payload['text']

    pipeline = _pipeline()
    pipeline.append_stage('reverser', TextReverser(11), concurrency=0)
    pipeline.append_stage_concurrently('duplicator0', TextDuplicator, concurrency=0)
    pipeline.append_stage('duplicator1', TextDuplicator(), concurrency=1)
    item = next(items_generator_fx)
    pipeline.process_async(copy.deepcopy(item))
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] != item.payload['text']

    pipeline = _pipeline().set_max_init_workers(1)
    pipeline.append_stage_concurrently('reverser0', TextReverser, args=[20], concurrency=1, use_threads=False)
    pipeline.append_stage_concurrently('reverser1', TextReverser, args=[20], concurrency=1, use_threads=True)
    pipeline.append_stage_concurrently('duplicator', TextDuplicator, args=[20], concurrency=1, use_threads=False)
    item = next(items_generator_fx)
    pipeline.process_async(item)
    result = pipeline.get_item()
    pipeline.stop()
    assert result.id == item.id
    assert result.payload['text'] == item.payload['text']
    assert len(result.payload.keys()) > len(item.payload.keys())
