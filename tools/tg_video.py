"""Copy a Telegram video that is too big for the Bot API (over 20 MB) into media/tg/.

Runs in GitHub Actions (workflow tg-video.yml), started by the site editor's Telegram inbox.
The bot logs in over MTProto (api_id/api_hash + bot token), which allows downloads up to 2 GB,
reads the message the owner forwarded to the bot (by its message id in the bot's private chat),
re-encodes it to at most 720p H.264 (480p if still over 95 MB) and writes the MP4 to OUT.

Environment: TG_API_ID, TG_API_HASH, TG_BOT_TOKEN (repository secrets), MSG_ID, OUT (workflow inputs).
"""
import asyncio, os, re, subprocess, sys, tempfile

LIMIT = 95 * 1024 * 1024


def fail(msg):
    print('ERROR: ' + msg)
    sys.exit(1)


def encode(src, dst, width, crf):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', src, '-map', '0:v:0', '-map', '0:a:0?',
           '-vf', "scale='min(%d,iw)':-2" % width, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf),
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', dst]
    subprocess.run(cmd, check=True)
    return os.path.getsize(dst)


async def main():
    for k in ('TG_API_ID', 'TG_API_HASH', 'TG_BOT_TOKEN'):
        if not os.environ.get(k):
            fail('secret %s is missing — add it under Settings > Secrets and variables > Actions' % k)
    msg = os.environ.get('MSG_ID', '')
    out = os.environ.get('OUT', '')
    if not re.fullmatch(r'\d{1,12}', msg):
        fail('bad message id')
    if not re.fullmatch(r'media/tg/[A-Za-z0-9_-]{1,80}\.mp4', out):
        fail('bad output path')
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    client = TelegramClient(StringSession(), int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'], receive_updates=False)
    await client.start(bot_token=os.environ['TG_BOT_TOKEN'])
    try:
        m = await client.get_messages(None, ids=int(msg))
        if not m:
            fail('message %s not found in the bot chat' % msg)
        if not (m.video or m.gif or (m.document and (m.document.mime_type or '').startswith('video/'))):
            fail('message %s has no video' % msg)
        size = m.file.size if m.file else 0
        print('video in message %s: %.1f MB' % (msg, size / 1048576))
        tmp = tempfile.mkdtemp()
        src = await client.download_media(m, file=os.path.join(tmp, 'in'))
    finally:
        await client.disconnect()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = encode(src, out, 1280, 28)
    if n > LIMIT:
        n = encode(src, out, 854, 30)
    if n > LIMIT:
        os.remove(out)
        fail('still %.0f MB after re-encoding — too large for GitHub' % (n / 1048576))
    print('wrote %s (%.1f MB)' % (out, n / 1048576))


asyncio.run(main())
