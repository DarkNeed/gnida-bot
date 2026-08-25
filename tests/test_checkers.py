import unittest

from checkers import (
    EMPTY,
    WHITE,
    apply_move,
    capture_moves_for_piece,
    index_of,
    initial_board,
    legal_moves,
    simple_moves_for_piece,
)


class CheckersTests(unittest.TestCase):
    def empty_board(self) -> list[str]:
        return [EMPTY] * 64

    def test_initial_board_has_twelve_pieces_per_player(self):
        board = initial_board()
        self.assertEqual(board.count("b"), 12)
        self.assertEqual(board.count("w"), 12)
        self.assertEqual(len(board), 64)

    def test_capture_is_mandatory(self):
        board = self.empty_board()
        capturing = index_of(5, 0)
        board[capturing] = "w"
        board[index_of(4, 1)] = "b"
        board[index_of(5, 4)] = "w"

        moves = legal_moves(board, WHITE)

        self.assertEqual(set(moves), {capturing})
        self.assertEqual(moves[capturing][0].destination, index_of(3, 2))

    def test_regular_piece_can_capture_backwards(self):
        board = self.empty_board()
        source = index_of(3, 2)
        board[source] = "w"
        board[index_of(4, 3)] = "b"

        moves = capture_moves_for_piece(board, source)

        self.assertIn(index_of(5, 4), {move.destination for move in moves})

    def test_multiple_capture_keeps_the_turn(self):
        board = self.empty_board()
        source = index_of(5, 0)
        board[source] = "w"
        board[index_of(4, 1)] = "b"
        board[index_of(2, 3)] = "b"

        first = apply_move(board, WHITE, source, index_of(3, 2))
        self.assertTrue(first.continuation)
        second = apply_move(first.board, WHITE, index_of(3, 2), index_of(1, 4))
        self.assertEqual(second.winner, WHITE)

    def test_piece_promotes_and_continues_capture_as_king(self):
        board = self.empty_board()
        source = index_of(2, 1)
        destination = index_of(0, 3)
        board[source] = "w"
        board[index_of(1, 2)] = "b"
        board[index_of(2, 5)] = "b"

        result = apply_move(board, WHITE, source, destination)

        self.assertEqual(result.board[destination], "W")
        self.assertTrue(result.continuation)
        self.assertIn(
            index_of(3, 6),
            {move.destination for move in capture_moves_for_piece(result.board, destination)},
        )

    def test_king_can_move_across_empty_diagonal(self):
        board = self.empty_board()
        source = index_of(4, 3)
        board[source] = "W"

        destinations = {
            move.destination for move in simple_moves_for_piece(board, source)
        }

        self.assertIn(index_of(0, 7), destinations)
        self.assertIn(index_of(7, 0), destinations)


if __name__ == "__main__":
    unittest.main()
