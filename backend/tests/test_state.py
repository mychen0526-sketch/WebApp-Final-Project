import pytest

from app.errors import Conflict
from app.state import TRANSITIONS, Status, require


@pytest.mark.parametrize("action", sorted(TRANSITIONS))
def test_every_action_only_allowed_from_listed_states(action):
    allowed, _ = TRANSITIONS[action]
    for status in Status:
        post = {"status": status.value}
        if status in allowed:
            require(post, action)
        else:
            with pytest.raises(Conflict):
                require(post, action)


def test_only_approved_can_publish():
    assert TRANSITIONS["publish"][0] == {Status.APPROVED}


def test_published_is_terminal():
    for allowed, _ in TRANSITIONS.values():
        assert Status.PUBLISHED not in allowed
