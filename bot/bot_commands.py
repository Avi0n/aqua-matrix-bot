import asyncio

from chat_functions import send_text_to_room
from sqlite_functions import populate_db

class Command(object):
    def __init__(self, client, store, config, command, room, event):
        """A command made by a user

        Args:
            client (nio.AsyncClient): The client to communicate to matrix with

            store (Storage): Bot storage

            config (Config): Bot configuration parameters

            command (str): The command and arguments

            room (nio.rooms.MatrixRoom): The room the command was sent in

            event (nio.events.room_events.RoomMessageText): The event describing the command
        """
        self.client = client
        self.store = store
        self.config = config
        self.command = command
        self.room = room
        self.event = event
        self.args = self.command.split()[1:]

    async def process(self):
        """Process the command"""
        if self.command.startswith("add"):
            await self._add()
        elif self.command.startswith("help"):
            await self._show_help()
        else:
            await self._unknown_command()

    async def _add(self):
        """Add current room to db"""
        if self.room.is_group is True:
            text = "I'm only useful in groups atm."
            #text="Use /addme to let me forward media that you " +
            #    emojize(":star:", use_aliases=True) + " to you!")
        # Check to see if bot can be used in this group chat
        #elif check_auth_room(str(update.message.chat.id)) is False:
        #    return
        else:
            # Populate db with room's id
            room_id_orig = self.room.room_id
            print(room_id_orig)
            room_id = room_id_orig[1:].replace(':', '_')
            print(room_id)

            if populate_db(str(room_id)) is True:
                text = f"{self.room.display_name} has already been added."
            else:
                text = f"{self.room.display_name} has been added! I will now add reactions to photos/videos/gifs!"
        try:
            await send_text_to_room(self.client, self.room.room_id, text)
        except Exception as e:
            print(str(e))


    async def _show_help(self):
        """Show the help text"""
        if not self.args:
            text = ("Hello, I am a bot made with matrix-nio! Use `help commands` to view "
                    "available commands.")
            await send_text_to_room(self.client, self.room.room_id, text)
            return

        topic = self.args[0]
        if topic == "rules":
            text = "These are the rules!"
        elif topic == "commands":
            text = "Available commands"
        else:
            text = "Unknown help topic!"
        await send_text_to_room(self.client, self.room.room_id, text)

    async def _unknown_command(self):
        await send_text_to_room(
            self.client,
            self.room.room_id,
            f"Unknown command '{self.command}'. Try the 'help' command for more information.",
        )
