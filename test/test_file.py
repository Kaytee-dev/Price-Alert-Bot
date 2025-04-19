import unittest
from storage import tiers
from config import SUPER_ADMIN_ID

class TestUserLimit(unittest.TestCase):
    def setUp(self):
        self.original_tiers = dict(tiers.USER_TIERS)

    def tearDown(self):
        tiers.USER_TIERS = self.original_tiers

    def test_super_admin_limit(self):
        user_id = SUPER_ADMIN_ID
        self.assertEqual(tiers.get_user_limit(user_id), 1000)

    def test_free_tier_default(self):
        user_id = "1234567890"
        if user_id in tiers.USER_TIERS:
            del tiers.USER_TIERS[user_id]
        self.assertEqual(tiers.get_user_limit(user_id), 3)

    def test_standard_tier(self):
        user_id = "111"
        tiers.USER_TIERS[user_id] = "standard"
        self.assertEqual(tiers.get_user_limit(user_id), 10)

    def test_premium_tier(self):
        user_id = "222"
        tiers.USER_TIERS[user_id] = "premium"
        self.assertEqual(tiers.get_user_limit(user_id), 20)

    def test_invalid_tier_fallback(self):
        user_id = "333"
        tiers.USER_TIERS[user_id] = "unknown"
        self.assertEqual(tiers.get_user_limit(user_id), 3)

if __name__ == '__main__':
    unittest.main()
