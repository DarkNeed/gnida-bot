from __future__ import annotations

import random


RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("♠", "♥", "♦", "♣")


def shuffled_deck() -> list[str]:
    deck = [rank + suit for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_rank(card: str) -> str:
    return card[:-1]


def card_value(card: str) -> int:
    rank = card_rank(card)
    if rank == "A":
        return 11
    if rank in {"J", "Q", "K"}:
        return 10
    return int(rank)


def fate_card_value(card: str) -> int:
    rank = card_rank(card)
    if rank == "A":
        return 14
    if rank == "K":
        return 13
    if rank == "Q":
        return 12
    if rank == "J":
        return 11
    return int(rank)


def hand_total(cards: list[str]) -> int:
    total = sum(card_value(card) for card in cards)
    aces = sum(1 for card in cards if card_rank(card) == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_natural_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_total(cards) == 21


def visible_hand(cards: list[str]) -> str:
    if not cards:
        return "—"
    visible = [cards[0], "🂠", *cards[2:]]
    return " + ".join(visible)


def full_hand(cards: list[str]) -> str:
    return " + ".join(cards) if cards else "—"


def compare_stood_hands(
    challenger_hand: list[str], opponent_hand: list[str], deck: list[str]
) -> tuple[int, str]:
    """Return 0 for challenger, 1 for opponent, plus a concise result reason."""
    first_total = hand_total(challenger_hand)
    second_total = hand_total(opponent_hand)
    first_natural = is_natural_blackjack(challenger_hand)
    second_natural = is_natural_blackjack(opponent_hand)
    if first_natural != second_natural:
        return (0 if first_natural else 1), "натуральный блэкджек"
    if first_total != second_total:
        winner = 0 if first_total > second_total else 1
        return winner, f"{first_total} против {second_total}"
    if len(challenger_hand) != len(opponent_hand):
        winner = 0 if len(challenger_hand) < len(opponent_hand) else 1
        return winner, f"равные {first_total}, но меньше карт"
    while len(deck) >= 2:
        first_fate = deck.pop()
        second_fate = deck.pop()
        first_value = fate_card_value(first_fate)
        second_value = fate_card_value(second_fate)
        if first_value != second_value:
            winner = 0 if first_value > second_value else 1
            return winner, f"карты судьбы: {first_fate} против {second_fate}"
    return random.randrange(2), "монетка судьбы"
