import unittest

from app.controllers import ping as ping_controller


class TestPingController(unittest.TestCase):
    def test_ping(self):
        response = ping_controller.ping(None)

        self.assertEqual(response, "pong")


if __name__ == "__main__":
    unittest.main()
