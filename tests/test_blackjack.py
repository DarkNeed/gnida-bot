import random
import unittest

from blackjack import (
    compare_stood_hands,
    hand_total,
    is_natural_blackjack,
    shuffled_deck,
    visible_hand,
)


class BlackjackTests(unittest.TestCase):
    def test_deck_contains_52_unique_cards(self):
        random.seed(1)
        deck = shuffled_deck()
        self.assertEqual(len(deck), 52)
        self.assertEqual(len(set(deck)), 52)

    def test_aces_change_from_eleven_to_one(self):
        self.assertEqual(hand_total(["A♠", "9♥"]), 20)
        self.assertEqual(hand_total(["A♠", "9♥", "8♦"]), 18)
        self.assertEqual(hand_total(["A♠", "A♥", "9♦"]), 21)

    def test_only_hole_card_is_hidden(self):
        self.assertEqual(visible_hand(["8♣", "K♥", "3♦"]), "8♣ + 🂠 + 3♦")

    def test_natural_blackjack_beats_three_card_twenty_one(self):
        first = ["A♠", "K♥"]
        second = ["7♣", "7♥", "7♦"]
        winner, reason = compare_stood_hands(first, second, shuffled_deck())
        self.assertTrue(is_natural_blackjack(first))
        self.assertEqual(winner, 0)
        self.assertEqual(reason, "натуральный блэкджек")


if __name__ == "__main__":
    unittest.main()
