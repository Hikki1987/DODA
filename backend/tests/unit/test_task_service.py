import pytest

from doda.application.task_service import ALLOWED_TASK_TRANSITIONS, InvalidTaskTransition
from doda.domain.task.models import TaskStatus


def _transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in ALLOWED_TASK_TRANSITIONS.get(current, frozenset()):
        raise InvalidTaskTransition(current, target)
    return target


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
        (TaskStatus.TODO, TaskStatus.CANCELLED),
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
        (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED),
    ],
)
def test_allowed_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    assert _transition(current, target) is target


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.TODO, TaskStatus.DONE),  # skips IN_PROGRESS
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),  # terminal, no reopening
        (TaskStatus.CANCELLED, TaskStatus.TODO),
        (TaskStatus.IN_PROGRESS, TaskStatus.TODO),  # no backtracking by design
    ],
)
def test_disallowed_task_transitions_raise(current: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransition):
        _transition(current, target)


def test_every_task_status_is_covered() -> None:
    assert set(TaskStatus) == set(ALLOWED_TASK_TRANSITIONS)
