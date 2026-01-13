# blackjack.py
import random
from dataclasses import dataclass
from typing import List, Tuple

Card = Tuple[int, int]  # (rank 1..13, suit 0..3)


def new_shuffled_deck() -> List[Card]:
    deck: List[Card] = []
    for suit in range(4):
        for rank in range(1, 14):
            deck.append((rank, suit))
    random.shuffle(deck)
    return deck


def card_value(rank: int) -> int:
    if rank == 1:
        return 11  # Ace is always 11 in this simplified version
    if rank >= 11:
        return 10  # J, Q, K
    return rank  # 2..10


def hand_total(hand: List[Card]) -> int:
    return sum(card_value(r) for r, _ in hand)


@dataclass
class RoundState:
    deck: List[Card]
    player: List[Card]
    dealer: List[Card]

    def draw(self) -> Card:
        if not self.deck:
            # Extremely unlikely with this simplified game, but safe.
            self.deck = new_shuffled_deck()
        return self.deck.pop()
