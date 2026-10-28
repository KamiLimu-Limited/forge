"""Unit tests for the branded notification email specs."""

import pytest

from forge.models import NotificationType
from forge.services.email_templates import PATHS, SPECS


@pytest.mark.parametrize("notification_type", list(NotificationType))
def test_every_type_has_a_spec_and_path(notification_type):
    assert notification_type in SPECS
    assert notification_type in PATHS
