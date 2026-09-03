

from typing import Optional
from enum import Enum

SERVER_INDEX = 0
CATALOG_INDEX = 1
SCHEMA_INDEX = 2
TABLE_INDEX = 3
MAX_PARTS = 4


class IdentifierError(ValueError):
    pass

class State(Enum):
    INIT = 0
    IN_PART = 1
    IN_QUOTED_PART = 2
    AFTER_QUOTE = 3
    AFTER_DOT = 4


def parse_multipart_identifier(
    name,
    allow_empty = False
):
    """
    Parse SQL Server multipart identifiers.

    Example:
        MyDB.dbo.Users
        [My.DB].[dbo].[Users]
        "My.DB"."dbo"."Users"
    """

    if not name.strip():
        if allow_empty:
            return [None] * MAX_PARTS
        raise IdentifierError('Empty identifier is not allowed')

    parts = []
    current_state = State.INIT
    current_part = ''
    quote_char = ''

    # State machine
    it = enumerate(name)

    for index, ch in it:
        if current_state == State.INIT or current_state == State.AFTER_DOT:
            if ch.isspace():
                # Skip leading whitespace
                continue
            elif ch == '[' or ch == '"':
                # Start quoted identifier
                quote_char = ch
                current_state = State.IN_QUOTED_PART
            elif ch == '.':
                # Empty part before dot
                if not allow_empty and len(parts) == 0:
                    raise IdentifierError('Empty identifier is not allowed')
                parts.append('')
                current_state = State.AFTER_DOT 
            else:
                # Start unquoted identifier
                current_part += ch
                current_state = State.IN_PART
        elif current_state == State.IN_PART:
            if ch == '.':
                # End of part
                parts.append(current_part.rstrip())
                current_part = ''
                current_state = State.AFTER_DOT
            else:
                current_part += ch
        elif current_state == State.IN_QUOTED_PART:
            closing_quote = ']' if quote_char == '[' else '"'

            if ch == closing_quote:
                # Check for escaped quote (]] or "")
                if index + 1 < len(name) and name[index + 1] == closing_quote:
                    # Escaped quote - add one closing quote to the part
                    current_part += closing_quote
                    next(it) # skips next item
                else:
                    # End of quoted part
                    current_state = State.AFTER_QUOTE
            else:
                current_part += ch
        elif current_state == State.AFTER_QUOTE:
            if ch.isspace():
                # skip whitespace after quote
                continue
            elif ch == '.':
                # end of part
                parts.append(current_part)
                current_part = ''
                quote_char = ''
                current_state = State.AFTER_DOT
            else:
                raise IdentifierError(f'Unexpected character {ch} after quote')
            
    # Handle final part
    if current_state == State.IN_PART or current_state == State.AFTER_QUOTE:
        parts.append(current_part.strip())
    elif current_state == State.IN_QUOTED_PART:
        raise IdentifierError('Unclosed quoted identifier')
    elif current_state == State.INIT:
        if not allow_empty:
            raise IdentifierError('Empty identifier is not allowed')
        
    # Validate part count
    if len(parts) > MAX_PARTS:
        raise IdentifierError(f'Too many identifier parts {len(parts)} (maximum is {MAX_PARTS})')

    # Right justify
    result = [None] * MAX_PARTS
    start = MAX_PARTS - len(parts)

    for i, part in enumerate(parts):
        result[start + i] = part

    return result

def escape_identifier(name, force_wrap = False):
    if name is None or not isinstance(name, str):
        return name
    name = name.replace(']', ']]').replace('"', '""')
    if ']]' in name or force_wrap:
        # only wrap when escaping
        return f'[{name}]'
    return name

def escape_string_literal(name):
    return name.replace("'", "''")

def build_multipart_name(*parts, force_wrap = False):
    result = ''
    force_wrap = len(parts) > 1 or force_wrap

    for part in parts:
        if len(result) != 0:
            result += '.'
        result += escape_identifier(part, force_wrap=force_wrap) or ''

    return result
