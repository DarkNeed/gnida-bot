import unittest

from parsing import command_payload, format_duration, parse_duration, parse_duration_prefix


class DurationTests(unittest.TestCase):
    def test_english_hour(self):
        self.assertEqual(parse_duration("1h").seconds, 3600)

    def test_russian_compact_duration(self):
        self.assertEqual(parse_duration("2дня").seconds, 172800)

    def test_russian_hour(self):
        self.assertEqual(parse_duration("1час").seconds, 3600)

    def test_spaced_russian_minute_prefix(self):
        duration, reason = parse_duration_prefix("1 минута слишком много сообщений")
        self.assertEqual(duration.seconds, 60)
        self.assertEqual(reason, "слишком много сообщений")

    def test_spaced_short_minute_prefix(self):
        duration, reason = parse_duration_prefix("1 мин причина")
        self.assertEqual(duration.seconds, 60)
        self.assertEqual(reason, "причина")

    def test_invalid_or_excessive_duration(self):
        self.assertIsNone(parse_duration("навсегда"))
        self.assertIsNone(parse_duration("10s"))
        self.assertIsNone(parse_duration("367дней"))

    def test_format(self):
        self.assertEqual(format_duration(7200), "2 ч.")

    def test_payload_with_bot_suffix(self):
        self.assertEqual(command_payload("/мут@GnidaBot @user 1h причина"), "@user 1h причина")


if __name__ == "__main__":
    unittest.main()
