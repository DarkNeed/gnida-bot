"""Strict transfer lists and an atomic, replay-safe repository operation."""

import json
import re
from dataclasses import dataclass


MAX_TRANSFER_ENTRIES = 50
MAX_TRANSFER_QUANTITY = 10000
TRANSFER_COMMAND_RE = re.compile(r"^\s*[/!]?передать(?:@\w+)?(?:\s|$)", re.I)
ITEM_WORD_RE = re.compile(r"^(?:предмет(?:ы|ов)?|трактат(?:ы|ов)?)$", re.I)
SLAVE_WORD_RE = re.compile(r"^(?:раб|рабы|рабов)$", re.I)
ITEM_ENTRY_RE = re.compile(r"(?P<item>[0-9]+)(?:[xх×*:](?P<quantity>[0-9]+))?", re.I)
USER_TOKEN_RE = re.compile(r"(?:@[a-zA-Z0-9_]+|[0-9]+)")
TRANSFER_HELP = (
    "Передача рабов: /передать @раб1 @раб2 @получатель.\n"
    "Ответом получателю: /передать @раб1 @раб2.\n"
    "Предметы: /передать предмет 42x3, 57 @получатель.\n"
    "Ответом получателю: /передать предмет 42x3, 57.\n"
    "Можно написать несколько команд /передать отдельными строками. "
    "Не больше 50 позиций за сообщение; x3 означает три экземпляра."
)


@dataclass(frozen=True)
class TransferRequest:
    kind: str
    entries: tuple[tuple[str, int], ...]
    recipient: str | None


def parse_transfer_message(text, *, reply=False):
    """Last token is recipient without a reply; a reply supplies the recipient.

    Item commands retain the old explicit @recipient override in replies.
    Newlines can wrap a list or start another complete command, including mixed
    slave/item commands. Never silently ignore an unparsed suffix.
    """
    blocks = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        match = TRANSFER_COMMAND_RE.match(line)
        if match:
            blocks.append(line[match.end():].strip())
        elif blocks:
            blocks[-1] += " " + line.strip()
        else:
            raise ValueError(TRANSFER_HELP)
    if not blocks:
        raise ValueError(TRANSFER_HELP)
    requests, total = [], 0
    for block in blocks:
        tokens = block.split()
        kind = "slave"
        if tokens and ITEM_WORD_RE.fullmatch(tokens[0]):
            kind = "item"
            tokens.pop(0)
        elif tokens and SLAVE_WORD_RE.fullmatch(tokens[0]):
            tokens.pop(0)
        recipient = None
        if not reply or (kind == "item" and tokens and tokens[-1].startswith("@")):
            if len(tokens) < 2:
                raise ValueError(TRANSFER_HELP)
            recipient = tokens.pop()
            if not (USER_TOKEN_RE.fullmatch(recipient) or recipient.casefold() in {"мне", "себе"}):
                raise ValueError(TRANSFER_HELP)
        body = " ".join(tokens)
        # Reject empty comma-delimited entries rather than guessing intent.
        if not body or any(not part.strip() for part in body.split(",")):
            raise ValueError(TRANSFER_HELP)
        entries = []
        for token in re.split(r"[\s,]+", body):
            if kind == "item":
                match = ITEM_ENTRY_RE.fullmatch(token)
                if not match:
                    raise ValueError(TRANSFER_HELP)
                item, quantity = int(match["item"]), int(match["quantity"] or 1)
                if not 0 < item < 2**63 or not 1 <= quantity <= MAX_TRANSFER_QUANTITY:
                    raise ValueError("Номер предмета и количество должны быть положительными; количество — до 10000.")
                entries.append((str(item), quantity))
            else:
                if not USER_TOKEN_RE.fullmatch(token):
                    raise ValueError(TRANSFER_HELP)
                entries.append((token, 1))
        total += len(entries)
        if total > MAX_TRANSFER_ENTRIES or len(blocks) > MAX_TRANSFER_ENTRIES:
            raise ValueError("За одно сообщение можно передать не больше 50 позиций.")
        requests.append(TransferRequest(kind, tuple(entries), recipient))
    return requests


SLAVE_TRANSFER_ERRORS = {
    "not_owned": "Этот участник не ваш раб.",
    "recipient_is_slave": "Раб не может владеть другими рабами.",
    "self": "Нельзя передать человека самому себе.",
    "same_owner": "Этот участник уже принадлежит вам.",
    "pirojok_cannot_own": "Этот кувшин слишком тесен для вас двоих",
}


class TransferBatchMixin:
    async def transfer_batch(self, chat, actor, operations, *, source_chat=None, message_id=None):
        """Apply every operation or none; repeated delivery cannot spend twice."""
        if not isinstance(operations, (list, tuple)) or not operations or len(operations) > MAX_TRANSFER_ENTRIES:
            raise ValueError("За одно сообщение можно передать от 1 до 50 позиций.")
        normalized = []
        slaves = set()
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("Некорректные данные передачи.")
            kind, target = operation.get("kind"), operation.get("target")
            entry = operation.get("id")
            quantity = operation.get("quantity", 1)
            if (kind not in {"slave", "item"} or type(target) is not int
                    or not 0 < target < 2**63 or type(entry) is not int
                    or not 0 < entry < 2**63 or type(quantity) is not int
                    or not 1 <= quantity <= MAX_TRANSFER_QUANTITY):
                raise ValueError("Некорректные данные передачи.")
            if kind == "slave":
                if quantity != 1 or entry in slaves:
                    raise ValueError("Один и тот же раб указан несколько раз.")
                slaves.add(entry)
            normalized.append(dict(kind=kind, target=target, id=entry, quantity=quantity))
        request = json.dumps(dict(chat=chat, operations=normalized), sort_keys=True)
        replay_key = (source_chat, message_id, actor) if type(message_id) is int and message_id > 0 else None
        if replay_key and (type(source_chat) is not int or source_chat == 0):
            raise ValueError("Не указан исходный чат сообщения.")
        async with self._lock:
            with self.connection:
                if replay_key:
                    old = self.connection.execute(
                        "SELECT request_json,receipt_json FROM transfer_batches WHERE source_chat=? AND message_id=? AND actor_id=?",
                        replay_key,
                    ).fetchone()
                    if old:
                        if old["request_json"] != request:
                            raise ValueError("Это сообщение уже обработано. Для новой передачи отправь новое сообщение.")
                        return json.loads(old["receipt_json"])
                receipt = []
                for operation in normalized:
                    if operation["kind"] == "slave":
                        result = self._transfer_slave_locked(chat, actor, operation["id"], operation["target"])
                        if result != "transferred":
                            raise ValueError(f'{operation["id"]}: {SLAVE_TRANSFER_ERRORS[result]}')
                        name = str(operation["id"])
                    else:
                        name = self._arena_transfer_item_locked(
                            chat, actor, operation["id"], operation["target"], operation["quantity"])
                    receipt.append(dict(operation, name=name))
                if replay_key:
                    self.connection.execute(
                        "INSERT INTO transfer_batches(source_chat,message_id,actor_id,request_json,receipt_json) VALUES(?,?,?,?,?)",
                        (*replay_key, request, json.dumps(receipt, ensure_ascii=False)),
                    )
                return receipt
