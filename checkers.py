from __future__ import annotations

from dataclasses import dataclass


BLACK = "black"
WHITE = "white"
EMPTY = "."
BOARD_SIZE = 8


@dataclass(frozen=True)
class Move:
    source: int
    destination: int
    captured: int | None = None


@dataclass(frozen=True)
class MoveResult:
    board: list[str]
    continuation: bool
    winner: str | None
    reason: str
    captured: int | None


def initial_board() -> list[str]:
    board = [EMPTY] * (BOARD_SIZE * BOARD_SIZE)
    for row in range(3):
        for column in range(BOARD_SIZE):
            if (row + column) % 2 == 1:
                board[index_of(row, column)] = "b"
    for row in range(5, 8):
        for column in range(BOARD_SIZE):
            if (row + column) % 2 == 1:
                board[index_of(row, column)] = "w"
    return board


def index_of(row: int, column: int) -> int:
    return row * BOARD_SIZE + column


def coordinates(square: int) -> tuple[int, int]:
    return divmod(square, BOARD_SIZE)


def inside(row: int, column: int) -> bool:
    return 0 <= row < BOARD_SIZE and 0 <= column < BOARD_SIZE


def piece_color(piece: str) -> str | None:
    if piece.casefold() == "b":
        return BLACK
    if piece.casefold() == "w":
        return WHITE
    return None


def opponent(color: str) -> str:
    return WHITE if color == BLACK else BLACK


def is_king(piece: str) -> bool:
    return piece in {"B", "W"}


def capture_moves_for_piece(board: list[str], source: int) -> list[Move]:
    piece = board[source]
    color = piece_color(piece)
    if color is None:
        return []
    row, column = coordinates(source)
    moves: list[Move] = []
    directions = ((-1, -1), (-1, 1), (1, -1), (1, 1))
    if not is_king(piece):
        for row_step, column_step in directions:
            middle_row = row + row_step
            middle_column = column + column_step
            target_row = row + 2 * row_step
            target_column = column + 2 * column_step
            if not inside(target_row, target_column) or not inside(
                middle_row, middle_column
            ):
                continue
            middle = index_of(middle_row, middle_column)
            target = index_of(target_row, target_column)
            if (
                piece_color(board[middle]) == opponent(color)
                and board[target] == EMPTY
            ):
                moves.append(Move(source, target, middle))
        return moves

    for row_step, column_step in directions:
        target_row = row + row_step
        target_column = column + column_step
        captured: int | None = None
        while inside(target_row, target_column):
            target = index_of(target_row, target_column)
            target_piece = board[target]
            if target_piece == EMPTY:
                if captured is not None:
                    moves.append(Move(source, target, captured))
            elif piece_color(target_piece) == color:
                break
            elif captured is not None:
                break
            else:
                captured = target
            target_row += row_step
            target_column += column_step
    return moves


def simple_moves_for_piece(board: list[str], source: int) -> list[Move]:
    piece = board[source]
    color = piece_color(piece)
    if color is None:
        return []
    row, column = coordinates(source)
    if is_king(piece):
        moves: list[Move] = []
        for row_step, column_step in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            target_row = row + row_step
            target_column = column + column_step
            while inside(target_row, target_column):
                target = index_of(target_row, target_column)
                if board[target] != EMPTY:
                    break
                moves.append(Move(source, target))
                target_row += row_step
                target_column += column_step
        return moves

    row_step = 1 if color == BLACK else -1
    moves = []
    for column_step in (-1, 1):
        target_row = row + row_step
        target_column = column + column_step
        if inside(target_row, target_column):
            target = index_of(target_row, target_column)
            if board[target] == EMPTY:
                moves.append(Move(source, target))
    return moves


def legal_moves(
    board: list[str], color: str, forced_from: int | None = None
) -> dict[int, list[Move]]:
    if forced_from is not None:
        if piece_color(board[forced_from]) != color:
            return {}
        captures = capture_moves_for_piece(board, forced_from)
        return {forced_from: captures} if captures else {}

    captures: dict[int, list[Move]] = {}
    for source, piece in enumerate(board):
        if piece_color(piece) != color:
            continue
        piece_captures = capture_moves_for_piece(board, source)
        if piece_captures:
            captures[source] = piece_captures
    if captures:
        return captures

    moves: dict[int, list[Move]] = {}
    for source, piece in enumerate(board):
        if piece_color(piece) != color:
            continue
        piece_moves = simple_moves_for_piece(board, source)
        if piece_moves:
            moves[source] = piece_moves
    return moves


def apply_move(
    board: list[str], color: str, source: int, destination: int
) -> MoveResult | None:
    available = legal_moves(board, color)
    move = next(
        (candidate for candidate in available.get(source, []) if candidate.destination == destination),
        None,
    )
    if move is None:
        return None

    updated = list(board)
    piece = updated[source]
    updated[source] = EMPTY
    updated[destination] = piece
    if move.captured is not None:
        updated[move.captured] = EMPTY

    destination_row, _ = coordinates(destination)
    if piece == "b" and destination_row == BOARD_SIZE - 1:
        updated[destination] = "B"
    elif piece == "w" and destination_row == 0:
        updated[destination] = "W"

    if move.captured is not None and capture_moves_for_piece(updated, destination):
        return MoveResult(updated, True, None, "нужно продолжить взятие", move.captured)

    enemy = opponent(color)
    if not any(piece_color(piece) == enemy for piece in updated):
        return MoveResult(updated, False, color, "у соперника не осталось шашек", move.captured)
    if not legal_moves(updated, enemy):
        return MoveResult(updated, False, color, "у соперника нет доступных ходов", move.captured)
    return MoveResult(updated, False, None, "ход выполнен", move.captured)
