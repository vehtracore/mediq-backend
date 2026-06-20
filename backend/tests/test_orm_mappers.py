import unittest

from sqlalchemy.orm import configure_mappers

import app.models.appointment  # noqa: F401
import app.models.consultation_payout  # noqa: F401
import app.models.doctor  # noqa: F401
import app.models.review  # noqa: F401
import app.models.user  # noqa: F401


class OrmMapperTests(unittest.TestCase):
    def test_all_relationships_configure_without_ambiguous_foreign_keys(self):
        configure_mappers()


if __name__ == "__main__":
    unittest.main()
