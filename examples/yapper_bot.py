"""Set YAPPER_BOT_TOKEN and put yapper.py on the import path, then run."""
import ezytools
import yapper

bot = yapper.Bot()

@bot.command('ping', 'Check the bot')
def ping(msg):
    msg.reply('Pong!')

@bot.command('rules', 'DM the rules')
def rules(msg):
    if ezytools.dm(bot, msg.author_id, 'Be kind. No spam. Have fun.'):
        msg.reply('Sent you the rules.')
    else:
        msg.reply('Could not send you a DM.')

@bot.command('announce', 'Post an announcement')
@ezytools.command_guard(bot, owner_only=True, cooldown=10)
def announce(msg):
    args = ezytools.command_arguments(msg, minimum=1, usage='/announce "your announcement"')
    if args is None:
        return
    ezytools.reply_long(msg, ' '.join(args))

@bot.command('roleinfo', 'Look up a role by name, ID, or mention')
def roleinfo(msg):
    if not msg.server_id:
        return msg.reply('Use this in a server.')
    try:
        role = ezytools.find_role(bot, msg.server_id, msg.args)
    except ValueError:
        return msg.reply('Several roles have that name. Use an ID or mention.')
    if role is None:
        return msg.reply('Role not found.')
    msg.reply(f'{role["name"]}: {role["id"]}')


ezytools.register_help(bot)

if __name__ == '__main__':
    bot.run()
