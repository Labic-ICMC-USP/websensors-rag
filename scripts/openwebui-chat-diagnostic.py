"""Diagnóstico somente de leitura de uma conversa; não imprime conteúdo ou chaves."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


PARAMETERS = {'max_tokens', 'max_completion_tokens', 'num_predict', 'num_ctx', 'stream', 'reasoning_effort'}
TOKEN_FIELDS = {'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens', 'reasoning_tokens'}
REASONS = {'stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'error', 'STOP', 'MAX_TOKENS', 'SAFETY', 'RECITATION', 'OTHER', 'MALFORMED_FUNCTION_CALL'}


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def safe_parameters(value):
    if not isinstance(value, dict):
        return {}
    result = {key: item for key, item in value.items() if key in PARAMETERS and isinstance(item, (int, float, bool, str)) and (not isinstance(item, str) or item in {'none','minimal','low','medium','high','max'})}
    if 'stop' in value:
        stops = value['stop'] if isinstance(value['stop'], list) else [value['stop']]
        result['stop_sequences_count'] = len([v for v in stops if isinstance(v, str) and v])
        result['stop_contains_newline'] = any(isinstance(v, str) and '\n' in v for v in stops)
    return result


def generation_details(value, path=''):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            label = f'{path}.{key}' if path else key
            if key in TOKEN_FIELDS and type(item) in (int, float):
                result[label] = item
            elif key in {'finish_reason', 'native_finish_reason'}:
                result[label] = item if isinstance(item, str) and item in REASONS else 'unavailable_or_other'
            elif key not in {'content', 'messages', 'tool_calls', 'files'} and isinstance(item, (dict, list)):
                result.update(generation_details(item, label))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(generation_details(item, f'{path}[{index}]'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chat-id', required=True)
    parser.add_argument('--db', default=str(Path(os.environ.get('DATA_DIR', '/app/backend/data'))/'webui.db'))
    args = parser.parse_args()
    path = Path(args.db).resolve()
    if not path.is_file():
        raise SystemExit('Banco SQLite não encontrado no caminho esperado; nenhuma alteração realizada.')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    connection.execute('PRAGMA query_only = ON')
    try:
        row = connection.execute('SELECT chat, user_id FROM chat WHERE id = ?', (args.chat_id,)).fetchone()
        if row is None:
            raise SystemExit('Conversa não encontrada; confira o ID da conversa na URL.')
        chat = decode(row[0])
        messages = (chat.get('history') or {}).get('messages') or {}
        messages = list(messages.values()) if isinstance(messages, dict) else []
        if not messages:
            messages = chat.get('messages') or []
        assistants = [m for m in messages if isinstance(m, dict) and m.get('role') == 'assistant']
        report = {'chat_id': args.chat_id, 'chat_parameters': safe_parameters(chat.get('params')), 'assistant_messages': []}
        for message in assistants[-3:]:
            content = message.get('content')
            report['assistant_messages'].append({
                'message_id': message.get('id'), 'model': message.get('model'), 'done': message.get('done'),
                'content_characters': len(content) if isinstance(content, str) else None,
                'parameters': safe_parameters(message.get('params')),
                'generation_metadata': generation_details(message),
            })
        try:
            row = connection.execute('SELECT settings FROM user WHERE id = ?', (row[1],)).fetchone()
            settings = decode(row[0]) if row and row[0] else {}
            report['account_parameters'] = safe_parameters(settings.get('params'))
            report['account_ui_parameters'] = safe_parameters((settings.get('ui') or {}).get('params'))
        except sqlite3.OperationalError:
            report['account_parameters_available'] = False
        models = set(chat.get('models') or [])
        models.update(m.get('model') for m in assistants if isinstance(m.get('model'), str))
        report['model_parameters'] = {}
        for model in models:
            try:
                row = connection.execute('SELECT params FROM model WHERE id = ?', (model,)).fetchone()
                if row:
                    report['model_parameters'][model] = safe_parameters(decode(row[0]))
            except sqlite3.OperationalError:
                break
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('\nValores ausentes não significam ausência de limite. O OpenWebUI pode não ter persistido o motivo de término ou os parâmetros efetivamente enviados.')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
