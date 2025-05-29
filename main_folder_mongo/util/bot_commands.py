# 📄 bot_commands.py

from telegram import BotCommand

regular_cmds = [
    BotCommand("lc", "Launch bot dashboard"),
    BotCommand("start", "Start tracking tokens"),
    BotCommand("stop", "Stop tracking tokens"),
    BotCommand("add", "Add a token to track -- /a"),
    BotCommand("remove", "Remove token from tracking -- /rm"),
    BotCommand("list", "List tracked tokens -- /l"),
    BotCommand("reset", "Clear all tracked tokens -- /x"),
    BotCommand("help", "Show help message -- /h"),
    BotCommand("status", "Show stats of tracked tokens -- /s"),
    BotCommand("threshold", "Set your spike alert threshold (%) -- /t"),
    BotCommand("upgrade", "Upgrade your tier to track more tokens -- /u"),
    BotCommand("renew", "Renew your current tier to continue tracking your tokens -- /rn"),
]

admin_cmds = [
    BotCommand("restart", "Restart the bot -- /rs"),
    BotCommand("alltokens", "List all tracked tokens -- /at"),
    BotCommand("checkpayment", "Retrieve user payment log -- /cp"),
    BotCommand("manualupgrade", "Manually upgrade user tier -- /mu"),
    BotCommand("processpayouts", "Process referral commission -- /pp"),
    BotCommand("listrefs", "View user referral data -- /lr"),
    BotCommand("addrpc", "Add rpc to rpc list -- /ar"),
    BotCommand("removerpc", "Remove rpc from rpc list -- /rr"),
    BotCommand("listrpc", "List all rpc -- /lrp"),
]

super_admin_cmds = [
    BotCommand("addadmin", "Add a new admin -- /aa"),
    BotCommand("removeadmin", "Remove an admin -- /ra"),
    BotCommand("listadmins", "List all admins -- /la"),
    BotCommand("addwallet", "Add new deposit wallets -- /aw"),
    BotCommand("addpayout", "Add withdrawal wallet -- /ap"),
    BotCommand("listwallet", "List wallets (deposit & withdrawal) -- /lw"),
    BotCommand("removewallet", "Remove deposit wallets -- /rm"),
    BotCommand("removepayout", "Remove withdrawal wallets -- /rp"),
    BotCommand("boot", "Boot the bot and reconnect to MongoDB -- /bt"),
]
