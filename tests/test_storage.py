import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hub'))
from storage import load_json, save_json  # noqa: E402


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'scores_X.json')

    def test_missing_file_returns_default(self):
        self.assertEqual(load_json(self.path, []), [])

    def test_save_then_load(self):
        save_json(self.path, [{'score': 1}])
        save_json(self.path, [{'score': 2}])  # rename over existing file
        self.assertEqual(load_json(self.path, []), [{'score': 2}])
        self.assertFalse(os.path.exists(self.path + '.tmp'))

    def test_corrupt_file_is_kept_aside_not_overwritten(self):
        with open(self.path, 'w') as f:
            f.write('[{"score": 5}, {"sco')  # truncated by power loss
        self.assertEqual(load_json(self.path, []), [])
        with open(self.path + '.corrupt') as f:
            self.assertIn('"score": 5', f.read())
        save_json(self.path, [{'score': 9}])
        self.assertTrue(os.path.exists(self.path + '.corrupt'))

    def test_empty_file_counts_as_corrupt(self):
        open(self.path, 'w').close()
        self.assertEqual(load_json(self.path, []), [])
        self.assertTrue(os.path.exists(self.path + '.corrupt'))


if __name__ == '__main__':
    unittest.main()
