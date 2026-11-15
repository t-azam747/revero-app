"""Read your bot's private chat IDs without printing its token. Never sends a message."""
import sys
import httpx
from .digest import configuration


def main():
    token = configuration()['TELEGRAM_BOT_TOKEN']
    if not token:
        print('Set TELEGRAM_BOT_TOKEN in the ignored root .env first.')
        return 1
    try:
        response = httpx.get(f'https://api.telegram.org/bot{token}/getUpdates', timeout=15)
        data = response.json()
        if not response.is_success or not data.get('ok'):
            print('Telegram could not read updates. Check your bot token and ensure the bot has no active webhook.')
            return 1
        ids = set()
        for update in data.get('result', []):
            message = update.get('message') or update.get('edited_message') or {}
            chat = message.get('chat', {})
            if chat.get('type') == 'private':
                ids.add(chat['id'])
        if not ids:
            print('Open your bot in Telegram, press Start, and send it a message. Then run this command again.')
        else:
            print('Private chat IDs found (choose yours for TELEGRAM_CHAT_ID):')
            for identifier in sorted(ids): print(identifier)
        return 0
    except Exception:
        # Request exceptions can contain the credential-bearing URL.
        print('Could not read Telegram updates. Check the connection and bot settings; no token was printed.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
